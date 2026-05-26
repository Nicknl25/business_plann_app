# P3.40 Contract 5 — IntakeDraftContract — Pre-spec trace

**Boundary:** 1 (INTAKE → POST_INTAKE).
**Status:** pre-spec trace. Holds for review before the spec doc is drafted.
**Companion to:** [p3_40_contract_5_intake_draft_spec.md](./p3_40_contract_5_intake_draft_spec.md) (not yet written).
**v2 inventory baseline:** [p3_40_pipeline_data_flow_inventory_v2.md §Boundary 1](./p3_40_pipeline_data_flow_inventory_v2.md#boundary-1-intake--post_intake) (lines 202-247).
**v1 inventory baseline (richer details):** [p3_40_pipeline_data_flow_inventory.md §Boundary 1](./p3_40_pipeline_data_flow_inventory.md#boundary-1-intake--post_intake) (lines 61-163).

Same trace-before-spec discipline as Contracts 1, 2, 3, 4: enumerate
the actual producer + consumer call paths from production code,
surface divergences from the v2 inventory and the directive's
framing, and call out anything that would change the shape of the
contract before the spec is written.

---

## Headline findings — read these first

1. **The boundary surface is 8 top-level JSON fields** persisted to
   the `intake_consult_drafts` SQL row and parsed by post-intake
   at [runner.py:190-197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L190).
   Roster is unchanged from v1/v2 inventory; line numbers verified
   verbatim.

2. **Persistence is INCREMENTAL, not single-shot.** `append_messages`
   at [intake_consult_draft.py:1781-1955](../../python/client_intake_and_finmo/intake_consult_draft.py#L1781)
   accepts every JSON column as `Optional` and only UPDATEs the
   columns the caller passes. 20+ call sites in `intake_consult.py`
   (line numbers 2113, 8251, 8388, 8542, 8746, 8842, 9011, 9059,
   9358, 9526, 9712, 9743, 9843, 9875, 10012, 10047, 10075, 10618,
   10762, 10825). **Producer-side single-gate is infeasible**;
   this is the Contract 2 R8 pattern, not the Contract 3 single-
   producer pattern. T7 elaborates.

3. **T4 fulfillment_json: v1 specific mechanism CLOSED (corrected
   rationale), broader phantom RESIDUAL.** The v1-cited
   silent-drop site (runner.py:854 →
   `estimate_balance_sheet_contextual_seed_with_gpt(fulfillment_context=fulfillment_json)`)
   IS structurally closed, but NOT for the reason v1 implied.
   The function still exists at
   [post_intake_contracts/runner.py:1447](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1447)
   with its full body; its declared parameters do not include
   `fulfillment_context` / `fulfillment_json`, so the function
   could not accept fulfillment_json even if called with that
   kwarg. It's plumbed as a Callable parameter to
   [initial_grid/runner.py:53](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L53)
   but **never invoked inside that file** (Tier-F forwarded-
   but-unused pattern, same as Contract 3 identified for other
   params). Broader phantom still holds: fulfillment_json is
   parsed + threaded through 5 downstream dicts in runner.py and
   never structure-read by any consumer per Contract 3's trace
   (Tier-B closure-captured-but-explicitly-unused per the
   closure docstring at orchestrator.py:625-630). §T4 enumerates
   the corrected lifecycle and classifies the disposition.

4. **All 8 fields are FALLBACK_PATH reads** via `parse_json_dict`
   which silently returns `{}` on missing or malformed JSON.
   Defensive by design — but means a malformed write upstream
   surfaces as an empty plan rather than a contract violation.
   The boundary gate would close this hole.

5. **Composition: ZERO with prior contracts.** Contract 5 is
   upstream of Contracts 1-4. Inverse retrofits (where Contract
   3+'s deferred-from-Flag-4 shapes would retrofit to compose
   Contract 5) are R-residual, not Contract 5's scope. §T5
   elaborates.

---

## T1. Producer-side assembly + persist sites

### T1.1 No single assembly site — 20+ incremental writes

Unlike Contract 3's solver-input bundle (single assembly at
runner.py:1830) or Contract 4's solver-output dict (orchestrator
return statement), the intake draft is **assembled across many
chat turns** through repeated UPDATEs to the SQL row.

`append_messages` at
[intake_consult_draft.py:1781-1955](../../python/client_intake_and_finmo/intake_consult_draft.py#L1781)
is the uniform persistence helper. Its signature accepts
**every** JSON column as `Optional[Dict[str, Any]] = None`; for
each one provided, the function appends `"<column> = %s"` to the
SET clause + `json.dumps(<column>, ensure_ascii=False)` to the
values list (lines 1953-1955 for fulfillment_json — same pattern
for all 8 JSON columns + ~10 other Optional columns).

**Caller sites for `append_messages` in intake_consult.py**
(grep count: 20+):

| Line | Context |
|---|---|
| 2113 | initial draft creation |
| 8251 | finalize-step persist after consultant returns |
| 8388 | post-edit persist |
| 8542, 8746, 8842 | various consultant finalize sites |
| 9011, 9059 | patch-system writes |
| 9358, 9526 | edit/replay sites |
| 9712, 9743 | resume-checkpoint writes |
| 9843, 9875, 10012, 10047, 10075 | post-completion persists |
| 10618, 10762, 10825 | trace / lifecycle persists |

Each call writes whatever subset of columns the caller cares about
and leaves the rest untouched. The SQL row's "final" state is
whatever the most recent `append_messages` call for each column
left it at — there is no "complete the draft" gate.

### T1.2 Per-field producers (intake-side write sites)

Lifted from v1 inventory §A (file:line citations verified verbatim
where line numbers still match; otherwise drift documented in T8):

| Field | Producer | Notes |
|---|---|---|
| `operating_model_json` | `consultant_finalize` at [intake_consultant.py:583](../../python/client_intake_and_finmo/intake_consultant.py#L583) | OpenAI-schema-enforced |
| `target_market_json` | `target_market_finalize` at [target_market_consultant.py:659](../../python/client_intake_and_finmo/target_market_consultant.py#L659) | OpenAI-schema-enforced |
| `people_json` | `people_capability_finalize` at [people_capability_consultant.py:368](../../python/client_intake_and_finmo/people_capability_consultant.py#L368) | OpenAI-schema-enforced |
| `financials_json` | `financials_chat_turn` accumulator at [financials_consultant.py:1873](../../python/client_intake_and_finmo/financials_consultant.py#L1873) | Python-aggregated; "least schema-disciplined of the eight" per v1 |
| `financials_year1_json` | `assemble_financials_year1` at [financials_year1.py:684](../../python/client_intake_and_finmo/financials_year1.py#L684) | Python-aggregated nested-by-product shape |
| `fulfillment_json` | `_apply_scoped_patch` at [intake_consult.py:6720+](../../python/api_handlers/intake_consult.py#L6720) | Patch-system writes only; no schema gate; see §T4 |
| `marketing_model_json` | `_compute_marketing_model_json` at intake_consult.py | Carries `version: int`; reader never checks it |
| `planning_context_summary_json` | `_build_planning_context_summary_payload` at intake_consult.py | Planning-mode metadata |

Per v1, three of the eight (`operating_model_json`, `target_market_json`,
`people_json`) are OpenAI-schema-enforced. The other five are
either Python-aggregated or patch-system-driven; their shape
discipline depends entirely on the producer code, not on a schema
gate.

### T1.3 SQL persistence layer (intake_consult_draft.py)

Schema confirmed at
[intake_consult_draft.py:1081](../../python/client_intake_and_finmo/intake_consult_draft.py#L1081):
`fulfillment_json JSON NULL`. The 8 JSON columns + 10 others
(model_input_json, finmo_json, planning_run_json,
numeric_solver_feedback_json, etc.) are all `JSON NULL` columns.

Persistence is uniform: every JSON column passes through the same
`if <column> is not None: set_parts.append("<column> = %s"); values.append(json.dumps(<column>))`
pattern in `append_messages`. **No silent drop at persist for any
of the 8 boundary fields** (confirmed by grep — all 8 column
names appear in the function body).

---

## T2. Top-level draft JSON shape (the boundary surface)

Verified at [runner.py:190-197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L190).
Verbatim from source:

```python
ops_json = parse_json_dict(draft.get("operating_model_json"))
market_json = parse_json_dict(draft.get("target_market_json"))
people_json = parse_json_dict(draft.get("people_json"))
financials_json = parse_json_dict(draft.get("financials_json"))
financials_year1_json = parse_json_dict(draft.get("financials_year1_json"))
fulfillment_json = parse_json_dict(draft.get("fulfillment_json"))
marketing_model_json = parse_json_dict(draft.get("marketing_model_json"))
planning_context_summary_json = parse_json_dict(draft.get("planning_context_summary_json"))
```

Eight `parse_json_dict(draft.get("<column>"))` calls. The naming
asymmetry — `ops_json` reads `operating_model_json`, `market_json`
reads `target_market_json` — is unchanged from v1 (the post-intake
side uses shorter local names than the persisted column names).

| # | SQL column | Local var in runner.py | Required-or-optional in producer intent | Tier classification (per Contracts 3-4 pattern) |
|---|---|---|---|---|
| 1 | `operating_model_json` | `ops_json` | Required (consultant gate enforces) | A — consumed-direct |
| 2 | `target_market_json` | `market_json` | Required | A — consumed-direct |
| 3 | `people_json` | `people_json` | Required | A — consumed-direct |
| 4 | `financials_json` | `financials_json` | Required | A — consumed-direct |
| 5 | `financials_year1_json` | `financials_year1_json` | Required | A — consumed-direct |
| 6 | `fulfillment_json` | `fulfillment_json` | Optional (patch-system; no consultant required) | **F — phantom-required (see §T4)** |
| 7 | `marketing_model_json` | `marketing_model_json` | Required | A — consumed-direct |
| 8 | `planning_context_summary_json` | `planning_context_summary_json` | Required | A — consumed-direct |

Note: per v1 inventory §A, there are also **business-fact scalar
fields on the draft row** (`business_name`, `business_naics_6`,
`business_address`, etc.) that aren't JSON columns. These are
loaded by `build_shared_context` and `_targeted_process_runtime_context_from_rows`
into the `business_facts` dict that Contract 3's
`BusinessFactsForSolverContract.fact_template` types as opaque
Dict[str, Any]. **For Contract 5: include or exclude business-fact
scalars from the contract?** Flag candidate; spec doc decides.

---

## T3. Consumer-side: what runner.py reads from each field

Mirror of Contract 2 §T3 / Contract 3 §T4 / Contract 4 §T2.2
table. Tracing each top-level field through runner.py +
downstream:

| Field | Reader | What it reads from the field |
|---|---|---|
| `operating_model_json` (ops_json) | `compute_adaptive_policy` (Contract 3 trace site) | top-level dict |
| `operating_model_json` (ops_json) | `_attach_seed_provenance` ([finmo_bridge.py:339-353](../../python/client_intake_and_finmo/finmo_bridge.py#L339)) | `business_naics_6` (digits-only strip) |
| `operating_model_json` (ops_json) | `verify_structural_feasibility`, `restore_feasibility` (per Contract 3 trace) | full payload |
| `target_market_json` (market_json) | bundled into Contract 3 solver input; per Contract 3 trace T2 this is **Tier F TRULY READER_MISSING** | NEVER READ at solver boundary |
| `people_json` | `build_python_finmo_json` ([finmo_bridge.py:2931-2956](../../python/client_intake_and_finmo/finmo_bridge.py#L2931)) | full payload — per-quarter people drivers |
| `people_json` | `estimate_payroll_headcount_schedule_with_gpt` | full payload |
| `financials_json` | `compute_adaptive_policy`, `authoritative_annual_revenue`, `verify_structural_feasibility`, `restore_feasibility`, `_build_finmo_callable` closure | top-level dict |
| `financials_year1_json` | same five sites as `financials_json` | top-level dict |
| `financials_year1_json` | dual access pattern — nested via `lobs[].products[].revenue_total_year1` AND flat via `.get("company_revenue_total_year1")` | both patterns intentional per v1 §E |
| `fulfillment_json` | bundled into 5 downstream dicts (runner.py:248, 901, 1539, 1848, 1884); per Contract 3 trace **Tier B closure-only with closure docstring marking it "intentionally unused"** | **NEVER STRUCTURE-READ** post-intake (see §T4) |
| `marketing_model_json` | `_build_finmo_callable` closure | top-level dict — per Contract 3 Tier B |
| `planning_context_summary_json` | Bundled in Contract 3 SolverInputContract as **Tier C — persist-only round-trip** | Pure round-trip; no structure-read by solver |

**Phantom-required findings:**
- `target_market_json`: per Contract 3 trace T2, Tier F TRULY
  READER_MISSING across the entire solver module. Kept-required
  per Flag 2 in Contract 3 to close the door on future regressions
  if a cascade refactor unpacks it.
- `fulfillment_json`: see §T4.
- `planning_context_summary_json`: persist-only round-trip per
  Contract 3 trace TC3; no structure-read.

**No phantom-read findings** at runner.py — all 8 fields are
actively parsed. Phantom-reads (the Contract 4 inverse pattern)
don't apply at this boundary.

---

## T4. fulfillment_json full lifecycle (the headline T-task)

Per the directive: "The handoff doc flagged 'fulfillment_json
silent-drop status' as a known decision point."

### T4.1 Producer side

`fulfillment_json` is **patch-system written only** — no consultant
finalize site produces it. The single writer is `_apply_scoped_patch`
at [intake_consult.py:6720+](../../python/api_handlers/intake_consult.py#L6720)
which takes patch keys of the form `"fulfillment.<field>"` and
updates a `next_fulfillment` dict (line 6734-6770). The updated
dict propagates through the chat-turn handler and lands in an
`append_messages(..., fulfillment_json=next_fulfillment)` call.

No OpenAI-schema enforcement. No required-fields list. No
mandatory write — a draft can exist with `fulfillment_json = NULL`
in SQL if no patch ever set a `fulfillment.<field>` key.

### T4.2 Persistence

**`fulfillment_json` IS persisted.** SQL column at
[intake_consult_draft.py:1081](../../python/client_intake_and_finmo/intake_consult_draft.py#L1081):
`fulfillment_json JSON NULL`. `append_messages` parameter at
[intake_consult_draft.py:1807](../../python/client_intake_and_finmo/intake_consult_draft.py#L1807).
SQL UPDATE branch at
[intake_consult_draft.py:1953-1955](../../python/client_intake_and_finmo/intake_consult_draft.py#L1953):

```python
if fulfillment_json is not None:
  set_parts.append("fulfillment_json = %s")
  values.append(json.dumps(fulfillment_json, ensure_ascii=False))
```

Same pattern as every other JSON column. **NOT silently dropped at
persist.**

### T4.3 Consumer side — runner.py + downstream

Parsed at [runner.py:195](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L195).
Threaded into 5 downstream dicts:

| Line | Dict | Downstream consumer |
|---|---|---|
| 248 | `shared_context` | Various GPT-context payloads; opaque dict |
| 901 | `handler_kwargs` for `determine_planning_mode` | Per the handler key/value pattern, recipient does not structure-read |
| 1539 | `kwargs` for `generate_live_quarter_grid_plan` | quarter_grid handler payload |
| 1848 | Contract 3 solver-input-gate dict | Validated against `SolverInputContract` per Contract 3 Commit 3 |
| 1884 | Final bundle return | Contract 3 SolverInputContract field per the type declaration |

**Contract 3's existing trace + type system already documents
fulfillment_json's downstream fate:**
- Typed in Contract 3 as `Dict[str, Any]` opaque (Tier B closure-
  only) per [solver_input_contract.py SolverInputContract.fulfillment_json](../../python/client_intake_and_finmo/post_intake_contracts/solver_input_contract.py).
- Captured by `_build_finmo_callable` closure at
  [orchestrator.py:620-641](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L620).
- The closure docstring explicitly says:
  > `# The auxiliary kwargs (business_facts, ops_json, etc.) aren't
  >  part of build_python_finmo_json's signature — they're already
  >  stamped onto model_input_json by the time _build_model_input_overlay
  >  runs. The closure-captured args are kept here only for potential
  >  future use ...; today they are intentionally unused.`

**No production consumer structure-reads `fulfillment_json`.**

### T4.4 v1/v2 phantom mechanism — CONFIRMED CLOSED (corrected rationale) + CONFIRMED RESIDUAL (broader)

v1 inventory §D-1 cited a specific silent-drop site:
> `fulfillment_json is effectively READER_MISSING. It's parsed at
>  runner.py:200 and passed as fulfillment_context=fulfillment_json
>  to estimate_balance_sheet_contextual_seed_with_gpt at runner.py:854,
>  but the callee's signature does not accept that parameter.`

**Corrected picture (the function is NOT deleted; the broken call
site is gone for a different reason):**

1. The function **still exists** at
   [post_intake_contracts/runner.py:1447](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1447)
   with its full body. Exported in `__all__` at
   [post_intake_contracts/runner.py:390](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L390).

2. Its declared parameters are: `business_facts`, `ops_json`,
   `financials_json`, `financials_year1_json`, `model_input_json`,
   `finmo_json` (verified verbatim from the signature at lines
   1447-1455). `fulfillment_context` / `fulfillment_json` is NOT
   among them — so the function could not accept fulfillment_json
   even if a caller passed that kwarg. v1's "callee does not
   accept that parameter" half is correct.

3. The function is plumbed through to `initial_grid/runner.py` as
   a Callable parameter at
   [initial_grid/runner.py:53](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L53):
   `estimate_balance_sheet_contextual_seed_with_gpt: Callable[..., Dict[str, Any]]`.
   Bound at the API layer:
   - Module-level alias at
     [intake_consult.py:79](../../python/api_handlers/intake_consult.py#L79):
     `_estimate_balance_sheet_contextual_seed_with_gpt = _post_intake_contracts_runner._estimate_balance_sheet_contextual_seed_with_gpt`
   - Passed as kwarg at
     [intake_consult.py:7088](../../python/api_handlers/intake_consult.py#L7088):
     `estimate_balance_sheet_contextual_seed_with_gpt=_estimate_balance_sheet_contextual_seed_with_gpt`
     into the initial_grid runner call.

4. **The Callable parameter is never invoked inside
   initial_grid/runner.py.** Grep:
   `estimate_balance_sheet_contextual_seed_with_gpt(` in
   initial_grid/runner.py returns **0 results**. This is the
   Tier-F forwarded-but-unused pattern that Contract 3's trace
   identified for other params at the solver boundary
   (target_market_json, planning_result,
   catalog_source_model_input_json). The Callable is in the
   signature but never called.

5. The v1-cited call site at the historical runner.py:854 line
   no longer exists in initial_grid/runner.py — there is no
   invocation of this Callable in the file at all.

**CONFIRMED CLOSED for the specific v1 mechanism** — but the
correct rationale is "the broken call site is gone (Callable
forwarded-but-unused at initial_grid/runner.py)" rather than the
previously-stated wrong rationale "the function was deleted from
the codebase".

**CONFIRMED RESIDUAL for the broader pattern.** fulfillment_json
remains effectively unread post-intake — parsed, threaded through
5 dicts, captured by a closure that explicitly marks it
"intentionally unused" (per T4.3 + Contract 3 trace).

Independent of the Callable plumbing: `fulfillment_context=` does
not appear in initial_grid/runner.py at all (zero current call
sites with that keyword). It does appear at
[intake_consult.py:8286](../../python/api_handlers/intake_consult.py#L8286)
and [9175](../../python/api_handlers/intake_consult.py#L9175) —
both inside the interactive chat-turn handler (NOT the post-intake
system run path), confirmed by v2 inventory §C note.

### T4.5 Disposition options for the spec

Three viable contract-level dispositions:

- **(a) Type fulfillment_json as Optional[Dict[str, Any]] = None.**
  Reflects production reality: field may or may not be set; if
  set, no schema; downstream doesn't structure-read. Documents
  the silent-empty path as a known shape.
- **(b) Type fulfillment_json as required Dict[str, Any].**
  Matches the "don't loosen safety checks" stance + Contract 3
  Flag 2 disposition (Tier-F kept-required). Pin the requirement
  so a future contract loosening doesn't slip through silently.
- **(c) Drop fulfillment_json from the contract entirely.** Admits
  the field is dead. Requires a separate cleanup commit to remove
  the SQL column + the 5 runner.py threading sites + the Contract
  3 solver-input field. **Scope creep — not Contract 5's
  responsibility.**

The honest finding is that fulfillment_json is "patch-system
writes only, never required, never structure-read". (a) matches
that reality. (b) tightens it (might require fulfillment_json to
exist as `{}` rather than NULL — verify by inspecting how often
SQL NULL appears in production). (c) is dead-code removal
deferred to R-residual.

Spec doc Flag candidate (F-FULFILLMENT in §7): recommend **(a)**
unless intake side actually always writes `{}` (in which case
**(b)** matches production verbatim).

---

## T5. Composition opportunities

### T5.1 Zero composition with prior contracts

Contract 5 is **upstream of Contracts 1-4**. No prior-contract
shapes flow INTO this boundary. Contract 5 doesn't re-import
`FinmoModelInputContract` / `FinmoOutputContract` /
`PayrollHeadcountContract` / `DebtScheduleContract` /
`CapitalLeaseScheduleContract` — none of those exist at intake
time (they're downstream outputs).

### T5.2 Inverse composition (R-residual retrofits)

Several intake-domain shapes are touched by downstream contracts
as opaque `Dict[str, Any]`:

| Shape | Downstream contract | Current type | Retrofit target |
|---|---|---|---|
| `fact_template` | Contract 3 `BusinessFactsForSolverContract.fact_template` | `Dict[str, Any]` | New `IntakeBusinessFactTemplate` sub-contract here; Contract 3 retrofits to compose |
| `ops_json` | Contract 3 `SolverInputContract.ops_json` (Flag 4 opaque) | `Dict[str, Any]` | New `IntakeOpsJsonContract` here; Contract 3 retrofits |
| `financials_json` | Contract 3 (Flag 4 opaque) | `Dict[str, Any]` | New `IntakeFinancialsJsonContract` here; Contract 3 retrofits |
| `financials_year1_json` | Contract 3 (Flag 4 opaque) | `Dict[str, Any]` | New `IntakeFinancialsYear1JsonContract` here; Contract 3 retrofits |
| `people_json` | Contract 3 (Flag 4 opaque) | `Dict[str, Any]` | New `IntakePeopleJsonContract` here; Contract 3 retrofits |
| `fulfillment_json` | Contract 3 (Flag 4 opaque) | `Dict[str, Any]` | See §T4 disposition |
| `marketing_model_json` | Contract 3 (Flag 4 opaque) | `Dict[str, Any]` | New `IntakeMarketingModelJsonContract` here; Contract 3 retrofits |

**R-residual.** Contract 3's Flag 4 explicitly deferred these to
"Contract 5 (IntakeDraftContract)". Now that Contract 5 is opened,
the spec doc decides which sub-contracts ship in Commit 1a vs
defer to follow-up commits.

Spec Flag candidate (F-COMPOSITION): for each of the 7 intake-
domain shapes, decide between:
- (a) Define typed sub-contract here in Commit 1a. **Scope risk** —
  each sub-contract is potentially as large as Contract 2's
  workbook payload (which was 639 LOC for a single contract module).
- (b) Type as opaque `Dict[str, Any]` first cut; defer typed
  sub-contracts to per-shape follow-up commits (Contract 5b, 5c,
  etc.).
- (c) Mix — ship the simplest sub-contracts (e.g., consultant-
  schema-enforced ones: ops_json, target_market_json, people_json
  per v1 inventory §B) in Commit 1a; defer the rest.

Recommend **(b)** for Commit 1a — establish the boundary gate
with opaque types; sub-contract tightenings ship as Contract 5b/c/
etc. or as R-residuals. Avoids ballooning Commit 1a beyond the
700-LOC cap and lets the boundary gate land quickly.

### T5.3 OpenAI-schema-enforced sub-shapes (free typing)

Three of the eight fields are already OpenAI-schema-enforced at
the producer:
- `operating_model_json` — `consultant_finalize` at
  [intake_consultant.py:583](../../python/client_intake_and_finmo/intake_consultant.py#L583)
- `target_market_json` — `target_market_finalize` at
  [target_market_consultant.py:659](../../python/client_intake_and_finmo/target_market_consultant.py#L659)
- `people_json` — `people_capability_finalize` at
  [people_capability_consultant.py:368](../../python/client_intake_and_finmo/people_capability_consultant.py#L368)

The OpenAI schemas live as constants in each consultant module.
For these three: typing the sub-shape is a matter of TRANSLATING
the OpenAI schema to Pydantic. Lower-risk than the others.

Spec sub-flag (F-COMPOSITION (c)): consider typing the three
schema-enforced shapes in Commit 1a, deferring the other 4 to
follow-up commits.

---

## T6. Silent fallback / defensive patterns

### T6.1 `parse_json_dict` — silent empty on every read

All 8 boundary fields read via the same pattern:

```python
ops_json = parse_json_dict(draft.get("operating_model_json"))
```

`parse_json_dict` is documented in v1 inventory as silently
returning `{}` on missing or malformed JSON. Defensive by design.

**What the contract gate eliminates:** the silent-empty path.
With a `validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)`
call BEFORE the 8 parse_json_dict reads, missing-or-malformed
JSON surfaces as a structured `ContractViolation` rather than an
empty `{}` that crashes downstream when a required field is
read.

### T6.2 `build_shared_context` legacy-table import swallow

Per v1 inventory §F-3:
> `build_shared_context swallows legacy-table import errors at
>  shared_context.py:61, 77 with bare except Exception: pass,
>  masking import errors.`

NOT in Contract 5's gate scope (the import errors happen during
context-building, not at the draft-load boundary). Surfacing for
documentation; spec R-residual.

### T6.3 Edit-mode overwrites (v1 §B noted)

`operating_model_json`, `target_market_json`, `people_json` support
`edit_mode` at [intake_consultant.py:610-622](../../python/client_intake_and_finmo/intake_consultant.py#L610)
so their writer can overwrite the same field multiple times if
the user revisits the consultant. The persistence layer takes
whatever was passed; there's no revision count or checksum.

Not a contract-shape concern — the contract validates the SHAPE
of whatever the most recent write produced. Surfacing because if
a future operator wants per-write revision tracking, that's R-
residual.

---

## T7. Producer-side gate feasibility

### T7.1 INFEASIBLE — incremental writes across 20+ sites

Per §T1.1, `append_messages` is called from 20+ sites in
intake_consult.py. Each call may write a different subset of
columns. There is no "intake complete" event before the draft is
handed to post-intake — the post-intake pipeline simply reads
whatever the most recent column writes left in the SQL row.

A producer-side gate would need to land at EACH writer site,
similar to Contract 2's 5-writer R8 defer pattern. Worse than
Contract 2 because there are 20+ writer sites, and many of them
only write a subset of the 8 boundary columns (so each gate
would need partial-payload validation).

**Spec recommendation candidate:** SKIP producer-side gate per
PSL5 (Contract 2 R8 pattern). Consumer-side gate at runner.py:30
catches every regression at the boundary. Producer-side
tightening is per-consultant work (Contract 5b/c/etc.) — make
each consultant's finalize site validate its own sub-shape
against the corresponding typed sub-contract once those land.

### T7.2 Alternative — "finalize lock" gate

If intake had a single "finalize the draft" event before
post-intake reads, a producer-side gate could land there. Trace
finds: NO such event exists today. The user transitions from
intake to post-intake via the "start the planning run" button
which triggers `_run_planning_system_for_draft` directly without
a draft-finalize handshake.

Flag candidate (F-FINALIZE-GATE): does Contract 5 also add a
"draft finalize" event + producer-side gate at that event? **NOT
recommended for first cut** — adds a new architectural concept,
not just a contract. Defer to R-residual.

### T7.3 Composition with Contract 3 producer-side gate

Note that Contract 3's producer-side gate at runner.py:1809-1822
already validates the post-intake-side AFTER intake hands off.
That gate validates `applied_model_input_json` against Contract 1
plus the full 21-field solver-input bundle against Contract 3.
**Contract 5's consumer-side gate at runner.py:30 is structurally
upstream of Contract 3's producer-side gate** — both run during
the same `prepare_initial_grid_for_draft` invocation; Contract 5
validates the raw intake JSON columns FIRST, Contract 3
validates the post-intake-transformed bundle LATER. Two gates,
disjoint surfaces, structurally clean (same pattern as Contracts
1 + 3 co-existing at runner.py).

---

## T8. Divergences from v2 inventory

Taxonomy: **NEW SUBSTANTIVE** / **NEW STRUCTURAL** / **CONFIRMED
RESIDUAL** / **CONFIRMED CLOSED**.

### Div-1. fulfillment_json silent-drop specific mechanism — CONFIRMED CLOSED (corrected rationale)

Per §T4.4: the v1-cited runner.py:854 call site is gone from
initial_grid/runner.py — but the function
`_estimate_balance_sheet_contextual_seed_with_gpt` itself **still
exists** at post_intake_contracts/runner.py:1447 and is plumbed
as a Callable parameter to initial_grid/runner.py:53. The
Callable is **never invoked** inside initial_grid/runner.py
(Tier-F forwarded-but-unused pattern). The function's declared
parameters do not include `fulfillment_context` / `fulfillment_json`,
so even a hypothetical future call site would not consume
fulfillment_json without a signature change. Broader phantom
remains (CONFIRMED RESIDUAL) per §T4.3.

### Div-2. 8-field roster — CONFIRMED unchanged

v1/v2 confirmed verbatim. Line numbers at runner.py:190-197
match current source exactly (no drift). Field names + producer
sites confirmed.

### Div-3. `parse_json_dict` FALLBACK_PATH on all 8 reads — CONFIRMED RESIDUAL

v1 §D-3 noted this; v2 says "UNCHANGED". Trace confirms — all 8
reads use the silent-empty pattern. Contract gate eliminates it
at the boundary.

### Div-4. `realism_memo_json` READER_MISSING for planning path — PARTIAL CONTRADICTION

v1 §D-2 cites: "realism_memo_json is READER_MISSING for the
planning path. Written at intake_consult.py:8230 on intake
completion. No grep hit for any post-intake reader."

Trace finds: realism_memo_json IS read at
[runner.py:1541](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1541):
`"realism_memo_json": parse_json_dict(draft.get("realism_memo_json"))`
— bundled into `generate_live_quarter_grid_plan` kwargs. So
there IS a post-intake read site. Whether the callee
structure-reads the value is unverified by this trace; but the
v1 claim of "zero post-intake readers" is wrong.

Note also: realism_memo_json is NOT in the 8-field boundary
roster (v1 §A only lists 8 fields, realism_memo_json is the 9th
JSON column that v1 considers diagnostic-only). The trace
recommendation: **exclude realism_memo_json from the IntakeDraftContract**
because it's diagnostic, not driving the planning. Spec sub-flag
candidate.

**Classification: NEW STRUCTURAL.** v1's claim of zero readers
is contradicted; the one read site is bundled-but-likely-
phantom-read. Spec doc decides scope.

### Div-5. Producer-side gate impossibility — NEW STRUCTURAL

v1/v2 inventories don't address gate feasibility. §T7 establishes
it directly: 20+ incremental writer sites → no single producer-
side gate.

### Div-6. Adjustment B carry-over — CONFIRMED

Same `_run_planning_system_for_draft` → API handler at
intake_consult.py:7276 catch chain that protects Contracts 3 + 4
also protects Contract 5's consumer-side gate at runner.py:30
(via the same `_run_planning_system_for_draft_unified` →
`prepare_initial_grid_for_draft` call path). ContractViolation
propagates through the line-7377 generic `except Exception` as a
structured 500 with `detail=str(exc)` carrying the stage tag.

Same end-to-end pattern as Contracts 3 + 4. Spec doc test class
mirrors Contract 4's `ApiCatchPatternEndToEndTest` verbatim.

**Classification: CONFIRMED carry-over.**

### Div-7. business-fact scalar fields on the draft row — NEW STRUCTURAL

v1 §A briefly mentions "plus business-fact scalar fields on the
draft row" but doesn't enumerate them. Trace finds these scalars
load into the `business_facts` dict via `build_shared_context` and
`_targeted_process_runtime_context_from_rows` at
[intake_consult.py:7160-7240](../../python/api_handlers/intake_consult.py#L7160).
At least these scalar keys appear: `draft_id`, `client_id`,
`business_name`, `business_address`, `business_start_date`,
`address_street`, `address_city`, `address_state`, `address_zip`,
`address_country`.

**Flag candidate (F-BUSINESS-FACTS):** include the scalar fields
in Contract 5 (as a `business_facts` sub-shape), or exclude them
(scope only the 8 JSON columns)?

Recommend **exclude** for Commit 1a — Contract 3's
`BusinessFactsForSolverContract` already types `fact_template`
opaquely; doing it here would require either redefining or
inverse-composing, both of which are scope creep for the first
cut. R-residual for retrofit.

---

## Open questions / flags for the spec doc

Carrying forward for the spec's §7. Same numbered-flag format as
Contracts 1-4. Each flag: spec recommends + alternatives +
reasoning.

### F0 — Composition scope (PSL1 / §T5.2)

Recommend (b) opaque first cut for all 7 intake-domain shapes.
Sub-contracts retrofit as Contract 5b/c/etc. follow-ups. Avoids
ballooning Commit 1a beyond the 700-LOC cap.

Sub-flag (c): consider typing the 3 OpenAI-schema-enforced shapes
(ops_json, target_market_json, people_json) in Commit 1a since
their schemas already exist and just need pydantic translation.

### F1 — fulfillment_json disposition (PSL2 / §T4.5)

Three options. Recommend (a) Optional[Dict[str, Any]] = None to
match production reality. (b) required keep-all-required for the
"don't loosen" stance. (c) drop = scope creep, defer to R-
residual.

### F2 — realism_memo_json inclusion scope (§Div-4)

Recommend **exclude** from Contract 5 — diagnostic, not driving
planning. Spec doc confirms.

### F3 — business-fact scalar fields inclusion scope (§Div-7)

Recommend **exclude** from Commit 1a — Contract 3's
BusinessFactsForSolverContract handles it via opaque fact_template.
R-residual retrofit.

### F4 — Producer-side gate (PSL5 / §T7)

Recommend **SKIP** per Contract 2 R8 pattern. 20+ incremental
writer sites; no single producer-side gate is feasible.
Per-consultant producer-side gates land as Contract 5b/c/etc.
follow-ups.

### F5 — Consumer-side gate placement (PSL6 / §T2)

Recommend FIRST executable line of `prepare_initial_grid_for_draft`
at [runner.py:30](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30)
— BEFORE the 8 `parse_json_dict(draft.get(...))` calls at lines
190-197. Spec doc confirms exact placement.

### F6 — extra policy (PSL4)

Recommend `extra="forbid"` on top-level IntakeDraftContract;
`extra="ignore"` on every sub-contract envelope (when sub-
contracts ship). Established pattern.

### F7 — Adjustment B (PSL7)

Recommend re-use Contract 4's `ApiCatchPatternEndToEndTest`
verbatim — same intake_consult.py:7377 generic Exception catch
propagates ContractViolation from Contract 5's gate at
runner.py:30 through the same `_run_planning_system_for_draft`
→ `_run_planning_system_for_draft_unified` →
`prepare_initial_grid_for_draft` call chain.

### F8 — Diagnostic-emission invariant test (PSL8)

Recommend add `ContractFiveEmitsIntakeDraftPhaseCodeTest` to
`tests/test_p3_40_diagnostic_emission_invariant.py` + extend
`PhaseCodesDoNotCrossContaminateTest` with cross-contamination
check. Pattern established by Contract 2 restoration commit
(e073b6a), continued through Contracts 3 + 4. Lockstep
PhaseCode count 17 → 18; rename
`test_phase_code_has_seventeen_phases` → `_eighteen_phases`.

---

## Lessons baked in for Contract 5 spec drafting

- **Trace before spec.** The trace caught Div-1 (v1's fulfillment_json
  silent-drop mechanism is closed via the Callable-never-invoked
  path, NOT via function deletion as initially claimed —
  amendment corrected the supporting facts) and Div-4 (v1's claim
  of zero realism_memo_json readers is wrong — bundled at
  runner.py:1541). Both would have been costly assumption errors
  in the spec.
- **Match production vocabulary verbatim.** All 8 field names +
  producer sites + line numbers lifted from source.
- **Constraints from production reality.** Persistence pattern
  (`append_messages` with `Optional` columns + 20+ writer sites)
  determines producer-side gate feasibility (= infeasible). The
  contract must work with the persistence pattern as-is.
- **Don't loosen safety checks.** F1(b) considered for
  fulfillment_json per the "don't loosen" stance — but (a)
  matches production reality more honestly. Spec doc final call.
- **Compose where downstream contracts already exist — but
  Contract 5 has NO upstream contracts.** Inverse retrofits
  (Contract 3+'s Flag-4-deferred shapes) are R-residuals, not
  Contract 5's responsibility.
- **`extra="forbid"` only on top-level.** F6.
- **Adjustment B is recurring.** Div-6 confirms the same API-
  handler catch path. Test mirrors Contracts 3 + 4 verbatim.
- **Diagnostic-emission invariant matters.** F8 extends the
  established pattern from Contract 2 restoration through
  Contracts 3 + 4 to Contract 5.
