# P3.40 Contract 3 — SolverInputContract (Spec)

**Status:** Specification only. No code lands until Nick reviews this doc.
After review, implementation follows the commit sequence in §6 below.

**Boundary covered:** MODEL_INPUT → SOLVER, target-seeking
(Boundary 5 in
[p3_40_pipeline_data_flow_inventory_v2.md](p3_40_pipeline_data_flow_inventory_v2.md)).

**Predecessors:**
- [Contract 1 — FinmoModelInputContract](p3_40_contract_1_finmo_model_input_spec.md) (landed at SHA b7f3584). Composed by Contract 3 for `applied_model_input_json` and (per Flag 2 keep-all-required) `catalog_source_model_input_json`.
- [Contract 2 — WorkbookPayloadContract](p3_40_contract_2_workbook_payload_spec.md) (landed at SHA a6db38c). Composed by Contract 3 for `applied_finmo_json` (via `FinmoOutputContract`) and `stage_ramp_contract` (via `StageRampContract`). Re-imports rather than redefines.

**Companion trace doc:** [p3_40_contract_3_solver_input_trace.md](p3_40_contract_3_solver_input_trace.md)
(landed at SHA c15df40, amended with TC1-TC3 resolutions). All
file:line citations and divergence findings below trace back to
that doc.

**Lessons applied from Contracts 1 and 2:**
- Trace before spec. The trace doc surfaced 3 Div items v2 didn't catch (Div-1, Div-3, Div-8) plus 3 trace-completion items (TC1-TC3) that resolved before this spec drafted.
- Match production vocabulary verbatim. Param names + types + the `_VALID_PLANNING_MODES` enumeration lifted from orchestrator.py:1028 + 1102.
- Constraints from production reality. Contract 2's 1a-fix lesson (int/float/Decimal → type as float) applies to any numeric fields in typed sub-contracts.
- Don't loosen safety checks. Tier-F field treatment (Flag 2) keeps all 19 fields required + typed.
- `extra="forbid"` only on the top-level contract; `extra="ignore"` on sub-contracts and rows.
- Adjustment B is recurring. Trace Div-8 confirms it works identically at this boundary via the API-handler line-7377 generic catch.

---

## 1. Trace Task Findings

The 7 pre-implementation traces (T1-T7) plus 3 trace-completion
items (TC1-TC3) produced findings folded directly into this
spec's structure. The full enumeration is in the trace doc; this
section consolidates the ones that change contract design.

### 1.1 Eight v2-inventory divergences (Div-1 through Div-8)

| Div | Description | Class | Impact on spec |
|---|---|---|---|
| Div-1 | v2 §D miscounts "6 READER_MISSING" — actual breakdown is 3 truly unread + 2 cascade-phantom-but-orchestrator-persists + 3 closure-only-but-actually-read | NEW SUBSTANTIVE | §2 tier classification (A/B/C/F) + Flag 2 disposition |
| Div-2 | Producer-side gate already exists at runner.py:1809-1822 (Contract 1) | CONFIRMED CLOSED | §5: Contract 3's producer gate is the SECOND validate call at runner.py:1830 (next 20 lines), validating different fields. Structurally clean. |
| Div-3 | Two-hop wrapper between API and solver entry (`_run_unified_post_grid_system_run` + `_run_planning_system_for_draft_unified`) | NEW STRUCTURAL | §5 places the consumer-side gate inside the orchestrator entry (orchestrator.py:1028) rather than in either wrapper layer |
| Div-4 | `stage_ramp_contract` consumed without shape validation at 4 sites | CONFIRMED RESIDUAL | Flag 3 disposition closes this at the solver boundary by composing Contract 2's `StageRampContract` |
| Div-5 | Lossy model_input transformations (in-place at orchestrator.py:1208, 1280, 1349) | CONFIRMED RESIDUAL | Out of scope. Contract describes the boundary, not internal mutation. |
| Div-6 | `_inner_runner` NameError | CONFIRMED CLOSED | No action needed. |
| Div-7 | In-place parameter shadowing | CONFIRMED RESIDUAL | Out of scope. |
| Div-8 | ContractViolation propagation through API handler's `except Exception` at intake_consult.py:7377 | CONFIRMED | §6 commit 3 includes Adjustment B verification test mirroring Contract 2's `ApiBoundaryContractViolationTest`. |

### 1.2 Trace-completion items (TC1-TC3) — RESOLVED

**TC1. `planning_mode` enumeration.**
Resolved via grep of orchestrator.py:1100-1115. Four supported
values:

```python
_VALID_PLANNING_MODES = {"growth", "stability", "runway_extension", "survival"}
```

The spec's `planning_mode` field types as
`Literal["growth", "stability", "runway_extension", "survival"]`
(§3.1). Pin via test_typo_accepted + test_correct_spelling_rejected
pair per Contract 1's typo-lock pattern.

**TC2. `applied_finmo_json` composition.**
Resolved by tracing the producer — `build_python_finmo_json` at
runner.py:815/855, the same function Contract 2's
`FinmoOutputContract` already types. **Spec composes
`FinmoOutputContract` directly** for `applied_finmo_json`. No flag
— same disposition as Flag 6 for `FinmoModelInputContract`
composition.

**TC3. Tier-C shape typing.**
Resolved by tracing the two persist-site readers
(`_build_minimal_convergence_context` and
`_persist_unified_convergence_state` chain). Both Tier-C payloads
(`planning_context_summary_json`, `grid_application_summary`) are
**pure round-trip** to JSON columns — no `.get(...)` chains, no
structured reads. `_build_minimal_convergence_context` even does
`del planning_context_summary_json` on its first line (the parameter
is kept for caller-compat only). **Spec types both as
`Dict[str, Any]` opaque** (no typed sub-contract).

### 1.3 Producer surface

Single producer for all 19 data fields:
`prepare_initial_grid_for_draft` at
[runner.py:30+](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30),
return statement at
[runner.py:1830-1850](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1830).
This contrasts with Contract 2's 5-writer surface (R8 deferral)
and makes a **single producer-side gate at runner.py:1830
feasible** (Flag 5: SHIP).

---

## 2. Top-level production payload — 19-field roster

Tier legend (from trace T2.1):
- **A. consumed-direct.** Orchestrator body reads the payload at one or more sites. Type with full sub-contract.
- **B. closure-only.** Read only via the `_build_finmo_callable` closure at orchestrator.py:1361-1367. Type with full sub-contract (Contract 1 composition for the 3 closure params will land in Contract 5 / IntakeDraftContract per Flag 4).
- **C. persist-only.** Cascade-phantom but orchestrator persists via `_persist_unified_convergence_state`. Per TC3: type as `Dict[str, Any]` opaque (pure round-trip — no structured read at persist layer).
- **F. truly READER_MISSING.** No reader anywhere in the module. Per Flag 2 keep-all-required: type with full sub-contract anyway, closing the door on silent shape drift if a future cascade refactor unpacks them.

| # | Field | Tier | Contract type |
|---|---|---|---|
| 1 | `business_facts` | A | `BusinessFactsForSolverContract` (new sub-contract, opaque-at-fact_template per Flag 4) |
| 2 | `planning_context_summary_json` | C | `Dict[str, Any]` opaque (TC3) |
| 3 | `ops_json` | A | `Dict[str, Any]` opaque (intake-domain shape, Flag 4 defers to Contract 5) |
| 4 | `target_market_json` | F | `Dict[str, Any]` opaque (Flag 2 keep-required; no structured reader so no sub-contract pays off today) |
| 5 | `people_json` | B | `Dict[str, Any]` opaque (Flag 4 defers to Contract 5) |
| 6 | `financials_json` | A | `Dict[str, Any]` opaque (Flag 4 defers to Contract 5) |
| 7 | `financials_year1_json` | A | `Dict[str, Any]` opaque (Flag 4 defers to Contract 5) |
| 8 | `fulfillment_json` | B | `Dict[str, Any]` opaque (Flag 4 defers to Contract 5) |
| 9 | `marketing_model_json` | B | `Dict[str, Any]` opaque (Flag 4 defers to Contract 5) |
| 10 | `planning_mode` | A | `Literal["growth", "stability", "runway_extension", "survival"]` (TC1) |
| 11 | `planning_mode_reason` | A | `str` |
| 12 | `planning_result` | F | `Dict[str, Any]` opaque (Flag 2 keep-required) |
| 13 | `grid_application_summary` | C | `Dict[str, Any]` opaque (TC3); Optional because orchestrator entry signature already has it as Optional |
| 14 | `catalog_source_model_input_json` | F | `FinmoModelInputContract` (Flag 2 keep-required + Flag 6 compose Contract 1) |
| 15 | `applied_model_input_json` | A | `FinmoModelInputContract` (Flag 6 compose Contract 1) |
| 16 | `applied_finmo_json` | A | `FinmoOutputContract` (TC2 compose Contract 2) |
| 17 | `stage_ramp_contract` | A | `Optional[StageRampContract]` (Flag 3 compose Contract 2's `StageRampContract`); Optional because orchestrator entry signature has it as Optional |
| 18 | `payroll_headcount` | A | `Optional[PayrollHeadcountContract]` (compose Contract 2's `PayrollHeadcountContract`); Optional because orchestrator entry signature has it as Optional |
| 19 | (`applied_finmo_json` deduped — counted once at row 16) | | |

Plus 3 runtime context params (NOT data) treated specially:
- `conn` — DB connection. NOT in the contract. Passed via the wrapper or helper outside the contract surface.
- `draft_id: str` — runtime identifier. Type as `str` if included in the contract, or carried separately. Spec choice: **include both `draft_id` and `planning_run_id` in the contract** as `str` and `Optional[str]` so the producer-side gate can validate they're present.
- `planning_run_id: Optional[str]` — runtime identifier. Type as `Optional[str]`.

**Final contract field count: 19 data fields + 2 runtime IDs = 21
typed fields on top-level `SolverInputContract`.** `conn` is
passed alongside, not inside the contract.

### 2.1 Why three opaque-typed Contract-1-shaped fields aren't redundant with Contract 1

`applied_model_input_json` and `catalog_source_model_input_json`
are both `FinmoModelInputContract`. Contract 1's producer-side
gate at runner.py:1809-1822 already validates
`applied_model_input_json`. So why type it AGAIN at Contract 3?

- **Defense in depth.** The producer-side gate at runner.py:1809
  validates immediately before the dict return at runner.py:1830.
  Contract 3's consumer-side gate at orchestrator.py:1028
  validates immediately after the API-layer two-hop deep-copy
  chain (Div-3). If a future wrapper layer or test harness
  bypasses the producer-side gate, the consumer-side gate still
  fires.
- **catalog_source_model_input_json is NOT Contract-1-gated.**
  Only `applied_model_input_json` is gated upstream today.
  `catalog_source_model_input_json` is the pre-grid baseline
  (runner.py:1846: `copy.deepcopy(model_input_json)`) and goes
  through the contract gate for the first time here.

---

## 3. Field-by-field contract spec

### 3.1 Top-level `SolverInputContract`

```python
class SolverInputContract(BaseModel):
  """The 21-field bundle at the MODEL_INPUT → SOLVER boundary.

  Composes Contract 1 (FinmoModelInputContract) for 2 fields,
  Contract 2's FinmoOutputContract for 1 field, Contract 2's
  StageRampContract for 1 field, Contract 2's
  PayrollHeadcountContract for 1 field. The other 15 fields are
  new typed sub-contracts or opaque Dict[str, Any] per Tier
  classification (§2).
  """

  # Runtime identifiers (not data; included so producer-gate can
  # confirm they're set before bundle return).
  draft_id: str = Field(min_length=1)
  planning_run_id: Optional[str] = None

  # Tier A — consumed-direct, typed sub-contracts
  business_facts: BusinessFactsForSolverContract
  ops_json: Dict[str, Any]  # opaque — Flag 4 defers to Contract 5
  financials_json: Dict[str, Any]  # opaque — Flag 4
  financials_year1_json: Dict[str, Any]  # opaque — Flag 4
  applied_model_input_json: FinmoModelInputContract  # Flag 6 compose Contract 1
  applied_finmo_json: FinmoOutputContract  # TC2 compose Contract 2
  planning_mode: Literal["growth", "stability", "runway_extension", "survival"]  # TC1
  planning_mode_reason: str

  # Tier B — closure-only consumed via _build_finmo_callable
  people_json: Dict[str, Any]  # opaque — Flag 4
  fulfillment_json: Dict[str, Any]  # opaque — Flag 4
  marketing_model_json: Dict[str, Any]  # opaque — Flag 4

  # Tier C — persist-only (orchestrator.py:3609/3621), pure round-trip
  planning_context_summary_json: Optional[Dict[str, Any]] = None  # TC3 opaque
  grid_application_summary: Optional[Dict[str, Any]] = None  # TC3 opaque

  # Tier F — truly READER_MISSING; kept required + typed per Flag 2
  target_market_json: Dict[str, Any]  # opaque — Flag 2 keep-required
  planning_result: Dict[str, Any]  # opaque — Flag 2 keep-required
  catalog_source_model_input_json: FinmoModelInputContract  # Flag 2 + Flag 6 compose

  # Optional fields per orchestrator entry signature
  stage_ramp_contract: Optional[StageRampContract] = None  # Flag 3 compose Contract 2
  payroll_headcount: Optional[PayrollHeadcountContract] = None  # compose Contract 2

  model_config = ConfigDict(extra="forbid")  # Flag 7 top-level only
```

### 3.2 `BusinessFactsForSolverContract` (new sub-contract)

The only new typed sub-contract. `business_facts` has the shape
the orchestrator actually reads — primarily nested under
`fact_template`. Per Flag 4, `fact_template` itself is typed as
opaque `Dict[str, Any]` for the first cut (the fields read —
`business_stage`, `business_model` — are intake-domain shapes
deferred to Contract 5).

```python
class BusinessFactsForSolverContract(BaseModel):
  """The business_facts payload at the solver boundary.

  Per trace T4: read at compute_adaptive_policy (orchestrator.py:1156),
  _bf_template extraction (1188-1195), business_stage_for_cascade
  (1605-1607), _build_finmo_callable closure (1361). All reads
  bottom out in .fact_template (an intake-domain shape) or treat
  the top-level dict as opaque.

  Typed minimally for first cut: fact_template is required as
  Dict[str, Any] (the only reads bottom out there); other top-level
  keys are permitted via extra=ignore.
  """

  fact_template: Dict[str, Any]  # Flag 4 opaque

  model_config = ConfigDict(extra="ignore")
```

### 3.3 Re-imports from prior contracts

```python
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
  FinmoModelInputContract,
)
from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (
  FinmoOutputContract,  # for applied_finmo_json
  PayrollHeadcountContract,  # for payroll_headcount
  StageRampContract,  # for stage_ramp_contract
)
```

No new typing of `FinmoOutputContract` / `PayrollHeadcountContract`
/ `StageRampContract` — Contract 3 re-uses Contract 2's definitions
verbatim. This avoids type drift between the workbook-side typing
and the solver-side typing.

---

## 4. Cross-field invariants

Per Flag 8 enumeration:

### 4.1 `planning_mode_in_supported_set`

Enforced by the `Literal[...]` field declaration; no separate
validator needed. Pydantic emits the rejection at field-level
validation time. (Test pins both the typo-rejection and the four
valid spellings — Contract 1 typo-lock pattern.)

### 4.2 `stage_ramp_contract_quarter_ramp_grid_length` (Flag 3 → compose)

Already enforced inside Contract 2's `StageRampContract`. By
composing rather than redefining, Contract 3 inherits the
invariant automatically. (Verified: spec re-imports
`StageRampContract` from `workbook_payload_contract.py`.)

### 4.3 `payroll_headcount_rows_cover_all_horizon_quarters`

Already enforced inside Contract 2's `PayrollHeadcountContract`.
Same composition pattern as 4.2.

### 4.4 `planning_run_id_present_when_persisting`

If `planning_run_id is None`, the orchestrator's persist site
(orchestrator.py:3609) still calls `_persist_unified_convergence_state`
with `planning_run_id=""` which the persist layer silently skips.
Per Contract 1's "fail loud at the boundary" principle, the
contract should enforce: `planning_run_id is not None and
len(planning_run_id.strip()) > 0`.

**Spec recommends (a):** type as
`planning_run_id: str = Field(min_length=1)` (NOT `Optional[str]`).
This tightens the orchestrator entry signature (which today is
`Optional[str]`); the test would confirm the orchestrator's
implicit assumption is captured.

**Alternative (b):** match the orchestrator entry's `Optional[str]`
exactly. Producer-side gate would still pass `planning_run_id=""`
through silently.

Flag 8(a) for Nick (sub-flag inside Flag 8 cross-field
invariants). Recommend (a) — tighten.

### 4.5 `applied_model_input_json` and `catalog_source_model_input_json` agree on `contract_version`

Both fields type as `FinmoModelInputContract`. Contract 1 enforces
`contract_version: Literal["finmo_model_input_v3"]`. The cross-
field invariant adds: both fields' `contract_version` strings
match. This catches a future producer drift where the two paths
fall out of lockstep.

**Spec recommends (a) include.** Cheap invariant; surfaces drift.

---

## 5. Boundary enforcement

### 5.1 Producer-side gate (Flag 5 SHIP)

**Location:** the very last action of `prepare_initial_grid_for_draft`
before the dict return at runner.py:1830.

```python
# python/client_intake_and_finmo/post_intake_initial_grid/runner.py

# (existing line 1822) Contract 1 producer-side gate stays
validate_model_input_at_boundary(
  copy.deepcopy(applied_model_input_json or {}),
  side=SIDE_PRODUCER,
  emit_diagnostic_fn=_boundary_emitter,
)

# (new) P3.40 Contract 3 producer-side gate.
from client_intake_and_finmo.post_intake_contracts.enforcement import (  # type: ignore
  SIDE_PRODUCER as _SOLVER_SIDE_PRODUCER,
  validate_solver_input_at_boundary,
)
validate_solver_input_at_boundary(
  {
    "draft_id": str(draft_id or "").strip(),
    "planning_run_id": str(active_planning_run_id or "").strip() or None,
    "business_facts": copy.deepcopy(business_facts or {}),
    "planning_context_summary_json": copy.deepcopy(planning_context_summary_json or {}),
    "ops_json": copy.deepcopy(ops_json or {}),
    "target_market_json": copy.deepcopy(market_json or {}),
    "people_json": copy.deepcopy(people_json or {}),
    "financials_json": copy.deepcopy(financials_json or {}),
    "financials_year1_json": copy.deepcopy(financials_year1_json or {}),
    "fulfillment_json": copy.deepcopy(fulfillment_json or {}),
    "marketing_model_json": copy.deepcopy(marketing_model_json or {}),
    "planning_mode": planning_mode,
    "planning_mode_reason": planning_mode_reason,
    "planning_result": copy.deepcopy(planning_result or {}),
    "grid_application_summary": copy.deepcopy(grid_application_summary or {}) or None,
    "catalog_source_model_input_json": copy.deepcopy(model_input_json),
    "applied_model_input_json": copy.deepcopy(applied_model_input_json),
    "applied_finmo_json": copy.deepcopy(applied_finmo_json),
    "stage_ramp_contract": copy.deepcopy(stage_ramp_contract) or None,
    "payroll_headcount": copy.deepcopy(payroll_headcount_payload) or None,
  },
  side=_SOLVER_SIDE_PRODUCER,
  emit_diagnostic_fn=_boundary_emitter,
)

# (existing line 1830) dict return …
```

The two gates fire within 20 lines of each other, validating
disjoint fields. Per Div-2 this is structurally clean — one gate
per contract, not merged.

### 5.2 Consumer-side gate

**Location:** the FIRST executable line of
`run_target_seeking_orchestrated_system_run` body at
orchestrator.py:1028, before any other consumption.

Per Div-3, placing it inside the orchestrator entry rather than
in either wrapper layer keeps the gate co-located with the
consumer. Per Div-5, the gate validates at entry only — internal
mutation isn't re-validated.

```python
# python/client_intake_and_finmo/post_intake_solver/orchestrator.py:1028+

def run_target_seeking_orchestrated_system_run(*, conn, draft_id, …):
  # P3.40 Contract 3 consumer-side gate -- FIRST executable line.
  # Validates the 19-field bundle before adaptive_policy / feasibility
  # restoration / solver loop. Replaces the implicit ad-hoc shape
  # assumptions scattered through the body with one fail-fast point.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (
    SIDE_CONSUMER as _SOLVER_SIDE_CONSUMER,
    validate_solver_input_at_boundary,
  )
  validate_solver_input_at_boundary(
    {
      "draft_id": draft_id,
      "planning_run_id": planning_run_id,
      "business_facts": business_facts,
      "planning_context_summary_json": planning_context_summary_json,
      "ops_json": ops_json,
      "target_market_json": target_market_json,
      "people_json": people_json,
      "financials_json": financials_json,
      "financials_year1_json": financials_year1_json,
      "fulfillment_json": fulfillment_json,
      "marketing_model_json": marketing_model_json,
      "planning_mode": planning_mode,
      "planning_mode_reason": planning_mode_reason,
      "planning_result": planning_result,
      "grid_application_summary": grid_application_summary,
      "catalog_source_model_input_json": catalog_source_model_input_json,
      "applied_model_input_json": applied_model_input_json,
      "applied_finmo_json": applied_finmo_json,
      "stage_ramp_contract": stage_ramp_contract,
      "payroll_headcount": payroll_headcount,
    },
    side=_SOLVER_SIDE_CONSUMER,
  )

  # (existing body continues)
```

### 5.3 Enforcement helper

Added to existing `enforcement.py` (alongside Contract 1's
`validate_model_input_at_boundary` and Contract 2's
`validate_workbook_payload_at_boundary`):

```python
SOLVER_STAGE_LABEL = "MODEL_INPUT→SOLVER"

def validate_solver_input_at_boundary(
  payload: Dict[str, Any],
  *,
  side: str,
  stage: str = SOLVER_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> SolverInputContract:
  """P3.40 Contract 3 boundary gate. Validate ``payload`` against
  SolverInputContract and return the parsed contract on success.

  Producer-side: called at end of prepare_initial_grid_for_draft
  (runner.py:1830, just before dict return). Consumer-side:
  called as FIRST line of run_target_seeking_orchestrated_system_run
  (orchestrator.py:1028).

  On failure raises ContractViolation with the SOLVER stage label
  and the first ValidationError extracted into structured fields.
  Same pattern as Contracts 1 and 2: best-effort emit on success
  (SOLVER_INPUT_CONTRACT_VALIDATED), best-effort emit on failure
  (SOLVER_INPUT_CONTRACT_VIOLATION) before raising.

  Per Adjustment B (trace Div-8): ContractViolation propagates
  cleanly through the API handler's `except Exception as exc`
  catch at intake_consult.py:7377 — no audit wrapper interposes
  at this boundary.
  """
  ...
```

Mirror the existing model-input / workbook-payload helpers
verbatim. Same `_extract_first_error` / `_safe_emit` private
helpers reused.

### 5.4 Adjustment B verification (Div-8 confirmed)

Per Div-8 trace, the API handler at
[intake_consult.py:7377](../../python/api_handlers/intake_consult.py#L7377)
catches `except Exception as exc:` and logs `str(exc)` via
`_dispatch_post_intake_failure_alert` + `app.logger.exception`.

`ContractViolation` is a subclass of `Exception` (not `RuntimeError`,
so it skips the line-7298 `except RuntimeError as exc` branch).
The line-7377 generic catch handles it, returning HTTP 500 with
`detail=str(exc)`, persisting failure snapshot, and dispatching
the failure email.

The `str(ContractViolation)` format carries the
`MODEL_INPUT→SOLVER` stage tag + field path + expected vs actual —
informative for the operator, not a fallback stack trace.

§6 Commit 3 includes a test mirroring Contract 2's
`ApiBoundaryContractViolationTest` end-to-end pattern.

### 5.5 PhaseCode / EventCode / FailFastCode additions

New entries (lockstep with the existing test lock-counts per
Contract 1's lesson):

- `PhaseCode.SOLVER_INPUT_CONTRACT`
- `EventCode.SOLVER_INPUT_CONTRACT_VALIDATED`
- `EventCode.SOLVER_INPUT_CONTRACT_VIOLATION`
- `FailFastCode.FAIL_SOLVER_INPUT_CONTRACT_VIOLATION = "fail_solver_input_contract_violation"`

Lock-count tests to update:
`test_phase_9_p3_33_phase3_step9a_phase_codes.py` and any other
enumeration-pinning tests that count Contract codes.

---

## 6. Implementation sequence

After Nick green-lights this spec, implementation follows:

### Commit 1a — Contract module

File: `python/client_intake_and_finmo/post_intake_contracts/solver_input_contract.py`

- 1 new sub-contract: `BusinessFactsForSolverContract`
- 1 top-level: `SolverInputContract`
- Re-imports from Contracts 1 and 2 (no redefinition of
  `FinmoOutputContract` / `StageRampContract` /
  `PayrollHeadcountContract` / `FinmoModelInputContract`)
- 5 cross-field invariants per §4
- Module docstring covering boundary + composition + Flag 8(a) tightening of `planning_run_id`

Expected LOC: 350-500. Single file artifact. Well under 700 cap.

### Commit 1b — Fixtures + sub-contract tests

`tests/_p3_40_contract_3_fixtures.py` + `tests/test_p3_40_contract_3_subcontracts.py`

Imports Contract 1 + 2 fixtures (`valid_top_level` as
`valid_model_input_json_dict`, `valid_finmo_output_dict`,
`valid_stage_ramp_contract_dict`, `valid_payroll_headcount_dict`).
Adds:

- `valid_business_facts_dict()`
- `valid_solver_input_dict(include_optionals=True)`

Tests per sub-contract:
- `BusinessFactsForSolverContract`: valid, missing fact_template,
  extra=ignore behavior (3-4 tests).
- `planning_mode` Literal: 4 valid spellings accepted, 1 typo
  rejected (test_typo_accepted + test_correct_spelling_rejected
  per Contract 1 typo-lock pattern) (5 tests).
- Tier-F field round-trip: `target_market_json`, `planning_result`,
  `catalog_source_model_input_json` accept any dict shape (3 tests).
- Tier-C field round-trip: `planning_context_summary_json`,
  `grid_application_summary` accept any dict shape (2 tests).
- Optional field absence: `stage_ramp_contract`,
  `payroll_headcount`, `grid_application_summary`,
  `planning_context_summary_json`, `planning_run_id` (5 tests).

Target: 18-22 tests.

### Commit 1c — Top-level + cross-field + API-boundary tests

`tests/test_p3_40_contract_3_solver_input.py`

5 test classes mirroring Contract 2 §1c:

- `SolverInputContractTopLevelTest`: 21 required-field rejections,
  `extra="forbid"` on top-level (~8-12 tests).
- `CompositionWithContract1Test`: `applied_model_input_json` typed
  as `FinmoModelInputContract`; Contract 1 invariant violations
  propagate (2 tests).
- `CompositionWithContract2Test`: `applied_finmo_json` typed as
  `FinmoOutputContract`; `stage_ramp_contract` typed as
  `StageRampContract`; `payroll_headcount` typed as
  `PayrollHeadcountContract`. Contract 2 invariant violations
  propagate (3-4 tests).
- `CrossFieldInvariantTest`: invariants 4.4 (planning_run_id_present),
  4.5 (contract_version agreement). Both halves of each pair (3-4
  tests).
- `ApiBoundaryContractViolationTest`: Adjustment B verification.
  Mirrors Contract 2 `ApiBoundaryContractViolationTest`:
  ContractViolation message uses `SOLVER_STAGE_LABEL`; structured
  attributes accessible; survives generic Exception catch;
  source_payload not dumped into str (4 tests).

Target: 20-25 tests.

### Commit 2 — Adapter (classmethod, no dataclass per Flag 1)

Add to contract module:

```python
@classmethod
def from_initial_grid_state(
  cls,
  state: Dict[str, Any],
  *,
  draft_id: str,
  planning_run_id: Optional[str] = None,
) -> "SolverInputContract":
  """Build SolverInputContract from the dict prepare_initial_grid_for_draft
  returns at runner.py:1830-1850.

  Translates dict keys to contract fields. Drops keys that aren't
  part of the solver input (post_intake_process_sequence_trace,
  shared_context, draft). Caller passes draft_id + planning_run_id
  explicitly since those don't always live inside `state`."""
  ...
```

Plus matching `to_initial_grid_state(...)` for round-trip in tests.

Tests in `tests/test_p3_40_contract_3_adapter.py`:
- `from_initial_grid_state` accepts valid runner.py:1830 shape (3-4 tests).
- `from_initial_grid_state` rejects bad shapes with ContractViolation (3-4 tests).
- Round-trip: state → contract → state preserves the 19 fields (1-2 tests).
- Drops non-contract keys (`post_intake_process_sequence_trace`,
  `shared_context`, `draft`) without raising (1-2 tests).

Target: 8-12 tests.

### Commit 3 — Consumer-side gate + Producer-side gate + Adjustment B test

THREE wirings in one commit (per §5):

1. **Consumer-side gate** at orchestrator.py:1028 (first executable
   line of `run_target_seeking_orchestrated_system_run`).
2. **Producer-side gate** at runner.py:1830 (just before bundle
   return; second validate call after Contract 1's gate at
   runner.py:1809-1822).
3. **Enforcement helper** added to `enforcement.py`
   (`validate_solver_input_at_boundary`, `SIDE_PRODUCER` /
   `SIDE_CONSUMER` reused, `SOLVER_STAGE_LABEL` new).
4. **PhaseCode / EventCode / FailFastCode** additions per §5.5.
   Lockstep update of `test_phase_9_p3_33_phase3_step9a_phase_codes.py`.

Tests in `tests/test_p3_40_contract_3_consumer_gate.py`:
- Valid bundle through orchestrator entry passes (1 test — DOES
  NOT run the full solver; only confirms the gate fires and the
  orchestrator returns/proceeds normally up to the next blocking
  point).
- Missing each of 19 required fields → ContractViolation (~6-8
  representative tests, not exhaustive — 19 tests would be churn).
- Bad sub-payload → field path points into violation location (2-3
  tests).
- Adjustment B end-to-end: ContractViolation propagates through
  `except Exception` catch at intake_consult.py:7377 with stage tag
  + field in str(exc) (3 tests).

Target: 12-15 tests.

Implementation note: the consumer-side test for "valid bundle
passes the gate" cannot run the full solver in a unit test (the
solver needs a live DB conn + amalgamated session + many GPT
calls). The test asserts the gate fires + returns the validated
contract without raising; subsequent solver mechanics are out of
scope for boundary contract testing.

### Commit 4 (optional) — Replace defensive `or {}` patterns with typed access

Per trace T5.1, the orchestrator body has 20+ `<param> or {}`
defensive coalesces that the gate makes redundant. A follow-up
commit could remove them site-by-site.

Spec recommends: **defer to R8/R11 follow-up.** Removing 20+
defensive sites is a separate, riskier refactor; the contract's
boundary guarantee is the primary value. Skip Commit 4 here.

---

## 7. Open flags for Nick's review

8 decisions (4 with spec recommendations toward Nick's pre-stated
lean per the directive; 4 still open for Nick's confirmation).

### Flag 1 — Adapter shape (Nick lean: classmethod, no dataclass)

**(Recommended) (a) Classmethod + helper.** No new dataclass; use
`SolverInputContract.from_initial_grid_state(state, draft_id=...,
planning_run_id=...)` + `validate_solver_input_at_boundary(payload,
side=...)` helper. No existing dataclass at this boundary;
introducing one solely to mirror Contract 2's `DraftWorkbookData`
is over-engineering.

**(b) Introduce `SolverInputBundle` dataclass.** Would mirror
Contract 2's pattern but adds a new module + a dataclass with
21+ fields and no behavior beyond the contract.

### Flag 2 — Tier-F field treatment (Nick lean: keep-all-required)

**(Recommended) (a) Keep all 19 required + typed.** Same
disposition as Contract 2 Flag 1 for `debt_schedule`. Don't loosen
safety checks. Tier-F params (`target_market_json`, `planning_result`,
`catalog_source_model_input_json`) get full typed sub-contracts
(opaque `Dict[str, Any]` for the truly-opaque pair;
`FinmoModelInputContract` for `catalog_source_model_input_json` per
Flag 6) even though they're unread today. Closes the door on
silent shape drift if a future cascade refactor unpacks them.

**(b) Drop Tier-F from the contract.** Aligns with v2 §D's
recommendation that the call signature "can be trimmed". Cheaper
contract but riskier — a future unread → read transition would
land without a contract amendment.

### Flag 3 — `stage_ramp_contract` typed sub-model (Nick lean: compose Contract 2)

**(Recommended) (a) Compose `StageRampContract` directly.** Re-import
from `workbook_payload_contract.py`. Closes Div-4 / v2 §F.3 at
the solver boundary in the same commit. No type drift between
solver-side and workbook-side typing.

**(b) Leave as `Optional[Dict[str, Any]]` opaque.** Defers Div-4
to a producer-side fix; cheaper Contract 3 commit but leaves the
silent zero-fill bug class alive at the solver boundary.

### Flag 4 — Nested-key typing (Nick lean: opaque first cut)

**(Recommended) (a) Opaque for first cut.** `fact_template`,
`ops_json`, `financials_json`, `financials_year1_json`,
`people_json`, `fulfillment_json`, `marketing_model_json` all
type as `Dict[str, Any]`. These are intake-domain shapes;
Contract 3 detour into intake territory is scope creep. Defer to
Contract 5 (IntakeDraftContract).

**(b) Type each intake-domain payload.** Would type
`fact_template`, ops, financials etc. with sub-contracts. Pulls
intake-domain scope into Contract 3. Recommend defer.

### Flag 5 — Producer-side gate (Nick lean: SHIP)

**(Recommended) (a) SHIP producer-side gate at runner.py:1830.**
Single producer (Div-2) makes one gate feasible. Adds one
validate call. Contract 1 placed its gate outside the floor
wrapper; same disposition here — the gate lives at the end of
`prepare_initial_grid_for_draft`, before the dict return. The
Contract 1 producer-side gate at runner.py:1809-1822 still fires
first; Contract 3's gate is the SECOND validate call in the same
function within 20 lines, validating disjoint fields. Structurally
clean per Div-2.

**(b) Defer to R8 follow-up.** Cheaper Commit 3 but loses the
defense-in-depth property the gate provides.

### Flag 6 — Contract 1 composition (Nick lean: yes)

**(Recommended) (a) Yes, type `applied_model_input_json` as
`FinmoModelInputContract` + (per Flag 2) `catalog_source_model_input_json`
as `FinmoModelInputContract`.** Same composition pattern as
Contract 2. No invention.

**(b) Type as opaque `Dict[str, Any]`.** Drops the Contract 1
sub-shape guarantee at this boundary. Recommend against.

### Flag 7 — `extra` policy (Nick lean: top-level forbid)

**(Recommended) (a) `extra="forbid"` on top-level
`SolverInputContract`; `extra="ignore"` on every sub-contract +
row.** Established pattern from Contracts 1 and 2.

**(b) `extra="forbid"` everywhere.** Would reject the writer-side
extras Contract 2's sub-contracts intentionally permit. Recommend
against.

### Flag 8 — Cross-field invariants enumeration

Spec proposes 5 invariants in §4. Two are inherited via composition
(4.2 from `StageRampContract`, 4.3 from `PayrollHeadcountContract`)
and don't need a Nick decision. The other 3:

#### 8(a) — `planning_run_id` presence (4.4)

**(Recommended) (a) Tighten:** `planning_run_id: str = Field(min_length=1)`
(NOT `Optional[str]`). Per Contract 1's "fail loud at the
boundary" principle. Tightens the orchestrator entry signature
(today `Optional[str]`); test confirms the orchestrator's implicit
assumption is captured.

**(b) Match orchestrator entry:** `planning_run_id: Optional[str] = None`.
Permits the empty-string pass-through pattern the persist layer
silently skips on.

#### 8(b) — `contract_version` agreement (4.5)

**(Recommended) (a) Include.** Cheap invariant; surfaces drift if
`applied_model_input_json` and `catalog_source_model_input_json`
ever have differing `contract_version`. Type-system already pins
each individually to `Literal["finmo_model_input_v3"]`; this is
the cross-field equivalent.

**(b) Skip.** Saves one validator; loses one drift catch.

#### 8(c) — `planning_mode` Literal pinning

Already enforced by the field declaration; no separate validator.
No Nick decision needed.

---

## 8. Known residual cleanups (out of scope for Contract 3)

**P3.40 Contract Layer Cleanup Pass 6/6 final dispositions:**
- R8 → **DEFERRED**: Same pattern as Contract 1 R7 — deep defensive-read migration; scope too large for cleanup batch.
- R9 → **DEFERRED**: Same as Contract 2 R9 (`validate_draft_data` deletion needs caller audit).
- R10 → **DONE** via the 5b/5c/5d retrofit series (Cleanups 5b/5c/5d landed at fc91083/8942527/6c71a14).
- R11 → **DONE** via Contract 4 landing (the SolverOutputContract spec covers the typed contract that R11 anticipated).
- R12 → **DEFERRED**: API wrapper consolidation is architectural cleanup, not contract scope.

- **R8.** Defensive `or {}` pattern removal in the orchestrator
  body (trace T5.1). 20+ sites that the contract gate makes
  redundant. Separate commit / commits per scope (the gate alone
  doesn't break them; they're now dead defense).

- **R9.** `validate_draft_data` deletion (Contract 2 R9, still
  open at Contract 3 start). Contract 2 Commit 3 already removed
  the only caller; the function definition can be deleted in a
  follow-up. Lives in Contract 2's R-residual list; surfaces here
  only for cross-reference.

- **R10.** Intake-domain typed contracts (Contract 5):
  `fact_template`, `ops_json`, `financials_json`,
  `financials_year1_json`, `people_json`, `fulfillment_json`,
  `marketing_model_json`. Per Flag 4 deferred from Contract 3.
  Would land as `IntakeDraftContract` or split into per-domain
  contracts. Boundary 1 / 2 / 3 in the v2 inventory cover the
  producer sites.

- **R11.** Solver output typed contract (Contract 4): the
  `Dict[str, Any]` return at orchestrator.py:1768. Trace T6
  enumerates the keys. Would be `SolverOutputContract` /
  `FinmoJsonContract` (scope TBD when Contract 4 is opened).

- **R12.** Two-hop API wrapper consolidation (Div-3):
  `_run_unified_post_grid_system_run` +
  `_run_planning_system_for_draft_unified` are pure forwarding
  layers. Consolidation is a cleanup, not a contract concern.

---

## 9. Workflow

Same as Contracts 1 and 2: trace doc + spec doc each ship as
single commits, held for Nick review. After spec approval, the
4-commit implementation series (1a → 1b → 1c → 2 → 3) lands per
§6 with push + email per commit.

Per-commit LOC cap: 700. If a natural unit exceeds the cap
(Contract 1 1a was 749, Contract 2 1b was 847), single-artifact
ships are acceptable with a note matching prior precedent.

If during Commit 1a (the contract file) I find anything else that
diverges from production, I'll flag back the same way Contracts 1
and 2 did — no silent adjustment.

After spec approval, the implementation series ships per §6 with
push + email at each commit boundary. Adjustment B verification
test in Commit 3 mirrors Contract 2's pattern exactly.
