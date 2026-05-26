# P3.40 Contract 5 — IntakeDraftContract (Spec)

**Status:** Specification only. No code lands until Nick reviews this doc.
After review, implementation follows the commit sequence in §6 below.

**Boundary covered:** INTAKE → POST_INTAKE (Boundary 1 in
[p3_40_pipeline_data_flow_inventory_v2.md](p3_40_pipeline_data_flow_inventory_v2.md)).
The artifact is the `intake_consult_drafts` SQL row's 8 JSON
columns, assembled incrementally by intake_consult.py across many
chat turns and read by post-intake at
[runner.py:190-197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L190)
when the planning run starts.

**Predecessors:** none — Contract 5 is the **most upstream**
contract in the P3.40 series. Contracts 1-4 sit downstream of
this boundary.

**Companion trace doc:** [p3_40_contract_5_intake_draft_trace.md](p3_40_contract_5_intake_draft_trace.md)
(landed at e7c739d; T4 amendment at 1a190c7). All file:line
citations and divergence findings below trace back to that doc.

**Lessons applied from Contracts 1-4:**
- Trace before spec. The trace + T4 amendment caught a wrong v1
  fact about `estimate_balance_sheet_contextual_seed_with_gpt`
  being deleted (it's not — it's plumbed-but-never-invoked
  Tier-F per Contract 3's established pattern). Saved a wrong
  rationale in the spec.
- Match production vocabulary verbatim. All 8 field names +
  producer file:line + line numbers at runner.py:190-197 verified
  verbatim.
- Constraints from production reality. Persistence pattern
  (`append_messages` with `Optional` columns + 20+ writer sites)
  determines producer-side gate feasibility (= infeasible).
- Don't loosen safety checks. F1(a) for fulfillment_json reflects
  production (sometimes-NULL); the 7 other fields stay required.
- `extra="forbid"` only on top-level; `extra="ignore"` on
  sub-contracts.
- Compose where downstream contracts already exist — none exist
  upstream of Contract 5, so this contract has ZERO composition.
- Adjustment B is recurring. Trace Div-6 confirms the same
  intake_consult.py:7377 generic catch propagates ContractViolation
  cleanly at this boundary too.
- Diagnostic-emission invariant matters. Contract 5's PhaseCode
  addition gets its own observability invariant test alongside
  the lockstep update.

---

## 1. Trace Task Findings

The 8 pre-implementation traces (T1-T8) plus the T4 amendment
produced findings folded directly into this spec's structure.
The full enumeration is in the trace doc; this section
consolidates the ones that change contract design.

### 1.1 8-field roster — UNCHANGED from v1/v2

Verbatim from
[runner.py:190-197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L190):

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

8 SQL columns, 8 `parse_json_dict` reads. Local-variable naming
asymmetry (`ops_json` reads `operating_model_json`, `market_json`
reads `target_market_json`) preserved from production; the
contract types by SQL column name.

### 1.2 Persistence is INCREMENTAL — producer-side single-gate INFEASIBLE

Per trace §T1.1: `append_messages` at
[intake_consult_draft.py:1781-1955](../../python/client_intake_and_finmo/intake_consult_draft.py#L1781)
is called from 20+ sites in `intake_consult.py`; each call may
write a subset of columns. There is no "intake complete" event.
**Producer-side single-gate is infeasible** (Contract 2 R8
pattern, not Contract 3 single-producer pattern). Flag 4
disposition confirms SKIP producer-side gate.

### 1.3 fulfillment_json: CONFIRMED CLOSED (Tier-F Callable) + CONFIRMED RESIDUAL (broader phantom)

Per trace T4 + amendment 1a190c7:
- Function `_estimate_balance_sheet_contextual_seed_with_gpt`
  EXISTS at post_intake_contracts/runner.py:1447; plumbed as
  Callable to initial_grid/runner.py:53 but **never invoked**
  inside initial_grid/runner.py (verified: 0 invocation sites).
- The Callable's declared parameters don't include
  `fulfillment_context` / `fulfillment_json`, so even a
  hypothetical future call would not consume fulfillment_json
  without a signature change.
- This is the Contract 3 Tier-F forwarded-but-unused pattern.
- Broader phantom holds: fulfillment_json parsed at runner.py:195
  + threaded into 5 downstream dicts (lines 248, 901, 1539, 1848,
  1884) + never structure-read (Contract 3 typed it as
  `Dict[str, Any]` opaque Tier-B closure-only with the closure
  docstring at orchestrator.py:625-630 explicitly marking it
  "intentionally unused").

Flag 1 disposition (a) Optional[Dict[str, Any]] = None matches
production: fulfillment_json may or may not be set (patch-system
writes only; no required consultant produces it); when set, no
schema enforcement at any layer; downstream never structure-reads.

### 1.4 All 8 reads are FALLBACK_PATH

Per trace §T6.1: every read uses `parse_json_dict(draft.get(...))`
which silently returns `{}` on missing or malformed JSON. The
consumer-side contract gate at runner.py:30 closes this hole —
malformed-or-missing surfaces as `ContractViolation` rather than
an empty `{}` that crashes downstream when a required field is
read.

### 1.5 Composition: ZERO with prior contracts

Per trace §T5.1: Contract 5 is upstream of Contracts 1-4. No
prior-contract shapes flow INTO this boundary. The 7 inverse
retrofits (where Contract 3+'s deferred-from-Flag-4 shapes would
retrofit to compose Contract 5's sub-contracts) are **R-residual,
NOT Contract 5's scope.** Flag 0 disposition (b) opaque-first-cut
keeps Commit 1a tight.

### 1.6 Seven divergences from v2 inventory (trace T8)

Carried for reference; folded into flag dispositions below:

| Div | Class | Spec impact |
|---|---|---|
| Div-1: fulfillment_json silent-drop mechanism | CONFIRMED CLOSED (corrected rationale) | F1 disposition basis |
| Div-2: 8-field roster | CONFIRMED unchanged | §2 + §3 |
| Div-3: parse_json_dict FALLBACK_PATH | CONFIRMED RESIDUAL | §5 gate closes |
| Div-4: realism_memo_json has a reader at runner.py:1541 | NEW STRUCTURAL (partial v1 contradiction) | F2 EXCLUDE (diagnostic) |
| Div-5: Producer-side gate impossibility | NEW STRUCTURAL | F4 SKIP |
| Div-6: Adjustment B carry-over | CONFIRMED | §5 + §6 Commit 3 test |
| Div-7: business-fact scalar fields not enumerated | NEW STRUCTURAL | F3 EXCLUDE (R-residual retrofit) |

---

## 2. Top-level production payload — 8-field roster

Tier legend (carried from Contracts 3-4):
- **A. Consumed-direct.** Read structurally by post-intake (orchestrator + downstream). Type as required.
- **F. Forwarded-but-unused at this boundary.** Phantom-required per "don't loosen safety checks" stance.

| # | SQL column | Producer site (intake) | Required-or-optional | Tier | Contract type |
|---|---|---|---|---|---|
| 1 | `operating_model_json` | `consultant_finalize` ([intake_consultant.py:583](../../python/client_intake_and_finmo/intake_consultant.py#L583)) | required (consultant gate enforces) | A | `Dict[str, Any]` opaque (F0 first cut) |
| 2 | `target_market_json` | `target_market_finalize` ([target_market_consultant.py:659](../../python/client_intake_and_finmo/target_market_consultant.py#L659)) | required | A | `Dict[str, Any]` opaque (F0 first cut) |
| 3 | `people_json` | `people_capability_finalize` ([people_capability_consultant.py:368](../../python/client_intake_and_finmo/people_capability_consultant.py#L368)) | required | A | `Dict[str, Any]` opaque (F0 first cut) |
| 4 | `financials_json` | `financials_chat_turn` accumulator ([financials_consultant.py:1873](../../python/client_intake_and_finmo/financials_consultant.py#L1873)) | required | A | `Dict[str, Any]` opaque (F0 first cut) |
| 5 | `financials_year1_json` | `assemble_financials_year1` ([financials_year1.py:684](../../python/client_intake_and_finmo/financials_year1.py#L684)) | required | A | `Dict[str, Any]` opaque (F0 first cut) |
| 6 | `fulfillment_json` | `_apply_scoped_patch` ([intake_consult.py:6720+](../../python/api_handlers/intake_consult.py#L6720)) | OPTIONAL (patch-system only; no consultant) | **F** | `Optional[Dict[str, Any]] = None` (F1 (a)) |
| 7 | `marketing_model_json` | `_compute_marketing_model_json` (intake_consult.py) | required | A | `Dict[str, Any]` opaque (F0 first cut) |
| 8 | `planning_context_summary_json` | `_build_planning_context_summary_payload` (intake_consult.py) | required | A | `Dict[str, Any]` opaque (F0 first cut) |

**Total typed fields: 8.** Per F0 first cut, all 8 are opaque
`Dict[str, Any]` (or `Optional[Dict[str, Any]]` for
fulfillment_json). Sub-contracts (per F0 sub-flag (c)) retrofit
as Contract 5b/c/etc. follow-ups for the 3 OpenAI-schema-
enforced shapes (operating_model_json, target_market_json,
people_json) if Nick approves the typed-from-OpenAI-schema
translation.

### 2.1 Excluded fields (F2 + F3 dispositions)

The following are NOT part of `IntakeDraftContract`'s 8-field
roster:

- **`realism_memo_json`** — diagnostic, not driving planning.
  Read at [runner.py:1541](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1541)
  inside `generate_live_quarter_grid_plan` kwargs but downstream
  consumption unverified. F2 EXCLUDES; R-residual if a future
  contract types diagnostic blobs.
- **business-fact scalar fields** (`business_name`,
  `business_naics_6`, `business_address`, `business_start_date`,
  `address_street`, etc.) — loaded into the `business_facts` dict
  by `build_shared_context` and
  `_targeted_process_runtime_context_from_rows`. F3 EXCLUDES;
  Contract 3's `BusinessFactsForSolverContract.fact_template`
  already types this opaquely. R-residual retrofit when Contract
  3 tightens.

---

## 3. Field-by-field contract spec

### 3.1 Top-level `IntakeDraftContract`

```python
class IntakeDraftContract(BaseModel):
  """The 8-field intake-draft payload at the INTAKE -> POST_INTAKE
  boundary (Boundary 1).

  Consumed by post-intake at runner.py:190-197 where each field is
  passed through ``parse_json_dict(draft.get(<column>))``. The
  contract gate validates the 8-field bundle BEFORE those
  parse_json_dict reads -- closing the FALLBACK_PATH silent-empty
  pattern that today lets malformed-or-missing JSON surface as
  empty {} (Trace Div-3).

  Per spec Flag 0 (b): all 8 fields type as opaque
  Dict[str, Any] for first cut. Sub-contracts (per F0 sub-flag
  (c)) retrofit as Contract 5b/c/etc. follow-ups for the 3
  OpenAI-schema-enforced producer sites.

  Per spec Flag 1 (a): fulfillment_json is the only Optional
  field -- the patch-system producer at intake_consult.py:6720
  may legitimately leave the SQL column NULL. The other 7 fields
  are consultant-produced or python-aggregated; production
  expectation is they're always written before post-intake reads
  the row.
  """

  # Tier A -- consultant-produced or python-aggregated (required)
  operating_model_json: Dict[str, Any]
  target_market_json: Dict[str, Any]
  people_json: Dict[str, Any]
  financials_json: Dict[str, Any]
  financials_year1_json: Dict[str, Any]
  marketing_model_json: Dict[str, Any]
  planning_context_summary_json: Dict[str, Any]

  # Tier F -- patch-system-only producer; legitimately NULL when
  # no fulfillment.* patch ever ran (F1 (a))
  fulfillment_json: Optional[Dict[str, Any]] = None

  model_config = ConfigDict(extra="forbid")  # F6 PSL4
```

### 3.2 Zero re-imports from prior contracts (PSL1)

Contract 5 is upstream of all P3.40 contracts. No re-imports of
`FinmoModelInputContract` / `FinmoOutputContract` /
`PayrollHeadcountContract` / `DebtScheduleContract` /
`CapitalLeaseScheduleContract` / `BusinessFactsForSolverContract`
/ `StageRampContract`. Only `ContractViolation` is re-exported
(via `from finmo_model_input_contract import ContractViolation`)
so gate callers import from one place.

### 3.3 Zero new sub-contracts (F0 first cut)

Per spec F0 (b): all 8 fields type as opaque `Dict[str, Any]` for
first cut. Sub-contract introduction defers to:
- **R8** (per F0 sub-flag (c)): the 3 OpenAI-schema-enforced
  shapes (operating_model_json, target_market_json, people_json)
  can be typed by translating the existing OpenAI schemas to
  Pydantic. Each becomes a separate follow-up commit (Contract
  5b, 5c, 5d) so the boundary gate lands first and the typed
  tightenings ship incrementally.
- **R9-R12**: financials_json, financials_year1_json,
  marketing_model_json, planning_context_summary_json sub-
  contracts. Each is a separate intake-domain typing project; not
  blocking the boundary gate.

---

## 4. Cross-field invariants

Per Contracts 1-4 pattern. Contract 5's 8 fields are mostly
opaque dicts; cross-field invariant candidates are limited.

### 4.1 No invariants for first cut

Spec recommends **no `@model_validator` cross-field invariants in
Commit 1a**. Reasoning:

- All 8 fields are opaque `Dict[str, Any]` per F0 first cut. The
  only available checks are presence/absence — which the field
  declarations themselves enforce (7 required + 1 Optional).
- Once F0 sub-flag (c) lands sub-contracts for the 3 OpenAI-
  schema-enforced shapes, cross-field invariants become useful
  candidates:
  - `operating_model_json.business_naics_6 == people_json.business_naics_6`
    (v1 inventory §E noted NAICS source field name varies).
  - `marketing_model_json.version == "3"` (v1 §E noted the version
    field is unchecked by readers).
  - `financials_year1_json` dual-access-pattern consistency
    (v1 §E nested vs flat access).
- Each becomes a sub-flag in the corresponding Contract 5b/c/etc.
  follow-up spec.

Spec doc Commit 1a: NO `@model_validator` decorators. Test class
`CrossFieldInvariantTest` ships in Commit 1c with placeholder
note (`@unittest.skip("Cross-field invariants deferred to
Contract 5b/c follow-ups per spec section 4.1")`) — or omit the
class entirely. Spec recommends omit; test classes that exist
only to be skipped are noise.

---

## 5. Boundary enforcement

### 5.1 Producer-side gate — SKIP per F4 / PSL5

Per trace §T7.1 / §1.2: 20+ incremental writer sites in
intake_consult.py; no single producer-side gate is feasible. Each
consultant's finalize site or patch-system call writes a subset
of columns; per-call gates would need partial-payload validation.

**Spec recommendation:** SKIP producer-side gate. Per-consultant
producer-side gates land as Contract 5b/c/etc. follow-up commits
(each consultant validates its own sub-shape once the
corresponding sub-contract ships).

This matches Contract 2's R8 defer pattern (5 writers across
different modules → no single gate). It's a step weaker than
Contract 3's single-producer pattern (which shipped a producer-
side gate at the single bundle return).

### 5.2 Consumer-side gate per F5 / PSL6

**Location:** FIRST executable line of `prepare_initial_grid_for_draft`
at [runner.py:30](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30)
— **BEFORE** the 8 `parse_json_dict(draft.get(...))` calls at
lines 190-197.

```python
# python/client_intake_and_finmo/post_intake_initial_grid/runner.py:30+

def prepare_initial_grid_for_draft(
  *,
  conn,
  draft_id: str,
  ...
) -> Dict[str, Any]:
  # P3.40 Contract 5 Commit 3 -- consumer-side boundary gate.
  # FIRST executable line. Validates the 8-field intake-draft
  # JSON shape BEFORE the parse_json_dict reads at lines 190-197
  # (which today silently coerce missing/malformed JSON to {}).
  # Surfaces structural problems as ContractViolation rather than
  # empty plans downstream.
  #
  # Lazy import + lazy draft load: the draft row is loaded
  # several lines below via lifecycle_start; for the gate, we
  # need a draft-row peek. Place the gate immediately AFTER the
  # draft row becomes available.
  ...
```

**Placement nuance:** the FIRST executable line of
`prepare_initial_grid_for_draft` predates the draft row load
(which happens via `build_shared_context` / `get_draft` further
down). The gate cannot validate without the row. **Correct
placement: immediately after the draft row is loaded but BEFORE
the parse_json_dict reads at lines 190-197.**

Spec doc Commit 3 will identify the exact line during wiring;
expected placement is in the range runner.py:80-190 (after
`active_planning_run_id` derivation at line ~85 and after the
draft row becomes available).

### 5.3 Enforcement helper

Added to existing `enforcement.py` alongside Contracts 1-4
helpers:

```python
INTAKE_DRAFT_STAGE_LABEL = "INTAKE->POST_INTAKE"

def validate_intake_draft_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = INTAKE_DRAFT_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> IntakeDraftContract:
  ...
```

Mirrors Contracts 1-4 helpers verbatim. Reuses
`_extract_first_error` + `_safe_emit` private helpers.

**Payload construction at the gate:** the consumer-side gate
builds the 8-field dict from the draft row's JSON columns BEFORE
the parse_json_dict reads:

```python
# At the gate site (runner.py somewhere between draft row load
# and line 190):
_intake_payload_for_gate = {
  "operating_model_json": parse_json_dict(draft.get("operating_model_json")),
  "target_market_json": parse_json_dict(draft.get("target_market_json")),
  "people_json": parse_json_dict(draft.get("people_json")),
  "financials_json": parse_json_dict(draft.get("financials_json")),
  "financials_year1_json": parse_json_dict(draft.get("financials_year1_json")),
  "marketing_model_json": parse_json_dict(draft.get("marketing_model_json")),
  "planning_context_summary_json": parse_json_dict(draft.get("planning_context_summary_json")),
}
# fulfillment_json: include only if the raw SQL column is non-null
_raw_fulfillment = draft.get("fulfillment_json")
if _raw_fulfillment is not None:
  _intake_payload_for_gate["fulfillment_json"] = parse_json_dict(_raw_fulfillment)
validate_intake_draft_at_boundary(
  _intake_payload_for_gate,
  side=SIDE_CONSUMER,
  emit_diagnostic_fn=_boundary_emitter,
)
```

**Subtlety on parse_json_dict-then-validate ordering:** the gate
uses `parse_json_dict` to convert SQL JSON columns to dicts
BEFORE handing to the contract. This means the gate validates
the parsed shape, NOT the raw JSON string. If a column is
malformed JSON, `parse_json_dict` returns `{}` and the contract
sees `{}` → which (per the typed declaration `Dict[str, Any]`)
is a valid empty dict and passes.

**Spec choice:** is `{}` for a required field a contract
violation?
- (a) **No** — `{}` is a valid `Dict[str, Any]`; the contract
  passes empty dicts. Matches Pydantic's default declarative
  behavior. Downstream code's actual reads will fail when they
  try to extract specific keys, but that's the consumer's
  problem to validate per use.
- (b) **Yes** — add a `min_length=1` constraint on each required
  field, treating `{}` as "missing data". Tightens the contract
  but rejects payloads that production may legitimately produce
  (e.g., a draft where intake didn't get past consultant step 1
  shouldn't be allowed to start a planning run — but is this the
  contract's job or `validate_draft_data`'s job?).

Spec recommends **(a) no min_length** for first cut, matching
Pydantic default + the "boundary contract validates shape, not
content depth" principle. Sub-flag candidate (F4(b)?) for Nick.

### 5.4 Adjustment B verification (Div-6 confirmed)

Per trace Div-6 the API handler at
[intake_consult.py:7377](../../python/api_handlers/intake_consult.py#L7377)
catches `except Exception as exc:` and logs `str(exc)`.
ContractViolation is `Exception` subclass (not `RuntimeError`)
→ skips line-7298 RuntimeError branch → lands in line-7377
generic catch → returns HTTP 500 with `detail=str(exc)` carrying
`INTAKE_DRAFT_STAGE_LABEL` + field path.

The catch chain wraps `_run_planning_system_for_draft` →
`_run_planning_system_for_draft_unified` →
`prepare_initial_grid_for_draft` — so a ContractViolation
raised by Contract 5's gate at runner.py:30+ propagates through
the same chain Contracts 3 + 4 validated.

§6 Commit 3 includes a test mirroring Contracts 3 + 4's
`ApiCatchPatternEndToEndTest` end-to-end pattern.

### 5.5 PhaseCode / EventCode / FailFastCode additions

New entries (lockstep with the lock-count tests per the Contract
4 pattern):

- `PhaseCode.INTAKE_DRAFT_CONTRACT`
- `EventCode.INTAKE_DRAFT_CONTRACT_VALIDATED`
- `EventCode.INTAKE_DRAFT_CONTRACT_VIOLATION`
- `FailFastCode.FAIL_INTAKE_DRAFT_CONTRACT_VIOLATION = "fail_intake_draft_contract_violation"`

Lock-count tests to update:
- `test_phase_9_p3_33_phase3_step9a_phase_codes.py`: rename
  `test_phase_code_has_seventeen_phases` → `_eighteen_phases`;
  count 17 → 18; comment lists all 5 contract phases.
- `_safe_emit` partition + `raise_fail_fast` failed_event
  mapping updated to include the new phase.

### 5.6 Diagnostic-emission invariant test (F8 / PSL8)

Per directive + Contract 2 restoration pattern + Contracts 3, 4
extensions:

- `ContractFiveEmitsIntakeDraftPhaseCodeTest` (1 new test in
  `tests/test_p3_40_diagnostic_emission_invariant.py`): feed
  deliberate Contract 5 violation through
  `validate_intake_draft_at_boundary` with capturing emitter;
  assert captured event carries `PhaseCode.INTAKE_DRAFT_CONTRACT`.
- `PhaseCodesDoNotCrossContaminateTest` extension: 1 new test
  confirming Contract 5 violations route to
  `INTAKE_DRAFT_CONTRACT` exclusively, NOT under
  `MODEL_INPUT_CONTRACT` / `WORKBOOK_PAYLOAD_CONTRACT` /
  `SOLVER_INPUT_CONTRACT` / `SOLVER_OUTPUT_CONTRACT`.

Total invariant-file additions: 2 new tests; file count 7 → 9.

---

## 6. Implementation sequence

After Nick green-lights this spec, implementation follows.

### Commit 1a — Contract module

File: `python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py`

- 1 top-level: `IntakeDraftContract` with 8 fields (7 required
  `Dict[str, Any]` + 1 Optional `Dict[str, Any]` per F1 (a)).
- ZERO new sub-contracts (per F0 first cut).
- ZERO `@model_validator` cross-field invariants (per §4.1).
- ZERO re-imports from prior contracts (PSL1) — only
  `ContractViolation` re-export.
- `extra="forbid"` top-level (F6 / PSL4).
- Module docstring covering boundary + the 7 R-residual sub-
  contract tightenings + F1 fulfillment_json rationale + Tier
  classification.

Expected LOC: 150-250 (smallest contract module yet — mostly
docstrings + 8 field declarations). Well under 700 cap.

### Commit 1b — Fixtures + sub-contract tests

`tests/_p3_40_contract_5_fixtures.py` + `tests/test_p3_40_contract_5_subcontracts.py`

- `valid_intake_draft_dict(include_fulfillment_json=True)` —
  minimal-valid 8-field payload + toggle for the Optional
  fulfillment_json field.
- Imports nothing from prior contracts (PSL1).

Tests:
- `IntakeDraftContractTopLevelTest` (7-8 tests): valid full
  payload; extra='forbid' on top-level; 7 required-field
  removals each rejected (each of the 7 Tier-A fields).
- `FulfillmentJsonOptionalTest` (2 tests): fulfillment_json
  accepted absent (default None per F1 (a)); accepted with
  payload.

Expected total: 9-10 tests. Smaller than Contracts 1-4 because
Contract 5 has no sub-contracts.

### Commit 1c — Top-level + Adjustment B tests

`tests/test_p3_40_contract_5_intake_draft.py`

3 test classes (no CompositionWith* since Contract 5 doesn't
compose; no CrossFieldInvariant since none in Commit 1a):

- `IntakeDraftContractAcceptanceTest` (~6 tests): valid full
  payload accepted; all 7 required Tier-A field rejections
  exhaustively covered (one per field).
- `FulfillmentJsonDispositionTest` (3 tests): pins F1 (a) —
  accepted absent (= None), accepted with empty dict, accepted
  with arbitrary keys (no schema enforcement per Trace T4.1).
- `ApiBoundaryContractViolationTest` (4 tests): Adjustment B per
  Contracts 3 + 4 pattern. ContractViolation message uses
  `INTAKE_DRAFT_STAGE_LABEL`; structured attributes accessible;
  survives intake_consult.py:7377 generic Exception catch;
  source_payload not dumped into str.

Expected total: 13 tests.

### Commit 2 — SKIP per F2 / Contract 4 precedent

No adapter. Same disposition as Contract 4 Flag 2 (a) — the
boundary surface is already a dict-of-dicts at the SQL layer;
`model_validate` + the enforcement helper bridge directly. No
intermediate dataclass to bridge to/from.

Implementation sequence becomes **1a → 1b → 1c → 3** (4
commits).

### Commit 3 — Gate + enforcement helper + diagnostic codes + invariant test + Adjustment B test

THREE wirings + tests in one commit (mirroring Contracts 3 + 4
Commit 3):

1. **Enforcement helper** added to `enforcement.py`:
   `validate_intake_draft_at_boundary`,
   `INTAKE_DRAFT_STAGE_LABEL` new, `SIDE_PRODUCER` /
   `SIDE_CONSUMER` reused, `__all__` updated.

2. **Consumer-side gate** at `runner.py` somewhere in the
   30-190 line range, immediately after the draft row is
   available and BEFORE the 8 `parse_json_dict(draft.get(...))`
   reads at lines 190-197. Lazy import so the contracts package
   isn't a hard dependency at runner.py import time. Payload
   constructed per §5.3.

3. **PhaseCode / EventCode / FailFastCode** additions per §5.5.
   Lockstep update of
   `test_phase_9_p3_33_phase3_step9a_phase_codes.py` (count 17 →
   18; rename `_seventeen_phases` → `_eighteen_phases`).

4. **Diagnostic-emission invariant test** additions per §5.6
   (2 new tests in
   `tests/test_p3_40_diagnostic_emission_invariant.py`).

Consumer-gate tests in
`tests/test_p3_40_contract_5_consumer_gate.py`:

- `ValidPayloadAcceptedTest` (1): valid 8-field bundle returns
  parsed `IntakeDraftContract`.
- `GateRejectsMissingRequiredFieldTest` (4 representative of 7
  required fields): missing operating_model_json,
  financials_json, marketing_model_json,
  planning_context_summary_json each rejected with
  `INTAKE_DRAFT_STAGE_LABEL` + field path.
- `FulfillmentJsonAcceptedAbsentAtGateTest` (1): F1 (a) pinned
  through the gate path.
- `ApiCatchPatternEndToEndTest` (3): Adjustment B per Contracts
  3 + 4. ContractViolation is Exception subclass; NOT
  RuntimeError; str(exc) carries stage + field; non-empty.
- `DiagnosticEmitBestEffortTest` (2): valid AND violation paths
  both succeed when emit_diagnostic_fn raises.

Expected total: 11 tests in consumer_gate file + 2 in invariant
file = 13 new tests.

---

## 7. Open flags for Nick's review

9 numbered flags with spec recommendations matching the PSL
pre-stated leans. F0 has a sub-flag (c) for Nick's call.

### Flag 0 — Composition scope (PSL1 / Trace §T5)

**(Recommended) (b) Opaque first cut for all 8 fields.** Type as
`Dict[str, Any]` (or `Optional[Dict[str, Any]]` for
fulfillment_json). Sub-contracts retrofit as Contract 5b/c/etc.
follow-ups. Keeps Commit 1a tight; avoids ballooning past the
700-LOC cap.

**(a) Define typed sub-contracts in Commit 1a.** Each of the 7
required intake-domain shapes gets a typed sub-contract. **Scope
risk**: each sub-contract could be 200-500 LOC; Commit 1a would
likely exceed cap. Recommend against.

**Sub-flag (c) — type the 3 OpenAI-schema-enforced shapes in
Commit 1a.** The 3 shapes (operating_model_json,
target_market_json, people_json) already have OpenAI schemas at
their producer sites; translating to Pydantic is a known
operation. Could ship in Commit 1a without massive scope
expansion. Spec defaults to **(c) NO** — keep Commit 1a tight;
defer all 3 to Contract 5b/c/d follow-ups. Nick can override to
(c) YES if the typed-from-OpenAI-schema translation is
straightforward enough to bundle.

### Flag 1 — fulfillment_json disposition (PSL2 / Trace §T4)

**(Recommended) (a) Optional[Dict[str, Any]] = None.** Matches
production reality: patch-system writes only; no required
consultant produces it; SQL column legitimately NULL when no
patch ran. Downstream never structure-reads anyway per Trace
T4.3.

**(b) Required Dict[str, Any].** Matches "don't loosen safety
checks" stance + Contract 3 Flag 2 Tier-F kept-required
pattern. But would require verifying production never has SQL
NULL — likely false. Recommend against.

**(c) Drop from contract entirely.** Scope creep; requires
separate cleanup commit to remove SQL column + 5 runner.py
threading sites + Contract 3 solver-input field. R-residual.

### Flag 2 — realism_memo_json scope (Trace §Div-4)

**(Recommended) EXCLUDE from Contract 5.** Diagnostic, not
driving planning. The read at runner.py:1541 inside
`generate_live_quarter_grid_plan` kwargs is bundled-but-likely-
phantom-read; even if structure-read, the field is diagnostic
overlay. R-residual if a future contract types diagnostic
blobs.

**(b) Include.** Adds a 9th field for completeness. Recommend
against — diagnostic fields don't belong in a structural
contract.

### Flag 3 — business-fact scalar fields scope (Trace §Div-7)

**(Recommended) EXCLUDE from Commit 1a.** Contract 3's
`BusinessFactsForSolverContract.fact_template` already types
this opaquely. R-residual retrofit when Contract 3 tightens.
Including in Contract 5 would require redefining or inverse-
composing Contract 3 — scope creep.

**(b) Include.** Type the scalar fields as a `business_facts`
sub-shape on the draft row. Recommend against for the scope-
creep reason.

### Flag 4 — Producer-side gate (PSL5 / Trace §T7)

**(Recommended) SKIP per Contract 2 R8 pattern.** 20+
incremental writer sites; no single producer-side gate is
feasible. Per-consultant producer-side gates land as
Contract 5b/c/etc. follow-ups (each consultant validates its
own sub-shape once the corresponding sub-contract ships).

**(b) Add per-writer gates at each of the 20+ `append_messages`
sites.** Defense-in-depth but high churn cost; partial-payload
validation at each site is structurally awkward. Recommend
against.

**Sub-flag (c) — "finalize lock" gate (Trace §T7.2).** Add a
new "intake complete" event in intake_consult.py before
post-intake reads, with a single producer-side gate at that
event. Adds a new architectural concept (intake-finalize
handshake), not just a contract. Recommend defer to R-residual.

### Flag 5 — Consumer-side gate placement (PSL6 / Trace §T2)

**(Recommended) Inside `prepare_initial_grid_for_draft`,
immediately after the draft row is loaded and BEFORE the 8
parse_json_dict reads at lines 190-197.** Expected placement in
runner.py:80-190 range. Spec doc Commit 3 identifies exact
line during wiring.

**(b) Outside `prepare_initial_grid_for_draft` (e.g., in the
`_run_planning_system_for_draft_unified` caller).** Gate would
need to load the draft row itself, duplicating work the runner
already does. Recommend against.

### Flag 6 — extra policy (PSL4)

**(Recommended) `extra="forbid"` on top-level
IntakeDraftContract.** Established pattern. No sub-contracts
in Commit 1a so no sub-contract extra policy applies; once F0
sub-flag (c) sub-contracts ship, they'll use `extra="ignore"`
per Contracts 1-4 convention.

### Flag 7 — Adjustment B (PSL7 / Trace §Div-6)

**(Recommended) Re-use Contract 4's pattern verbatim.**
intake_consult.py:7377 generic Exception catch propagates
ContractViolation as structured 500 with str(exc) carrying
`INTAKE_DRAFT_STAGE_LABEL`. Test class mirrors Contract 4's
`ApiCatchPatternEndToEndTest`.

### Flag 8 — Diagnostic-emission invariant test (PSL8)

**(Recommended) ADD `ContractFiveEmitsIntakeDraftPhaseCodeTest` +
extend `PhaseCodesDoNotCrossContaminateTest`.** Established
pattern from Contract 2 restoration (e073b6a), continued through
Contracts 3 + 4. Lockstep PhaseCode count 17 → 18.

---

## 8. Known residual cleanups (out of scope for Contract 5)

**P3.40 Contract Layer Cleanup Pass 6/6 final dispositions:**
- R8 → **DONE**: Contract 5b retrofit landed (b7b8da6/662d2a1/fc91083).
- R9 → **DONE**: Contract 5c retrofit landed (763577b/8efdc6e/8942527).
- R10 → **DONE**: Contract 5d retrofit landed (863b393/adb28d1/6c71a14).
- R11 → **NOT PURSUED**: financials_json / financials_year1_json / marketing_model_json / planning_context_summary_json / fulfillment_json are python-aggregated shapes (NOT OpenAI-schema-enforced). The 5e/f/g/h retrofit track would follow a different pattern than 5b/c/d; no current consumer warrants the work.
- R12 → **DEFERRED**: fulfillment_json audit+drop pending Flag 1 (c) producer telemetry.
- R13 → **DEFERRED**: `_apply_scoped_patch` promotion is a follow-up patch-layer cleanup.
- R14 → **DEFERRED**: legacy-table import error squelching is a finmo_bridge cleanup.
- R15 → **DEFERRED**: Producer-side "finalize lock" gate per F4 sub-flag (c) requires consultant-side wiring.
- R16 → **DEFERRED**: `BusinessFactsForSolverContract.fact_template` typing requires Contract 3 sub-shape work.

- **R8.** Sub-contract for `operating_model_json` (Contract 5b).
  Translate OpenAI schema at intake_consultant.py:583 to Pydantic
  `OperatingModelJsonContract`. Add producer-side gate at
  consultant finalize site. Retrofit Contract 3's
  `SolverInputContract.ops_json` to compose the new sub-contract.

- **R9.** Sub-contract for `target_market_json` (Contract 5c).
  Same pattern, OpenAI schema at
  target_market_consultant.py:659.

- **R10.** Sub-contract for `people_json` (Contract 5d). OpenAI
  schema at people_capability_consultant.py:368.

- **R11.** Sub-contracts for `financials_json` /
  `financials_year1_json` / `marketing_model_json` /
  `planning_context_summary_json` (Contracts 5e/f/g/h). These
  are python-aggregated rather than OpenAI-schema-enforced;
  shape capture requires more trace work per shape.

- **R12.** Audit + drop fulfillment_json entirely (per F1 (c)
  reasoning). Verify no downstream consumer needs it; remove
  SQL column + 5 runner.py threading sites + Contract 3
  solver-input field. Standalone cleanup commit.

- **R13.** Promote `_apply_scoped_patch` writers to typed
  patch-set updates (closes Trace Div-3 patch-system "no schema
  gate" v1 §F-2 bug).

- **R14.** `build_shared_context` legacy-table import error
  swallow at shared_context.py:61, 77 (v1 §F-3 bug; carried
  through v2). Separate from intake-draft contract scope.

- **R15.** Producer-side "finalize lock" gate (F4 sub-flag (c)).
  Adds intake-complete handshake.

- **R16.** Inverse retrofit: type `BusinessFactsForSolverContract.fact_template`
  + business-fact scalar fields (F3 reasoning). Crosses
  Contract 3 boundary; Contract 5b/c/etc. wave is the natural
  trigger.

---

## 9. Workflow

Same as Contracts 1, 2, 3, 4: trace doc + spec doc each ship as
single commits, held for Nick review. After spec approval, the
4-commit implementation series (1a → 1b → 1c → 3) lands per §6
with push + email per commit.

Per-commit LOC cap: 700. Contract 5's modules are smaller than
prior contracts (no sub-contracts, no composition) so no LOC
overruns expected.

If during Commit 1a (the contract module) I find anything else
that diverges from production, I'll flag back the same way
Contracts 1-4 did — no silent adjustment.

After Commit 3 lands and the full P3.40 contracts suite goes
green, Contract 5 is end-to-end. The next direction (Contracts
6-7, or R-residual sub-contract typing for the 7 intake-domain
shapes via Contract 5b/c/etc.) comes from Nick.

Expected full-suite total after Contract 5 Commit 3:
~362 (today) + 9 (1b) + 13 (1c) + 13 (3) = ~397 passed.
