# P3.32 K9 — Handler C tool-calling migration (Stage B) design memo

**Status:** Design proposal. No code changes yet. Awaiting user
approval before S1-S7 implementation begins.
**Scope:** Migrate Handler C (`estimate_payroll_headcount_schedule_
with_gpt`) from `text.format.type=json_schema` strict-mode iterative
refinement to a tool-calling session matching H2/H3/H4.
**Background:** [p3_32_handler_c_prompt_and_lookup_audit.md](./p3_32_handler_c_prompt_and_lookup_audit.md)
established the prompt-vs-table architectural gap. [p3_32_cross_
handler_prompt_audit.md](./p3_32_cross_handler_prompt_audit.md)
established that Handler C is the architectural outlier among the
five GPT-loop authors (H1-H5); every other iterative author uses
tool-calling. K8 enrichment empirically failed on Skyward because
GPT obeyed the more-prominent "revise ONLY the fields named in the
failures" rule and refused to switch class.

---

## D1. Tools to expose

Three tool functions. The first two are the canonical SQL-grounded
policy lookups that replace prose paraphrase + K8 enrichment. The
third is the proposal-with-validation tool that closes the loop on
GPT's authored schedule.

The tool definitions live in a new module:
`python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py`
following the same shape as
`post_intake_gpt_exhaustion_handler/tool_calling_session.py`.

### Tool 1 — `get_payroll_revenue_sanity_bounds`

**Purpose.** GPT calls this once with its chosen labor_intensity_
class to receive the authoritative per-class payroll/revenue
bounds + the list of alternative classes whose bounds accept any
target value. Replaces the prose paraphrase at
[schedule.py:2566](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2566)
("for medium intensity the band is 0.10..0.55") AND the K8
enrichment at [schedule.py:2156-2214](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2156-L2214).

**Input schema:**
```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["labor_intensity_class"],
  "properties": {
    "labor_intensity_class": {
      "type": "string",
      "enum": ["low", "medium", "high", "expert"]
    }
  }
}
```

**Output (Python-resolved from
`post_intake_headcount_policy_lookup.payroll_revenue_sanity_bounds_
json`):**
```json
{
  "labor_intensity_class": "high",
  "min_pct": 0.16,
  "max_pct": 0.70,
  "tolerance_pct": 0.03,
  "relative_tolerance": 0.20,
  "all_class_bounds": [
    {"labor_intensity_class": "low",    "min_pct": 0.06, "max_pct": 0.45},
    {"labor_intensity_class": "medium", "min_pct": 0.10, "max_pct": 0.55},
    {"labor_intensity_class": "high",   "min_pct": 0.16, "max_pct": 0.70},
    {"labor_intensity_class": "expert", "min_pct": 0.18, "max_pct": 0.80}
  ],
  "source_table": "post_intake_headcount_policy_lookup",
  "policy_code": "default"
}
```

**Error cases.** Unknown class → `{"error":
"labor_intensity_class_not_in_policy", "valid_classes": [...]}`. SQL
miss → machinery fail-fast (the policy table is required upstream).

**Why tool-shaped, not schema-shaped.** The bounds depend on the
class. Strict-mode JSON schemas cannot express `allOf`/`if`-`then`
([post_intake_mapping.py:3069-3078](../../python/client_intake_and_finmo/post_intake_mapping.py#L3069-L3078)
— "Phase 9 P3.13 Sunny fix #2 — OpenAI strict-mode JSON schema does
NOT permit allOf"). Tool-call lookup is the canonical workaround
already proven by H2/H3/H4.

### Tool 2 — `find_classes_accepting_target_payroll_pct`

**Purpose.** GPT calls this when stuck — given a target_payroll_pct
GPT believes is operationally right, which classes will accept it?
Surfaces the same information Tool 1's `all_class_bounds` does, but
filtered to the currently-feasible set. This is the K8 enrichment
promoted from buried-JSON to first-class tool result. GPT may also
use it BEFORE picking a class — proposing a target first, then
choosing among the classes that accept it.

**Input schema:**
```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["target_payroll_percent_of_revenue"],
  "properties": {
    "target_payroll_percent_of_revenue": {
      "type": "number"
    }
  }
}
```

**Output:**
```json
{
  "target_payroll_percent_of_revenue": 0.105,
  "accepting_classes": [
    {"labor_intensity_class": "low",    "min_pct": 0.06, "max_pct": 0.45},
    {"labor_intensity_class": "medium", "min_pct": 0.10, "max_pct": 0.55}
  ],
  "rejecting_classes": [
    {"labor_intensity_class": "high",   "min_pct": 0.16, "max_pct": 0.70},
    {"labor_intensity_class": "expert", "min_pct": 0.18, "max_pct": 0.80}
  ],
  "source_table": "post_intake_headcount_policy_lookup"
}
```

**Error cases.** Non-numeric input → `{"error":
"target_must_be_numeric"}`. Out-of-overall-envelope (e.g., 0.95)
returns an empty `accepting_classes` list — that IS the signal that
the operator is asking for something the policy refuses for every
class.

**Implementation.** Wraps the existing
[intensity_classes_accepting_target_payroll_pct](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L853)
helper (which already exists from K8) and additionally returns the
rejecting classes for symmetry.

### Tool 3 — `propose_payroll_headcount_schedule`

**Purpose.** GPT's final-output channel. Carries the full payroll
schedule (capacity_labor_model, labor_intensity_class, wage_position
ing_tier, wage_positioning_multiplier, capacity_units_per_supporting
_fte, target_payroll_percent_of_revenue, rationale, payroll_head
count_grid). The tool runs Layers A.1 + A.2 + A.3 against the
proposal and returns the validator outcome as the tool response.
Matches H4's `probe_stage_ramp_contract` pattern exactly.

**Input schema.** The full payroll_headcount_schedule contract,
identical to the current strict-mode output schema generated by
`post_intake_gpt_contract_openai_schema(PAYROLL_HEADCOUNT_CONTRACT_
NAME, ...)`. We reuse that builder verbatim — no parallel schema
definition. The tool wraps it in a `{"type": "function",
"parameters": <schema>, "strict": true}` shell.

**Output (validator-accepted):**
```json
{
  "validator_accepted": true,
  "validator_error_text": null,
  "validator_error_code": null,
  "structured_failures": [],
  "summary": {
    "labor_intensity_class": "medium",
    "target_payroll_percent_of_revenue": 0.45,
    "policy_band": {"min_pct": 0.10, "max_pct": 0.55}
  }
}
```

**Output (validator-rejected, contract-table errors):**
```json
{
  "validator_accepted": false,
  "validator_error_code": "payroll_headcount_contract_table_validation_failed",
  "validator_error_text": "...",
  "structured_failures": [],
  "contract_table_errors": ["..."]
}
```

**Output (validator-rejected, A.2 structured failures with K8
enrichment IN-LINE):**
```json
{
  "validator_accepted": false,
  "validator_error_code": "payroll_headcount_contract_payload_validation_failed",
  "structured_failures": [
    {
      "field": "target_payroll_percent_of_revenue",
      "category": "out_of_range",
      "actual_value": 0.105,
      "required_range": {"min": 0.16, "max": 0.70},
      "labor_intensity_class": "high",
      "alternatives": {
        "accepting_classes": [
          {"labor_intensity_class": "low",    "min_pct": 0.06, "max_pct": 0.45},
          {"labor_intensity_class": "medium", "min_pct": 0.10, "max_pct": 0.55}
        ]
      },
      "guidance": "Either move target into [0.16, 0.70] for high OR switch class to one in alternatives.accepting_classes."
    }
  ]
}
```

**Output (validator-rejected, A.3 economic feasibility):**
```json
{
  "validator_accepted": false,
  "validator_error_code": "payroll_headcount_contract_economic_feasibility_failed",
  "compacted_violations": { ... existing _compact_payroll_failure_for_gpt() output ... }
}
```

**Important — tool result is INFORMATIONAL, not committing.** This
matches H2/H3/H4: the verified candidate is selected by the session
on the most-recent `validator_accepted=True` tool call. GPT does
NOT separately emit a final-commit JSON. The session writes the
candidate's arguments through the canonical apply chain after the
loop ends.

**Error cases.** JSON parse failure on tool arguments → returns
`{"validator_accepted": false, "validator_error_code":
"tool_arguments_not_json"}` so GPT can re-issue with correct shape.

### What stays out of the tool surface

- **stage_ramp_contract context** stays in the initial user prompt
  (read-only context, not a queryable surface). Matches H2/H3/H4
  pattern: operating_model is in the prompt; the tool returns
  computation results.
- **payroll_decision_options** content (enum lists, wage_position
  ing_options) collapses into the initial user prompt as
  pre-resolved Python output. GPT no longer needs to be reminded
  to "choose from X" — the enums are in the tool schema for Tool 3.
- **oews_title_catalog** stays in the initial user prompt. The
  catalog has hundreds of entries; making it tool-queryable would
  invite N round-trips to enumerate candidates. The catalog
  pre-filter (NAICS / state) already happens in Python.
- **mini_finmo-style payroll trajectory probe.** Considered, but
  rejected for K9 scope. Payroll dollars are derived deterministi
  cally from FTE × OEWS wage × multiplier × benefits %; there is
  no judgment on the payroll trajectory itself for GPT to probe.
  The validator IS the trajectory check (A.3 economic feasibility).
  Adding a mini_finmo probe before propose would just duplicate
  Layer A.3.

---

## D2. SQL table usage

**Canonical sources, no new tables, no column adds.**

| Tool | SQL source | Column |
|------|-----------|--------|
| Tool 1 `get_payroll_revenue_sanity_bounds` | `post_intake_headcount_policy_lookup` | `payroll_revenue_sanity_bounds_json` (per-class JSON), `payroll_revenue_sanity_tolerance_pct`, `payroll_revenue_sanity_relative_tolerance` |
| Tool 2 `find_classes_accepting_target_payroll_pct` | `post_intake_headcount_policy_lookup` | same `payroll_revenue_sanity_bounds_json` |
| Tool 3 `propose_payroll_headcount_schedule` | `post_intake_gpt_contract_lookup` (for schema) + `post_intake_headcount_policy_lookup` (for validation) | n/a — invokes existing `validate_payroll_headcount_contract_payload` + `build_payroll_headcount_payload_from_contract` + `_assert_payroll_contract_economic_feasible_for_retry` |

**No column adds are needed.** All policy data referenced by the
three tools already lives in `post_intake_headcount_policy_lookup.
payroll_revenue_sanity_bounds_json` ([lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79)).
The K8 alternative-class computation is already implemented at
[lookup.py:853](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L853)
(`intensity_classes_accepting_target_payroll_pct`).

**No new tables.** Per the user's guiding principle #2.

---

## D3. Prompt restructure

### New system prompt (content)

Universal across all NAICS / archetypes / stages. No business-type
special cases.

```
You are authoring a 20-quarter payroll headcount schedule for a
business plan. The schedule pins capacity_labor_model, labor_inten
sity_class, wage_positioning_tier, wage_positioning_multiplier,
capacity_units_per_supporting_fte, target_payroll_percent_of_
revenue, the per-OEWS-title FTE grid (start, hires, end) for Q1-Q20,
and a rationale.

You have three tools.

1. get_payroll_revenue_sanity_bounds(labor_intensity_class) returns
   the authoritative per-class min/max target_payroll_percent_of_
   revenue bounds for the policy. Call this when you want to know
   what target a class will accept. The result includes the bounds
   for every class in the policy, so one call gives you the full
   picture.

2. find_classes_accepting_target_payroll_pct(target_payroll_
   percent_of_revenue) returns the classes whose bounds accept a
   given target value. Call this when the operating model points
   you at a specific payroll/revenue ratio and you need to pick
   the class that fits. Or call it when propose_payroll_headcount_
   schedule has rejected a (class, target) pairing — the tool will
   show you which alternative classes accept your target.

3. propose_payroll_headcount_schedule(...) submits a full schedule
   for validation. The tool returns validator_accepted: true OR
   false with structured failures. Iterate until validator_accepted
   is true. The system uses your most recent accepted proposal as
   the committed schedule.

You may call the three tools in any order any number of times within
the budget. Class and target are equally mutable. If a class you
selected rejects your target, you may either move the target into
that class's band OR switch to a class whose band already accepts
your target — both resolutions are equally valid; choose whichever
better fits the operating model.

When iterating: do not reuse a (class, target) pairing that has
already been rejected. The structured failure will name the
alternatives.
```

### New task instruction (user prompt body)

This is the per-business context block, built freshly each session
from `user_context`. Replaces the current static task_instruction
at [schedule.py:2542-2571](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2542-L2571).

```
OPERATING CONTEXT:
{user_context as JSON, same content currently passed to GPT EXCEPT
 the policy-bound paraphrases at lines 2562, 2566-2567 are removed
 (those facts now flow via Tool 1).}

KEY-PEOPLE INJECTION:
Python will inject the intake's key-people roster into your authored
grid before final commit. You author supporting-staff OEWS titles
and their FTE schedule only; do not include key people in your grid.

OEWS TITLE SELECTION:
Every oews_occ_title in payroll_headcount_grid must be an exact
title from oews_title_catalog.title_candidates above. Each title
you include must carry positive FTE in at least one quarter; do
not author placeholder zero-FTE rows. Once a title carries positive
FTE, it must continue through Q20 (no terminations).

CAPACITY MODEL:
capacity_units_per_supporting_fte is your business-specific
productivity assumption. Python derives the supported-capacity
envelope from total average FTE × capacity_units_per_supporting_
fte; revenue is constrained downstream by that envelope. Do not
clip FTE to a hard capacity demand floor.

TARGET PAYROLL PERCENT:
target_payroll_percent_of_revenue is a decimal (0.45 = 45%, not
45 and not 0.045). The policy enforces per-class bands via Tool 1.
Choose your class and target together; consult Tool 1 or Tool 2
when in doubt.

STAGE RAMP CONTRACT:
The stage_ramp_contract below is read-only context. Use it to align
ramp shape; do not change ramp.

TASK:
Author the payroll headcount schedule. Call propose_payroll_head
count_schedule when you are ready to submit. Iterate until the
tool returns validator_accepted: true.
```

### What gets REMOVED from the current prompt

| Surface | Currently lives | Removed because |
|---------|----------------|-----------------|
| K8 enrichment infrastructure | [schedule.py:2156-2214](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2156-L2214) (inside `_build_payroll_iterative_feedback_packet` Class A path) | K8 alternatives now live IN-LINE in Tool 3's structured_failures (D1 above). The buried-in-user-JSON positioning is the root cause of the empirical Skyward failure (audit P4). |
| "Revise ONLY the fields named in the failures" rule | [schedule.py:2510-2516](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2510-L2516) (required_action) and [schedule.py:2569](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2569) (task_instruction) | Tool-calling is open-ended; GPT can change any field on any propose call. The directive directly caused class-immutability framing (audit P3, P5). |
| "First choose ... wage_positioning_tier, ..." framing | [schedule.py:2544](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2544) | Same — combines with "revise only" to pin class. Removed. |
| Per-class band example ("for medium intensity the band is 0.10..0.55") | [schedule.py:2566](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2566) | Replaced by Tool 1 (authoritative SQL lookup). The example was a prose paraphrase that named only one class (audit L1). |
| "applies table-backed wage positioning" prose | [schedule.py:2539](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2539) | The wage_positioning_multiplier_bounds per tier remain in `_payroll_decision_options_from_policy` which is in the user_context block; this prose pointer is redundant now that Tool 3's strict-mode schema enforces the bound per-tier via the existing contract schema. |

### What stays in the prompt

- OEWS title selection rules + continuity rules (Python invariants
  the validator enforces; GPT needs to know them up front).
- Key-people injection note (Python authors part of the grid).
- Capacity model framing (capacity_units_per_supporting_fte
  semantics).
- Decimal-vs-percent disambiguation for target_payroll_percent_of_
  revenue (0.45 vs 45 vs 0.045).
- stage_ramp_contract context block.

---

## D4. Migration plan

### What's preserved

| Surface | File | Why preserved |
|---------|------|---------------|
| `validate_payroll_headcount_contract_payload` | [schedule.py:1687](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1687) | Layer A.1 contract validation; tool-calling routes through this verbatim. |
| `build_payroll_headcount_payload_from_contract` | [schedule.py:1745+](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1745) | Layer A.2 build + Python key-people injection + wage resolution. Tool-calling routes through this verbatim. |
| `_assert_payroll_contract_economic_feasible_for_retry` | (existing) | Layer A.3 economic feasibility. Tool-calling routes through this verbatim. |
| Apply chain (capacity → headcount → finmo) | `feasibility_repair.py` | Post-handler commit chain. Unchanged. |
| Mirror Flavor 1 invariant from F6 | `assert_payroll_headcount_model_input_applied` ([schedule.py:3218](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3218)) + `assert_finmo_payroll_matches_headcount_schedule` ([schedule.py:3257](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3257)) | Three-surface assertion still fires after the apply chain. Unchanged. |
| K1 F1-F7 leak closures | (multiple sites) | All structural — none of K1 F1-F7 touched the iterative refinement loop's prompt or schema. Migration preserves them. |
| Machinery fail-fasts (7 invariants) | (existing helpers) | Adapt to new loop shape: round_count_drift, budget_decoupling, state_corruption, translator output, parse failure, best-effort-selection-drift, authority-violation. See §5b doctrine. |
| Sequence step control (`_assert_payroll_sequence_step` + process_object_control) | [schedule.py:2281+, 2436+](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2281) | Sequence guardrails fire before the GPT loop; unchanged. |
| `previous_contract_failure` external-caller seed path | `feasibility_repair.route_payroll_feasibility_to_handler_c` | The downstream feasibility repair caller still seeds Handler C with prior failure context. In the new shape, this becomes the **first user prompt addendum**, not a per-round packet. The convergence-time repair still works. |

### What's replaced

| Surface | Current | New |
|---------|---------|-----|
| OpenAI payload | `text.format.type=json_schema` strict, no `tools` | `tools=[t1, t2, t3]`, no `text.format` (assistant final text is unused) |
| Iteration mechanism | Per-round payload rebuild with `previous_contract_failure` packet REPLACED each round | Single conversation; tool calls + tool results accumulate naturally in `input_items` |
| Feedback packet construction | `_build_payroll_iterative_feedback_packet` translates exception to structured packet, attaches K8 enrichment, hands to next round's required_action | Validator outcome IS the Tool 3 response. K8 enrichment is IN-LINE in the structured_failures. No separate packet. |
| Commit selection | First round whose schedule passes A.1+A.2+A.3 returns | Verified-commit-candidate: most recent Tool 3 call with `validator_accepted=True` wins (matches H2/H3/H4) |
| Budget unit | 10 rounds, each round = 1 GPT call + Python validation | 10 tool calls; tool calls count, intermediate GPT thinking turns do not. Hard cap matches doctrine §5. |
| Exhaustion behavior | Hard-fail with `payroll_iterative_refinement_exhausted` after 10 rounds | Hard-fail with new code `payroll_tool_calling_session_exhausted` (matches H4's exhaustion code shape) carrying the same diagnostic shape (final failure code, message, raw response). Best-effort selection NOT taken — payroll commits must be validator-accepted; this matches the current behavior. |

### What's deleted

- `_build_payroll_iterative_feedback_packet` ([schedule.py:2079-2242](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2079-L2242)) — replaced by inline structured_failures in Tool 3 response.
- The `previous_contract_failure` JSON envelope construction at [schedule.py:2507-2529](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2507-L2529) — collapsed into tool result.
- The `_PAYROLL_ITER_GPT_CALL_COUNT` contextvar machinery — replaced by tool-call counter in the new session module.

Per memory `feedback_remove_dont_just_cutoff.md`: these are deleted, not routed around. The functions are no longer called from anywhere after the migration; we remove the function bodies (not stubs).

### Test plan

**M1 — tool schema correctness (3 unit tests).**
- `test_get_payroll_revenue_sanity_bounds_schema_strict_valid` — schema validates under Responses API strict-mode rules.
- `test_find_classes_accepting_target_payroll_pct_schema_strict_valid` — same.
- `test_propose_payroll_headcount_schedule_schema_matches_contract` — Tool 3's parameter schema is bit-identical to the existing strict-mode JSON schema for PAYROLL_HEADCOUNT_CONTRACT_NAME.

**M2 — tool function semantics (8 unit tests).**
- `test_tool_1_returns_bounds_for_known_class` (4 classes × 1 = 4 tests, parametrized).
- `test_tool_1_includes_all_class_bounds`.
- `test_tool_1_rejects_unknown_class`.
- `test_tool_2_returns_accepting_and_rejecting_partition` (parametrized: 0.05 → all reject; 0.20 → high accepts only; 0.45 → low/medium accept).
- `test_tool_2_returns_empty_accepting_for_out_of_envelope_target`.
- `test_tool_3_calls_existing_validator_chain` — assert the propose tool routes through validate / build / economic_feasibility unchanged.
- `test_tool_3_returns_structured_failures_with_k8_enrichment_inline` — A.2 out_of_range failure carries `alternatives.accepting_classes` in the result.
- `test_tool_3_returns_economic_feasibility_compact_on_a3_failure`.

**M3 — session-loop integration (6 behavioral tests, mocked LLM).**
- `test_session_commits_on_first_validator_accepted_tool_call`.
- `test_session_replaces_candidate_on_subsequent_validator_accepted` — most-recent-wins.
- `test_session_exhausts_hard_cap_without_accepted_call_hard_fails`.
- `test_session_handles_unknown_tool_name_gracefully`.
- `test_session_handles_tool_arguments_not_json` — returns structured error to GPT, GPT can retry.
- `test_session_seeds_initial_prompt_from_previous_contract_failure_external_caller`.

**Regression — existing test set (M4):** Re-run the full payroll
test suite (currently 434/437 passing; budget allows at most 2%
drop = ~9 tests). Specifically:
- `tests/test_phase_9_p3_32_k1_*` — all K1 F1-F7 regression tests.
- `tests/test_phase_9_p3_32_k1_k8_*` — the new K8 class-switching feedback test (already authored in this session per `?? tests/test_phase_9_p3_32_k1_k8_class_switching_feedback.py`). K8's enrichment moves from the iterative-refinement feedback packet to Tool 3's structured_failures; the test must be updated to assert the new location.
- The full P3.32 sweep harness's existing M-tests.

---

## D5. Doctrine implications

### Proposed addition to doctrine.md §6

A new row in the "GPT-as-authoring-source" table is not needed —
Handler C is already there. But the row's "Why it stays GPT-
authored" cell gains an explicit note about the tool-calling
architecture:

> Migrated from strict-mode iterative refinement to tool-calling
> session at P3.32 K9 (commit `phase_9_p3_32_k9_handler_c_tool_
> calling_migration_stage_b`). Three tools surface canonical policy
> bounds (Tool 1, Tool 2) + final-proposal validation (Tool 3).
> Matches H2/H3/H4 architecture.

### Proposed §10.4 addition — tool-calling as canonical pattern for GPT iterative loops

```
### 10.4 CORRECTION 3 — Tool-calling is the canonical pattern for
GPT iterative loops over policy-bounded structured outputs

Discovered during P3.32 K9. Handler C originally used strict-mode
json_schema iterative refinement with per-round feedback packets.
The audit established this pattern produces four pathologies that
tool-calling avoids by construction:

  - Prompt directives that conflict with policy-data enrichment
    (audit P3, "revise only named fields" vs K8 alternative-class
    enrichment).
  - JSON-burial of enrichment behind less-relevant prose (audit P4,
    K8 alternatives 5 levels deep in user-message JSON).
  - Implicit field-immutability framing ("first choose ... then
    revise only", audit P5).
  - Replace-only feedback that obscures stuck-strategy patterns
    (audit P7).

H2 (exhaustion), H3 (funding), H4 (stage_ramp) already use
tool-calling and exhibit none of these pathologies. Migrating
Handler C closed the gap.

Going forward: any new GPT loop that consults policy data and
emits structured output MUST use tool-calling. Strict-mode
json_schema iterative refinement is forbidden for new sites.

H5 (stage_ramp_contract estimator) remains single-shot strict-mode;
its single-shot shape doesn't compound the iteration-drift
pathologies, and the audit's H5 evidence didn't justify migration.
If H5 produces structured outputs that downstream validation
rejects, prefer migrating H5 to tool-calling before adding
prompt-level discipline.

H2/H3/H4 are NOT being retroactively migrated (user explicit
direction at P3.32 K9). They already use tool-calling, just with
different tool surfaces.
```

The retroactive-migration prohibition is recorded so future iters
don't drift into "let's make every handler look the same" without
load-bearing justification.

### Three-surface check (preserved)

The F6 mirror invariant (payroll_headcount.quarter_totals ==
model_input.expenses.Payroll == finmo.pl.Payroll == finmo.quarter_
rows.payroll) fires AFTER Handler C returns the schedule, in the
apply chain. The apply chain is unchanged by K9. The migration is
strictly internal to the GPT loop; the assertion still fires
post-loop.

---

## D6. Scope estimate

| Surface | LOC delta | Notes |
|---------|-----------|-------|
| New module `tool_calling_session.py` | +330 | Three tool definitions (~80), session loop (~150), commit selection + diagnostic (~50), data-class containers (~50). Mirrors H4's tool_calling_session.py shape. |
| `schedule.py` removal of strict-mode loop | -220 | Deletes the 10-round loop body, `_build_payroll_iterative_feedback_packet` (incl. K8 enrichment block), `_PAYROLL_ITER_GPT_CALL_COUNT` contextvar, per-round payload rebuild. |
| `schedule.py` new `estimate_payroll_headcount_schedule_with_gpt` body | +60 | Public function shrinks to context-build + delegate to `tool_calling_session.run_payroll_tool_calling_session`. |
| `lookup.py` Tool 1/2 helpers | +20 | `intensity_classes_accepting_target_payroll_pct` already exists; add a thin `find_classes_accepting_and_rejecting_target_payroll_pct` wrapper for Tool 2's symmetric output. |
| Unit + integration tests | +250 | M1 (3) + M2 (8) + M3 (6) + small fixtures. |
| Doctrine.md edit | +35 | §10.4 addition + §6 table cell update. |
| **Net** | **+475** | Within the 500-LOC cap. Tests are ~250 of the 475 — implementation is ~225 net. |

**Risk level: MEDIUM.** Tool-calling infrastructure is well-proven
in H2/H3/H4 — no green-field architecture. Risk concentrated in:
- Session-loop bugs (mitigated by mirroring H4's pattern).
- K8 enrichment relocation (the existing
  `intensity_classes_accepting_target_payroll_pct` helper is the
  same Python; only the consumption point moves).
- Validator chain re-routing through Tool 3 (the chain itself is
  reused unchanged — just called from a different orchestrator).

**Test count target: 17 new tests** (M1+M2+M3). Existing 434
must remain passing; budget allows 2% drop (≤9 regressions),
but expectation is zero regressions.

---

## Open design questions for user review

1. **Session budget shape.** H2 uses 5+5 two-phase; H3/H4 use 8+2.
   Handler C currently uses a flat 10-round cap with no extension
   prompt. Proposal: flat 10 tool calls, no extension prompt
   (Handler C's failures historically come from class-vs-target
   mismatches in 1-2 rounds, not from budget exhaustion). Confirm
   or override.

2. **Best-effort fallback.** H2 uses best-effort on hard-cap-without
   -verified. Handler C currently hard-fails (no best-effort —
   payroll commits must be validator-accepted). Proposal: KEEP
   hard-fail behavior in K9. Best-effort payroll would silently
   commit an out-of-policy schedule. Confirm.

3. **Tool 3 strict_mode.** The current strict-mode schema has been
   working for the contract structure. Confirm: Tool 3's
   `parameters` block reuses the EXACT same builder (`post_intake_
   gpt_contract_openai_schema(PAYROLL_HEADCOUNT_CONTRACT_NAME)`)
   with `strict: True`, no parallel definition.

4. **`previous_contract_failure` external-caller seed.** Currently
   the convergence-time payroll-repair caller (`feasibility_repair.
   route_payroll_feasibility_to_handler_c`) passes a failure
   context into Handler C. Under the new tool-calling shape, this
   becomes an additional sentence in the initial user prompt
   ("Note: a prior schedule was rejected for the following reason:
   <text>; iterate to a corrected schedule"). Confirm this
   re-shaping is acceptable (no caller-side changes needed).

5. **Doctrine §10.4 retroactive-migration prohibition.** The text
   proposed in D5 forbids retroactively migrating H2/H3/H4. Confirm
   this language captures user intent. Edit/strengthen as
   appropriate.

---

No code changes proposed. Awaiting explicit user approval before
S1-S7 implementation begins.
