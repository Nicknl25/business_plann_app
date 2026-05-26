# P3.40 Contract 5b — OperatingModelJsonContract (Spec)

**Status:** Specification only. No code lands until Nick reviews
this doc. After review, implementation follows the commit
sequence in §6 below.

**Scope:** Sub-contract retrofit for
``IntakeDraftContract.operating_model_json`` (currently
``Dict[str, Any]`` per Contract 5 F0 (b)). Tightens the field
type to a 4-sub-contract typed shape matching the OpenAI-schema-
enforced payload produced by ``consultant_finalize`` at
[intake_consultant.py:583-684](../../python/client_intake_and_finmo/intake_consultant.py#L583).

**Parent contract:** Contract 5 — IntakeDraftContract (landed
end-to-end). The existing consumer-side gate at
[runner.py:189](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L189)
validates the full draft payload; retrofitting the field type
automatically tightens that gate. No new gate site; no new
diagnostic codes.

**Companion trace doc:** [p3_40_contract_5b_operating_model_json_trace.md](p3_40_contract_5b_operating_model_json_trace.md)
(landed at 68caecc, 564 LOC, 5 trace tasks + 8 candidate flags
+ 6 R-residuals).

---

## 0. Value-constraint policy (LOAD-BEARING)

**The contract types JSON SHAPE, not VALUES.** Per the Contract
5b directive (overriding any PSL guidance from prior addenda):

| OpenAI schema says       | Contract types as              |
|--------------------------|--------------------------------|
| ``string``               | ``str``                        |
| ``string`` with ``enum`` | ``str`` (NOT ``Literal[...]``) |
| ``array``                | ``List[Any]``                  |
| ``object``               | ``Dict[str, Any]`` (or typed sub-contract if T5 sub-shape) |
| ``integer``              | ``int``                        |
| ``number``               | ``float``                      |
| ``boolean``              | ``bool``                       |

**Exceptions** (these stay enforced):
- Field PRESENCE — required-vs-Optional per the schema's
  ``required[]`` list, modulated by production-reality per PSL2
  applied to required-vs-Optional.
- Nested object STRUCTURE — schema-defined nested objects
  (``LobModelContract``, ``ProductContract``,
  ``MilestoneContract`` per T5) become typed sub-contracts;
  policy applies recursively.
- ``extra="ignore"`` on every sub-contract per F4.

**BANNED constructs anywhere in Contract 5b**:
- ``Field(min_length=...)``, ``Field(max_length=...)``,
  ``Field(pattern=...)``
- ``Field(ge=...)``, ``Field(le=...)``, ``Field(gt=...)``,
  ``Field(lt=...)``
- ``Literal[...]`` for enum values
- ``@model_validator(mode="after")`` with cross-field
  business-logic checks
- ``@field_validator`` with content checks beyond JSON-type
  correctness
- ``confloat`` / ``conint`` / ``constr`` with constraints
- Custom validators inspecting string content, numeric ranges,
  or list contents

**Rationale.** operating_model_json comes from intake. Intake
data varies STRUCTURALLY by business type — a coffee shop
produces different content than a SaaS company. Any content
constraint creates false-positive ContractViolations for
business types where the value legitimately doesn't fit. The
OpenAI schema enforces value-level rules upstream via strict
mode; Pydantic re-enforcing duplicates work AND introduces
drift risk if the schema evolves. Contract 5b's value is
structural typing — catches post-processing bugs, schema-
version drift, legacy-data shape changes — NOT business-logic
enforcement.

This policy applies to **Contracts 5b + 5c + 5d** uniformly.

---

## 1. Trace findings synthesis

Per the trace doc T1-T5 + the value-constraint policy in §0,
the contract structure simplifies vs the trace's preliminary
recommendations. The recap:

- **T1** — OpenAI schema source: [intake_consultant.py:67-182](../../python/client_intake_and_finmo/intake_consultant.py#L67)
  ``_final_schema()``. Strict ``additionalProperties: false``.
- **T2** — 23 required top-level schema fields + 3 nested object
  types (LobModelContract / ProductContract /
  MilestoneContract). Per §0: enum vocabularies do NOT
  translate to ``Literal`` — types as bare ``str``.
- **T3** — 4 production extras NOT in schema
  (``business_naics_6``, ``competitive_advantage``,
  ``business_type_candidates``,
  ``business_type_candidates_locked``); 2 legacy fallback fields
  (``naics_code``, ``business_naics``) read defensively in
  runner.py. Per F1/F2 below: type the 4 extras as Optional
  fields; ignore the legacy 2 via ``extra="ignore"`` + R-a
  cleanup.
- **T4** — Downstream consumers read field-by-field at ~13
  runner.py sites + ~6 post_intake_mapping prompt-context
  declarations. Retrofit is non-breaking (typed sub-contract
  is a subset of ``Dict[str, Any]``).
- **T5** — 4-sub-contract structure in a single module per
  the F0 multi-shape pattern (Contracts 6 + 7 precedent).

---

## 2. OpenAI schema → Pydantic translation table

Per the §0 policy. Field-by-field. ``Optional[X] = None``
default for nullable-typed schema fields per PSL2 applied to
required-vs-Optional (legacy-draft safety — see F7).

### 2.1 Top-level OperatingModelJsonContract (23 schema + 4 production extras = 27 fields)

| # | Field | Pydantic type | Required-shape | Source |
|---|---|---|---|---|
| **GPT schema fields (23 required per intake_consultant.py:156-180)** | | | | |
| 1 | ``consumer_type`` | ``str`` | required | schema enum -> bare str per §0 |
| 2 | ``business_type`` | ``str`` | required | |
| 3 | ``business_stage`` | ``Optional[str] = None`` | nullable-required (schema) | ``["string", "null"]`` |
| 4 | ``business_description_summary`` | ``str`` | required | |
| 5 | ``lob_models`` | ``Optional[List[LobModelContract]] = None`` | nullable-required (schema) | ``["array", "null"]`` of objects |
| 6 | ``unit_name`` | ``Optional[str] = None`` | nullable-required | ``["string", "null"]`` |
| 7 | ``unit_description`` | ``Optional[str] = None`` | nullable-required | ``["string", "null"]`` |
| 8 | ``unit_cadence`` | ``Optional[str] = None`` | nullable-required; enum -> bare str per §0 | ``["string", "null"]`` |
| 9 | ``units_per_week_capacity`` | ``Optional[float] = None`` | nullable-required | ``["number", "null"]`` |
| 10 | ``units_per_period_capacity`` | ``Optional[float] = None`` | nullable-required | ``["number", "null"]`` |
| 11 | ``operating_periods_per_year`` | ``Optional[float] = None`` | nullable-required | ``["number", "null"]`` |
| 12 | ``utilization_rate`` | ``Optional[float] = None`` | nullable-required | ``["number", "null"]`` |
| 13 | ``unit_price`` | ``Optional[float] = None`` | nullable-required | ``["number", "null"]`` |
| 14 | ``shipping_method`` | ``str`` | required | |
| 15 | ``sales_modality`` | ``str`` | required; enum -> bare str per §0 | |
| 16 | ``geographic_scope`` | ``str`` | required; enum -> bare str per §0 | |
| 17 | ``geographic_coverage`` | ``str`` | required | |
| 18 | ``countries`` | ``List[Any]`` | required; item-type pinning BANNED per §0 | ``array of string`` |
| 19 | ``milestones`` | ``List[MilestoneContract]`` | required; minItems=1 NOT enforced per §0 | ``array of object`` |
| 20 | ``capacity_driver`` | ``str`` | required; enum -> bare str per §0 | |
| 21 | ``primary_growth_lever`` | ``str`` | required | |
| 22 | ``legal_entity`` | ``str`` | required | |
| 23 | ``confidence`` | ``float`` | required; numeric range NOT enforced per §0 | |
| **Production extras (4, per T3, NOT in OpenAI schema)** | | | | |
| 24 | ``business_naics_6`` | ``Optional[str] = None`` | conditional per T3 | added by ``_ensure_ops_business_naics`` |
| 25 | ``competitive_advantage`` | ``Optional[str] = None`` | conditional per T3 | added at intake_consult.py:8568 |
| 26 | ``business_type_candidates`` | ``Optional[List[Any]] = None`` | conditional per T3 | added at intake_consult.py:8479 |
| 27 | ``business_type_candidates_locked`` | ``Optional[bool] = None`` | conditional per T3 | added at intake_consult.py:8480 |

**Field count math:** 13 non-nullable-required schema fields +
10 nullable-required schema fields + 4 conditional production
extras = 27 typed fields. ``extra="ignore"`` accepts any
additional fields silently (per F4 + safety for the 2 legacy
fallback reads in F2).

### 2.2 LobModelContract (2 fields per intake_consultant.py:84-119)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``lob_name`` | ``str`` | required |
| 2 | ``products`` | ``List[ProductContract]`` | required; minItems=1 NOT enforced per §0 |

### 2.3 ProductContract (9 fields per intake_consultant.py:91-115)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``product_name`` | ``str`` | required |
| 2 | ``unit_name`` | ``str`` | required |
| 3 | ``unit_description`` | ``str`` | required |
| 4 | ``unit_cadence`` | ``str`` | required; enum -> bare str per §0 |
| 5 | ``units_per_week_capacity`` | ``float`` | required |
| 6 | ``units_per_period_capacity`` | ``float`` | required |
| 7 | ``operating_periods_per_year`` | ``Optional[float] = None`` | nullable-required |
| 8 | ``utilization_rate`` | ``Optional[float] = None`` | nullable-required |
| 9 | ``unit_price`` | ``float`` | required (per §0 NOT ``gt=0`` even though system prompt says non-zero) |

### 2.4 MilestoneContract (2 fields per intake_consultant.py:141-148)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``description`` | ``str`` | required |
| 2 | ``timing`` | ``str`` | required |

---

## 3. Field-by-field contract spec

Per §0 policy, the module is small. 4 sub-contracts in one
module file:
``python/client_intake_and_finmo/post_intake_contracts/operating_model_json_contract.py``.

### 3.1 Module imports + constants

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


#: Stage label used if a future direct gate site needs it.
#: Per F3: sub-contract is invoked through Contract 5's
#: existing INTAKE_DRAFT_CONTRACT diagnostic stack -- no
#: separate label required at the diagnostic layer.
OPERATING_MODEL_JSON_STAGE_LABEL = "INTAKE_DRAFT::operating_model_json"
```

No enum tuples (no ``Literal[...]`` per §0 means no exported
vocabularies to pin). No invariant constants (no
``@model_validator`` per §0).

### 3.2 Sub-sub-contracts (define in dependency order)

```python
class ProductContract(BaseModel):
  """One product entry inside a LOB. 9 fields per
  intake_consultant.py:91-115."""
  product_name: str
  unit_name: str
  unit_description: str
  unit_cadence: str  # schema enum NOT pinned per §0
  units_per_week_capacity: float
  units_per_period_capacity: float
  operating_periods_per_year: Optional[float] = None
  utilization_rate: Optional[float] = None
  unit_price: float

  model_config = ConfigDict(extra="ignore")


class LobModelContract(BaseModel):
  """One line-of-business entry. 2 fields per
  intake_consultant.py:84-119."""
  lob_name: str
  products: List[ProductContract]  # minItems=1 NOT enforced per §0

  model_config = ConfigDict(extra="ignore")


class MilestoneContract(BaseModel):
  """One operational milestone. 2 fields per
  intake_consultant.py:141-148."""
  description: str
  timing: str

  model_config = ConfigDict(extra="ignore")
```

### 3.3 Top-level OperatingModelJsonContract

```python
class OperatingModelJsonContract(BaseModel):
  """Operating-model intake payload per intake_consultant.py
  _final_schema(). 23 required GPT-schema fields + 4
  production extras (T3) = 27 typed fields. extra='ignore'
  per F4 accepts the 2 legacy fallback fields (naics_code,
  business_naics) per F2 + tolerates future schema-version
  drift.
  """
  # --- GPT schema: 13 non-nullable required ---
  consumer_type: str
  business_type: str
  business_description_summary: str
  shipping_method: str
  sales_modality: str
  geographic_scope: str
  geographic_coverage: str
  countries: List[Any]            # item type NOT pinned per §0
  milestones: List[MilestoneContract]  # minItems=1 NOT enforced per §0
  capacity_driver: str
  primary_growth_lever: str
  legal_entity: str
  confidence: float

  # --- GPT schema: 10 nullable-required (typed Optional=None per F7) ---
  business_stage: Optional[str] = None
  lob_models: Optional[List[LobModelContract]] = None
  unit_name: Optional[str] = None
  unit_description: Optional[str] = None
  unit_cadence: Optional[str] = None
  units_per_week_capacity: Optional[float] = None
  units_per_period_capacity: Optional[float] = None
  operating_periods_per_year: Optional[float] = None
  utilization_rate: Optional[float] = None
  unit_price: Optional[float] = None

  # --- Production extras (T3, conditional per intake flow) ---
  business_naics_6: Optional[str] = None
  competitive_advantage: Optional[str] = None
  business_type_candidates: Optional[List[Any]] = None
  business_type_candidates_locked: Optional[bool] = None

  model_config = ConfigDict(extra="ignore")
```

### 3.4 Public re-exports

```python
__all__ = [
  "OPERATING_MODEL_JSON_STAGE_LABEL",
  "ProductContract",
  "LobModelContract",
  "MilestoneContract",
  "OperatingModelJsonContract",
]
```

### 3.5 Expected module LOC

200-350 LOC including module docstring + 4 sub-contracts + 4
docstrings + constants + imports. Significantly smaller than
Contracts 6 + 7 modules because §0 policy eliminates ~80% of
typical Pydantic boilerplate (no Field constraints, no
validators, no Literal vocabularies).

---

## 4. Cross-field invariants

**None.**

Per §0 value-constraint policy: content-level checks are out
of scope for sub-contract retrofits. No
``@model_validator(mode="after")``. No ``@field_validator``
beyond JSON-type-correctness. No cross-field business-logic
enforcement.

Examples of invariants that would TYPICALLY be encoded for a
boundary contract but are EXPLICITLY OUT OF SCOPE here:
- ``unit_price > 0`` (per intake_consultant.py:622 system
  prompt) — REJECTED per §0 (Field range constraint banned).
- ``utilization_rate ∈ [0, 1]`` (per system prompt's "decimal
  fraction" guidance) — REJECTED per §0 (Field range constraint
  banned).
- Multi-LOB consistency: when ``lob_models`` has >1 entry,
  top-level ``unit_*`` fields MUST be None — REJECTED per §0
  (cross-field validator banned; the OpenAI schema + system
  prompt enforce this upstream).
- ``milestones`` non-empty (schema ``minItems: 1``) — REJECTED
  per §0 (Field(min_length=1) banned).

These rules ARE production reality; they're enforced UPSTREAM
by OpenAI's strict schema + the system prompt. Contract 5b
doesn't duplicate.

---

## 5. Retrofit plan

### 5.1 Single-line field-type change

[intake_draft_contract.py:174](../../python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py#L174):

```python
# Before:
operating_model_json: Dict[str, Any]

# After:
operating_model_json: OperatingModelJsonContract
```

Plus import at the top of the module:

```python
from client_intake_and_finmo.post_intake_contracts.operating_model_json_contract import (
  OperatingModelJsonContract,
)
```

No other changes to ``IntakeDraftContract`` structure or
field roster.

### 5.2 Contract 5 fixture impact

[tests/_p3_40_contract_5_fixtures.py:50-53](../../tests/_p3_40_contract_5_fixtures.py#L50)
currently emits a 2-field minimal stub for
``operating_model_json``:

```python
"operating_model_json": {
  "business_naics_6": "722515",
  "business_stage": "growth",
},
```

After retrofit, this stub no longer validates (missing the 13
non-nullable required schema fields). The fixture either:
- (a) gets replaced with a fully-shaped
  ``valid_operating_model_json_dict()`` helper imported from
  the new ``_p3_40_contract_5b_fixtures.py`` module, OR
- (b) uses ``model_dump()`` from a valid OperatingModelJsonContract
  instance built via the 5b fixture, OR
- (c) the existing 2-field stub gets COMPLETELY rebuilt to the
  full 13-required-field minimum.

Spec recommends (a) for clarity + DRY across 5 + 5b suites.
See §6 Commit 5b-2 + 5b-3.

### 5.3 Contract 5 test impact

[tests/test_p3_40_contract_5_subcontracts.py](../../tests/test_p3_40_contract_5_subcontracts.py)
and
[tests/test_p3_40_contract_5_intake_draft.py](../../tests/test_p3_40_contract_5_intake_draft.py)
exercise IntakeDraftContract end-to-end. After retrofit:
- Tests that constructed ad-hoc ``operating_model_json={"foo":
  "bar"}`` will fail because the contract now requires the 13
  schema fields. Replace with calls to the 5b fixture builder.
- Tests that explicitly test ``operating_model_json``
  arbitrariness (if any) become 5b-suite tests instead — the
  field's permissive-dict semantic is gone.
- Tests that exercise other fields (target_market_json,
  people_json, etc.) — unchanged.

Estimate: ~3-6 Contract 5 tests need fixture updates. Lands in
Commit 5b-3.

### 5.4 No new gate site

Per the retrofit nature: Contract 5's existing consumer-side
gate at runner.py:189 calls
``validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)``.
After 5b retrofit, that gate AUTOMATICALLY tightens because
``IntakeDraftContract.model_validate`` now recursively validates
``operating_model_json`` against the new sub-contract.

**No changes to enforcement.py, phase_codes.py, fail_fast_codes.py,
or any wiring sites.** No new tests for "Contract 5b consumer
gate" — the existing
``test_p3_40_contract_5_consumer_gate.py`` invariants cover it
once the fixtures shift to validly-shaped operating_model_json.

### 5.5 Downstream consumer impact (none expected)

Per trace T4: downstream consumers (runner.py + post_intake_
mapping.py) read operating_model_json field-by-field via
``ops_json.get("field")`` — duck-typed dict access. After
retrofit:
- Pydantic returns ``OperatingModelJsonContract`` instances;
  Contract 5's existing gate calls ``model_validate`` but
  Contract 5's downstream code reads from the raw dict at
  runner.py:235 (``ops_json = parse_json_dict(draft.get(...))``).
- The gate validates ``IntakeDraftContract`` then discards the
  validated instance — the parsed dict continues downstream
  unchanged.
- So downstream consumers see the same Dict[str, Any] they see
  today.

R-residual R-g (future): downstream consumers could be
upgraded to consume the typed ``OperatingModelJsonContract``
instance directly (rather than re-parsing the dict). Out of
scope for 5b.

---

## 6. Implementation sequence

Per the directive: 3 commits.

### Commit 5b-1 — Sub-contract module + fixtures

Files added:
- ``python/client_intake_and_finmo/post_intake_contracts/operating_model_json_contract.py``
  (200-350 LOC; 4 sub-contracts per §3)
- ``tests/_p3_40_contract_5b_fixtures.py`` (~120 LOC)

Fixtures provide minimal-valid builders:
- ``valid_product_dict(unit_cadence="weekly", ...)`` → ProductContract-shaped dict
- ``valid_lob_model_dict(lob_name="Default LOB", ...)`` → LobModelContract-shaped dict (1 product by default)
- ``valid_milestone_dict(description="Open second location", timing="2027 Q1")`` → MilestoneContract-shaped dict
- ``valid_operating_model_json_dict(include_lob_models=False, include_milestones=True, **overrides)`` → full OperatingModelJsonContract-shaped dict (single-LOB top-level convenience case by default; toggles for multi-LOB / empty-milestones edge cases)

**Pre-step:** re-verify the 23-field required list at
intake_consultant.py:156-180 + the 4 production-extra write sites
per T3 (a) + the schema nullability per ``["X", "null"]`` typed
fields before Commit 5b-1 lands (Contracts 4-7 pre-1a re-
verification discipline). If anything diverges, flag back.

### Commit 5b-2 — Sub-contract tests

File added:
- ``tests/test_p3_40_contract_5b_operating_model_json.py``
  (~250-300 LOC; 4 test classes)

Test classes (~15-20 tests):
- ``ProductContractTest`` (~4): valid; missing required field
  rejected; bare-str unit_cadence accepted (including non-
  schema values like "biennial" — per §0 enum-not-pinned);
  Optional fields default None.
- ``LobModelContractTest`` (~3): valid; products list accepts
  empty (per §0 minItems=1 NOT enforced); missing lob_name
  rejected.
- ``MilestoneContractTest`` (~2): valid; missing required
  field rejected.
- ``OperatingModelJsonContractTest`` (~7-9):
  - valid minimal payload accepted (13 non-nullable required +
    defaults).
  - Each of the 10 nullable-required fields accepts None.
  - Each of the 4 production extras accepts absent.
  - Bare-string enum values accepted including non-vocabulary
    (e.g., ``consumer_type="franchise"``).
  - countries accepts mixed types (e.g., ``[None, 1, "US"]``)
    per List[Any].
  - Empty ``milestones=[]`` accepted (per §0).
  - ``extra="ignore"`` accepts unknown keys (covers the
    runner.py legacy fallback reads per F2).
  - Numeric fields accept ``int`` value where ``float`` typed
    (Pydantic int-to-float coercion default).

**No tests for**:
- Literal narrowing (no Literals to test).
- Range constraints (no ranges to test).
- Cross-field invariants (none exist per §4).
- @model_validator behavior (none exist).

### Commit 5b-3 — Retrofit + Contract 5 fixture / test alignment

Files modified:
- ``python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py``
  (single-line field type change + import per §5.1).
- ``tests/_p3_40_contract_5_fixtures.py``
  (replace the 2-field stub with a call to 5b's
  ``valid_operating_model_json_dict()``).
- ``tests/test_p3_40_contract_5_subcontracts.py`` (any tests
  that construct ad-hoc operating_model_json values; update to
  use 5b fixtures or expect rejection on the now-invalid
  stubs).
- ``tests/test_p3_40_contract_5_intake_draft.py``
  (top-level Contract 5 tests using operating_model_json).
- ``tests/test_p3_40_contract_5_consumer_gate.py`` (existing
  consumer-gate tests; fixtures alignment).

Full-suite verification after 5b-3:
- All Contract 5 tests pass with retrofitted contract.
- All new Contract 5b tests pass.
- Contracts 1-7 cross-suite green (P3.40 suite total expected
  ~565-580 passed after 5b lands).

---

## 7. Open flags for Nick's review

8 flags. Dispositions reflect §0 value-constraint policy.

### F0 — Sub-contract granularity

**(Recommended) (a) 4 sub-contracts in single module**
(``OperatingModelJsonContract`` +
``LobModelContract`` + ``ProductContract`` +
``MilestoneContract``). Matches F0 multi-shape pattern from
Contracts 6 + 7. PSL3 confirmed.

**(b) Flat single OperatingModelJsonContract with all nested
shapes as ``Dict[str, Any]``.** Rejected — loses the structural
typing value for the nested 9-field ProductContract; trivially
small additional cost per §0 policy (no validators to write).

### F1 — Persisted-extras disposition (4 production extras per T3)

**(Recommended) (a) Type the 4 extras as Optional fields
explicitly + ``extra="ignore"``.** Per the "type what production
produces" precedent from Contracts 2-7. Discoverability win for
future maintainers reading the contract.

**(b) Skip the 4 extras and rely on ``extra="ignore"`` alone.**
Rejected — opaque to future readers; production knowledge stays
buried in intake_consult.py.

### F2 — Legacy fallback fields (``naics_code``, ``business_naics``)

**(Recommended) (a) ``extra="ignore"`` only (no contract
fields) + R-residual R-a to audit DB and clean up runner.py
defensive reads.** Safe first cut; aligns with §0 (don't type
fields not in the schema).

**(b) Add as Optional contract fields.** Rejected — no evidence
they're in any production payload; would clutter the contract
with hypothetical fields. R-a covers the audit + cleanup.

### F3 — Stage label naming

**(Recommended) (a) ``OPERATING_MODEL_JSON_STAGE_LABEL =
"INTAKE_DRAFT::operating_model_json"``.** Sub-contract is
invoked through Contract 5's existing INTAKE_DRAFT_CONTRACT
diagnostic stack per PSL5 (no new gate). Label only surfaces
if a future direct gate site is added.

**(b) No label exported.** Rejected — establishes a discoverable
identifier for a future direct gate (PSL5-future-proof).

### F4 — ``extra`` policy on all 4 sub-contracts

**(Recommended) (a) ``extra="ignore"`` on every sub-contract**
(top-level OperatingModelJsonContract + LobModelContract +
ProductContract + MilestoneContract). PSL4 + §0 policy.

**(b) ``extra="forbid"`` on top-level (mirror boundary contract
precedent).** Rejected — operating_model_json is a sub-contract
of IntakeDraftContract (where top-level forbid lives at the
draft level, per Contract 5 F6). Sub-contracts at this layer
should tolerate schema-version drift.

### F5 — Value-level constraints (unit_price > 0, utilization_rate ∈ [0,1], etc.)

**(Recommended) (a) ALL value-level constraints REJECTED per §0
value-constraint policy.** No ``Field(gt=0)``, no
``Field(ge=0, le=1)``, no Literal pinning, no model_validators.
The OpenAI schema + system prompt enforce upstream; Contract 5b
doesn't duplicate.

**(b) Selectively pin a small subset (e.g., unit_price > 0,
utilization_rate ∈ [0, 1]) since the system prompt explicitly
specifies them.** Rejected per §0 — content-level checks
banned. Business-type variation may produce legitimately
unusual values; constraints fire false-positive
ContractViolations.

### F6 — Composition with Contract 5's fixtures

**(Recommended) (a) Add ``valid_operating_model_json_dict()``
builder in new ``_p3_40_contract_5b_fixtures.py``; Contract 5's
fixtures import it.** DRY + clear ownership.

**(b) Inline a full 27-field stub in Contract 5's fixtures.**
Rejected — duplicates 5b's builder; drift risk across two
fixture files.

### F7 — Required-vs-Optional disposition for the 10 nullable-required schema fields

The OpenAI schema marks 10 fields as ``["X", "null"]`` + ``in
required[]``: strict mode guarantees KEY presence with possibly-
null value.

**(Recommended) (a) Type as ``Optional[X] = None`` (key-
optional + value-nullable).** Safer for legacy drafts that may
pre-date the current schema and omit keys entirely. Matches the
``Optional[X] = None`` Pydantic semantic for "may or may not be
present, may be null when present."

**(b) Type as ``Optional[X]`` (no default — required key,
value-nullable).** Tighter; matches OpenAI strict-mode semantic
exactly. Rejected for first cut — exposes legacy-draft risk
without a DB audit first. R-h R-residual to tighten once an
audit confirms no legacy drafts omit these keys.

Expected total: 8 flags. None require ``Literal`` /
``Field(constraint)`` / validators per §0.

---

## 8. Known residual cleanups (out of scope for Contract 5b)

- **R-a.** ~~DB audit for ``naics_code`` + ``business_naics``
  legacy fields per T3 (b). If zero hits in production drafts,
  delete the defensive fallbacks in runner.py:284-285 +
  1093-1094.~~ **ASSESSED in P3.40 Contract Layer Cleanup
  Commit 3/6; FALLBACKS KEPT for legacy DB support.**
  Reader/writer audit confirmed ZERO current code writes
  ``naics_code`` or ``business_naics`` to ``ops_json``.
  However, legacy production drafts pre-dating the current
  OperatingModelJsonContract schema MAY carry these keys
  (DB audit out of scope for the cleanup commit). Per PSL2
  production-reality-wins + conservative engineering: removing
  the fallback chain would silently lose NAICS resolution on
  any legacy draft that still uses the old keys. Contract 5b's
  ``extra="ignore"`` lets such drafts pass the gate; the
  fallback chain at runner.py:283-287 + 1093-1110 is the
  actual consumer that uses them. KEPT with explicit
  ASSESSED+KEPT comments at both sites. A future DB audit
  (separate work item, not in cleanup scope) could confirm
  zero legacy data exposure and warrant removal.

- **R-b.** ``confidence`` field range — schema is unbounded
  ``number``. Per §0 no range constraint. If production audit
  reveals a sane bounded range, document as a comment in the
  contract; do NOT enforce.

- **R-c.** ``unit_cadence`` enum mismatch between top-level
  schema (``["weekly", "monthly", "contract", None]`` per
  intake_consultant.py:124) vs nested ProductContract (no
  None). Per §0 NOT enforced as Literal — the mismatch is moot.
  Document for clarity.

- **R-d.** ``competitive_advantage`` production extra trigger
  condition (``comp_action == "confirm_proceed"`` per T3 (a)).
  Document for future maintainers; contract treats as Optional.

- **R-e.** ``_apply_model_ops_patch`` allowed_keys whitelist at
  intake_consult.py:917-937 excludes 6 of the 23 schema fields
  (business_stage, business_description_summary, milestones,
  confidence, etc.). Align whitelist with the typed contract
  roster post-landing.

- **R-f.** Contract 3 ``fact_template`` field-path declarations
  at post_intake_mapping.py:1825-1827 reference
  ``operating_model_json.business_type`` paths. Once 5b lands,
  harmonize against the typed contract roster.

- **R-g.** Upgrade downstream consumers (runner.py +
  post_intake_mapping.py) to read from the typed
  OperatingModelJsonContract instance rather than re-parsing
  the dict at runner.py:235. Yields end-to-end typed plumbing.

- **R-h.** Tighten ``Optional[X] = None`` to ``Optional[X]``
  (required key, value-nullable) for the 10 nullable-required
  schema fields once a DB audit confirms no legacy drafts omit
  these keys (per F7 (b) deferred).

- **R-i.** Unblocked downstream R-residuals:
  - Contract 6 R16 (industry baseline business-facts typing).
  - Contract 7 R9 (Mirror.business_facts compose Contracts
    5b/c/d).
  Both become actionable once 5b + 5c + 5d all land.

---

## 9. Workflow

Same as Contracts 1-7: trace + spec each ship as single
commits, held for Nick review.

**Trace shipped at 68caecc.** This is the spec doc.

After spec approval, implementation lands per §6 (3 commits:
5b-1 module + fixtures, 5b-2 sub-contract tests, 5b-3 retrofit
+ Contract 5 alignment). Push + email per commit per the
standard pattern.

Pre-1a re-verification per Contracts 4-7 discipline (re-grep
schema source + production extras + nullability before Commit
5b-1 lands).

After 5b lands, proceed to 5c (target_market_json) and 5d
(people_json) — same value-constraint policy (§0) applies. Once
all three land, Contract 6 R16 + Contract 7 R9 become
actionable.

If during Commit 5b-1 anything diverges from production, flag
back the same way Contracts 1-7 did — no silent adjustment.

Expected full-suite total after 5b-3:
~545 (today) + ~15-20 (5b-2) = ~560-565 passed.
