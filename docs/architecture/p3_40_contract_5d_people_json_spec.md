# P3.40 Contract 5d — PeopleJsonContract (Spec)

**Status:** Specification only. No code lands until Nick reviews
this doc. After review, implementation follows the commit
sequence in §6 below.

**Scope:** Sub-contract retrofit for
``IntakeDraftContract.people_json`` (currently
``Dict[str, Any]`` per Contract 5 F0 (b)). Tightens the field
type to a 3-sub-contract typed shape matching the OpenAI-
schema-enforced payload produced by
``people_capability_finalize`` (per
[people_capability_consultant.py:80-147](../../python/client_intake_and_finmo/people_capability_consultant.py#L80)).

**Parent contract:** Contract 5 — IntakeDraftContract (landed
end-to-end). Contract 5b retrofit landed at fc91083; Contract
5c retrofit landed at 8942527. **Contract 5d is the FINAL
sub-contract retrofit in the 5b/5c/5d series.** Suite at 602
passing post-5c; expected ~620-625 post-5d.

**Companion trace doc:** [p3_40_contract_5d_people_json_trace.md](p3_40_contract_5d_people_json_trace.md)
(landed at 0761191, 576 LOC, 5 trace tasks + 9 candidate flags
+ 9 R-residuals).

**Unblocks downstream R-residuals (the milestone):**
- Contract 6 R16 (industry baseline business-facts typing).
- Contract 7 R9 (Mirror.business_facts compose Contracts
  5b/c/d).
Both become actionable **immediately after Commit 5d-3 lands.**

---

## 0. Value-constraint policy (LOAD-BEARING)

**The contract types JSON SHAPE, not VALUES.** Held verbatim
from Contracts 5b + 5c spec §0 (applies uniformly to 5b + 5c +
5d).

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
  ``required[]`` list, modulated by PSL2 production-reality-
  wins (5d's key_people_summary case is the strongest PSL2
  application in the series — see F1).
- Nested object STRUCTURE — schema-defined nested objects
  (``PersonContract``, ``InferredRoleContract`` per T5) become
  typed sub-contracts.
- ``extra="ignore"`` on every sub-contract per F4.

**BANNED constructs** (verbatim from 5b/5c spec §0):
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

**Rationale.** Same as 5b/5c: people data varies STRUCTURALLY
by business type (a sole proprietor's people array differs
from a 50-person franchise's; an early-stage business has
different inferred_roles than an operating one). Content
constraints fire false-positive ContractViolations. OpenAI
strict mode enforces value-level rules upstream; Pydantic
re-enforcing duplicates work AND introduces drift risk.

---

## 1. Trace findings synthesis

Per the trace doc T1-T5 + the §0 policy:

- **T1** — OpenAI schema source:
  [people_capability_consultant.py:80-147](../../python/client_intake_and_finmo/people_capability_consultant.py#L80)
  ``_final_schema()``. Strict ``additionalProperties: false``.
  Companion ``_progress_schema()`` at :150-184 for in-memory
  collection-progress tracking (NOT persisted).
- **T2** — 6 required top-level schema fields + 2 nested
  object types + **ZERO enum vocabularies** (simpler than
  5b/5c). minItems=1 schema constraints on people +
  inferred_roles REJECTED per §0.
- **T3 CRITICAL** — ``key_people_summary`` is schema-required
  but POPPED before persistence at intake_consult.py:6241. Per
  PSL2 (production-reality-wins): type as ``Optional[str] =
  None`` despite schema-required. This is the load-bearing
  PSL2 case of the 5b/5c/5d series. Plus: business_naics_6
  cross-flow from ops_json (IS in schema), inferred_roles_summary
  post-process generated (IS in schema), and LEGACY fallback
  person-item fields (``role``/``name``/``months_until_hire``)
  defensively read at post_intake_headcount/schedule.py.
- **T4** — runner.py + post_intake_mapping read full blob;
  post_intake_headcount/schedule.py reads field-by-field for
  staffing rows + payroll derivation (critical coupling);
  financials.py + people_roles.py wage enrichment.
- **T5** — 3-sub-contract structure in a single module per F0.

---

## 2. OpenAI schema → Pydantic translation table

Per §0. Field-by-field. ``Optional[X] = None`` default for
nullable-typed schema fields per F7 + the production-popped
``key_people_summary`` field per F1.

### 2.1 Top-level PeopleJsonContract (6 typed fields)

| # | Field | Pydantic type | Required-shape | Source |
|---|---|---|---|---|
| **Always-present per persistence reality (4)** | | | | |
| 1 | ``people`` | ``List[PersonContract]`` | required; minItems=1 NOT enforced per §0 | schema array |
| 2 | ``inferred_roles`` | ``List[InferredRoleContract]`` | required; minItems=1 NOT enforced per §0 | schema array |
| 3 | ``inferred_roles_summary`` | ``str`` | required | Post-process generated at intake_consult.py:6231 via format_roles_summary; fallback "" at :6235-6236 |
| 4 | ``confidence`` | ``float`` | required; numeric range NOT enforced per §0 | |
| **Nullable-required schema field (1)** | | | | |
| 5 | ``business_naics_6`` | ``Optional[str] = None`` | nullable-required per schema; Optional per F7 legacy safety | Cross-flow from ops_json at intake_consult.py:6228 |
| **Schema-required-but-production-popped (1, F1)** | | | | |
| 6 | ``key_people_summary`` | ``Optional[str] = None`` | schema-required; POPPED at intake_consult.py:6241; Optional per PSL2 / F1 | T3 critical finding |

**Field count math:** 4 always-present + 1 nullable-required +
1 production-popped = 6 typed fields. ``extra="ignore"``
accepts any additional fields silently (per F4 + future
schema-version drift safety).

### 2.2 PersonContract (9 fields per people_capability_consultant.py:94-114)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``full_name`` | ``str`` | required |
| 2 | ``role_title`` | ``str`` | required |
| 3 | ``primary_responsibilities`` | ``str`` | required |
| 4 | ``relevant_background`` | ``str`` | required |
| 5 | ``experience_years`` | ``str`` | required; schema says STRING (free-form like "8 years"), bare str per §0 / F8 |
| 6 | ``why_strengthens_business`` | ``str`` | required |
| 7 | ``paragraph`` | ``str`` | required |
| 8 | ``annual_wage`` | ``Optional[float] = None`` | nullable-required |
| 9 | ``wage_source`` | ``str`` | required; vocabulary client_override/gpt_estimate/unknown documented at consultant.py:218-221 NOT pinned per §0 / F9 |

### 2.3 InferredRoleContract (5 fields per people_capability_consultant.py:124-131)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``role_title`` | ``str`` | required |
| 2 | ``annual_wage`` | ``Optional[float] = None`` | nullable-required |
| 3 | ``wage_source`` | ``str`` | required |
| 4 | ``months_until_hire`` | ``Optional[float] = None`` | nullable-required |
| 5 | ``notes`` | ``str`` | required |

---

## 3. Field-by-field contract spec

Per §0 policy. 3 sub-contracts in one module file:
``python/client_intake_and_finmo/post_intake_contracts/people_json_contract.py``.

### 3.1 Module imports + constants

```python
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


#: Stage label exported for discoverability per spec §3.1. Sub-
#: contract is invoked through Contract 5's existing
#: INTAKE_DRAFT_STAGE_LABEL diagnostic stack; this label only
#: surfaces if a future direct gate site is added (PSL5
#: future-proof, 5b/5c precedent).
PEOPLE_JSON_STAGE_LABEL = "INTAKE_DRAFT::people_json"
```

No enum tuples (no Literal[...] per §0; no enums in the schema
anyway -- simplest of the 5b/5c/5d trio).

### 3.2 Sub-sub-contracts (define in dependency order)

```python
class PersonContract(BaseModel):
  """One key-person entry. 9 fields per
  people_capability_consultant.py:94-114.

  Per §0 policy: experience_years types as bare ``str`` per F8
  (schema says STRING -- free-form like "8 years" or "10+ years",
  NOT a number). wage_source vocabulary (client_override /
  gpt_estimate / unknown) is documented at consultant.py:218-221
  but NOT in the schema enum; type as bare ``str`` per F9.

  extra='ignore' per F2 + F4: accepts the legacy fallback
  person-item fields (role / name / months_until_hire) that
  post_intake_headcount/schedule.py:693-706 defensively reads.
  R-b R-residual covers cleaning up those downstream reads.
  """
  full_name: str
  role_title: str
  primary_responsibilities: str
  relevant_background: str
  experience_years: str
  why_strengthens_business: str
  paragraph: str
  annual_wage: Optional[float] = None
  wage_source: str

  model_config = ConfigDict(extra="ignore")


class InferredRoleContract(BaseModel):
  """One inferred-role entry. 5 fields per
  people_capability_consultant.py:124-131.

  ``months_until_hire`` correctly belongs here (per the
  schema), NOT on PersonContract -- the downstream
  post_intake_headcount/schedule.py:702-706 defensive read
  of months_until_hire from people-items is the legacy
  fallback (R-b cleanup target).
  """
  role_title: str
  annual_wage: Optional[float] = None
  wage_source: str
  months_until_hire: Optional[float] = None
  notes: str

  model_config = ConfigDict(extra="ignore")
```

### 3.3 Top-level PeopleJsonContract

```python
class PeopleJsonContract(BaseModel):
  """People & capability intake payload per
  people_capability_consultant.py _final_schema() at
  people_capability_consultant.py:80-147. 6 typed fields = 4
  always-present + 1 nullable-required + 1 production-popped
  (per T3).

  Field ordering grouped for readability:
    1. 4 always-present per persistence reality
    2. 1 nullable-required schema field (Optional[X] = None per F7)
    3. 1 schema-required-but-production-popped (Optional[str]
       = None per F1 / PSL2 -- the load-bearing PSL2 case of
       the 5b/5c/5d series)

  No enum vocabularies anywhere in the schema (simpler than
  5b's 5 enums + 5c's 5 enums). The ``wage_source`` vocabulary
  on Person + InferredRole entries is documented at
  consultant.py:218-221 but NOT in the schema enum -- bare
  ``str`` per F9.

  Schema constraints (people.minItems=1 + inferred_roles.
  minItems=1) NOT enforced per §0 / F5.

  Nested object lists keep typed sub-contract structure per T5:
    - people: List[PersonContract]
    - inferred_roles: List[InferredRoleContract]

  ``extra="ignore"`` per F4 tolerates future schema-version
  drift.
  """
  # --- 4 always-present per persistence reality ---
  people: List[PersonContract]
  inferred_roles: List[InferredRoleContract]
  inferred_roles_summary: str
  confidence: float

  # --- 1 nullable-required schema field (Optional[X] = None per F7) ---
  business_naics_6: Optional[str] = None

  # --- 1 schema-required-but-production-popped (Optional[str] = None per F1 / PSL2) ---
  key_people_summary: Optional[str] = None

  model_config = ConfigDict(extra="ignore")
```

### 3.4 Public re-exports

```python
__all__ = [
  "PEOPLE_JSON_STAGE_LABEL",
  "PersonContract",
  "InferredRoleContract",
  "PeopleJsonContract",
]
```

### 3.5 Expected module LOC

200-300 LOC. Smaller than 5b (274 LOC) -- no enum-vocabulary
documentation to bake into the module docstring. Comparable to
5c (287 LOC) since both have similar nesting depth.

---

## 4. Cross-field invariants

**None.**

Per §0 value-constraint policy: content-level checks are out
of scope for sub-contract retrofits. No
``@model_validator(mode="after")``. No ``@field_validator``
beyond JSON-type-correctness.

Examples of invariants that would TYPICALLY be encoded but
are EXPLICITLY OUT OF SCOPE here:
- ``people`` non-empty (schema ``minItems: 1``) — REJECTED per
  §0 (Field(min_length=1) banned).
- ``inferred_roles`` non-empty (schema ``minItems: 1``) —
  REJECTED per §0.
- ``annual_wage > 0`` when not None — REJECTED per §0
  (Field(gt=0) banned).
- ``months_until_hire >= 0`` when not None — REJECTED per §0.
- ``confidence`` numeric range — REJECTED per §0.
- ``wage_source`` in vocabulary
  (client_override/gpt_estimate/unknown) — REJECTED per §0 / F9.
- ``business_naics_6`` 6-digit pattern (analog to 5c's
  b2b_naics_6) — REJECTED per §0 (Field(pattern) banned).
- Consistency between top-level ``business_naics_6`` and the
  cross-flow source ``operating_model_json.business_naics_6``
  — REJECTED per §0 (cross-CONTRACT-field validator banned;
  the cross-flow at intake_consult.py:6228 enforces upstream).
- ``inferred_roles_summary`` matches ``format_roles_summary(inferred_roles)``
  — REJECTED per §0 (cross-field validator banned; the
  post-process at intake_consult.py:6231 enforces upstream).

These rules ARE production reality; they're enforced UPSTREAM
by OpenAI's strict schema, the cross-flow at intake_consult.py
:6228, the post-process at :6231, OR DOWNSTREAM by domain
code (financials.py / post_intake_headcount). Contract 5d
doesn't duplicate.

---

## 5. Retrofit plan

### 5.1 Single-line field-type change

[intake_draft_contract.py:176](../../python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py#L176):

```python
# Before:
people_json: Dict[str, Any]

# After:
people_json: PeopleJsonContract
```

Plus import at the top of the module (alongside 5b's
OperatingModelJsonContract + 5c's TargetMarketJsonContract
imports):

```python
from client_intake_and_finmo.post_intake_contracts.people_json_contract import (
  PeopleJsonContract,
)
```

No other changes to ``IntakeDraftContract`` structure or
field roster.

### 5.2 Contract 5 fixture impact

[tests/_p3_40_contract_5_fixtures.py:55-58](../../tests/_p3_40_contract_5_fixtures.py#L55)
currently emits a 2-field minimal stub for ``people_json``:

```python
"people_json": {
  "people": [],
  "inferred_roles": [],
},
```

After retrofit, this stub no longer validates (missing
non-nullable required schema fields: inferred_roles_summary,
confidence). The fixture gets replaced with a call to
``valid_people_json_dict()`` imported from the new
``_p3_40_contract_5d_fixtures.py`` module (matches 5b/5c F6
precedent).

### 5.3 Contract 5 test impact

[tests/test_p3_40_contract_5_subcontracts.py](../../tests/test_p3_40_contract_5_subcontracts.py)
``OpacityConfirmationTest::test_arbitrary_nested_shape_accepted_for_other_dict_field``
currently uses ``people_json`` as the still-opaque field after
5c's retrofit (the test was repurposed from target_market_json
in 5c-3). After 5d retrofit, this test must be repurposed
again to use another still-opaque field. The remaining 5
opaque Dict[str, Any] fields are: financials_json,
financials_year1_json, marketing_model_json,
planning_context_summary_json, fulfillment_json. Spec
recommends ``financials_year1_json`` (the next 5e R-residual
target).

Per-field rejection tests in
``test_p3_40_contract_5_subcontracts.py`` +
``test_p3_40_contract_5_intake_draft.py`` for ``people_json``
— unchanged (the field is still required at the top level;
the existing "missing rejected" tests stay valid).

Estimate: ~2 Contract 5 test updates needed (subcontracts
opacity test + fixture import). Lands in Commit 5d-3.

### 5.4 No new gate site

Contract 5's existing consumer-side gate at runner.py:189
calls ``validate_intake_draft_at_boundary(payload, side=
SIDE_CONSUMER)``. After 5d retrofit, that gate AUTOMATICALLY
tightens because ``IntakeDraftContract.model_validate`` now
recursively validates ``people_json`` against the new
sub-contract.

**No changes to enforcement.py, phase_codes.py, fail_fast_codes.py,
or any wiring sites.** No new tests for "Contract 5d consumer
gate" — the existing
``test_p3_40_contract_5_consumer_gate.py`` invariants cover
it once the fixtures shift to validly-shaped people_json.

### 5.5 Downstream consumer impact (none expected)

Per trace T4: downstream consumers (runner.py +
post_intake_headcount/schedule.py + financials.py +
post_intake_mapping.py) read people_json field-by-field via
``people_json.get(...)``. After retrofit:
- Gate validates IntakeDraftContract then discards the
  validated instance; raw dict continues downstream unchanged.
- Downstream consumers see the same Dict[str, Any].

R-residual R-f (5b R-g / 5c R-f analog): upgrade downstream
consumers to typed instance reads.

---

## 6. Implementation sequence

Per the directive: 3 commits (mirrors 5b/5c precedent).

### Commit 5d-1 — Sub-contract module + fixtures

Files added:
- ``python/client_intake_and_finmo/post_intake_contracts/people_json_contract.py``
  (200-300 LOC; 3 sub-contracts per §3)
- ``tests/_p3_40_contract_5d_fixtures.py`` (~120-150 LOC)

Fixtures provide minimal-valid builders:
- ``valid_person_dict(full_name="Jane Doe", role_title="Founder",
  ...)`` → PersonContract-shaped dict
- ``valid_inferred_role_dict(role_title="Store Manager", ...)`` →
  InferredRoleContract-shaped dict
- ``valid_people_json_dict(include_key_people_summary=False,
  include_business_naics_6=True, **overrides)`` → full
  PeopleJsonContract-shaped dict. Defaults: 1 person + 1
  inferred_role + populated summary + business_naics_6;
  key_people_summary OMITTED by default (matches production
  post-pop state per T3 / F1).

**Pre-step:** re-verify the 6 required[] entries at
people_capability_consultant.py:138-145 + the
``key_people_summary`` pop at intake_consult.py:6241 + the
2 nested object schemas at people_capability_consultant.py:
94-114 (PersonContract) + :124-131 (InferredRoleContract)
before Commit 5d-1 lands (Contracts 4-7 + 5b + 5c pre-1a
re-verification discipline). If anything diverges, flag back.

### Commit 5d-2 — Sub-contract tests

File added:
- ``tests/test_p3_40_contract_5d_people_json.py``
  (~280-330 LOC; 4 test classes)

Test classes (~20-25 tests, mirrors 5b/5c-2 structure):
- ``PersonContractTest`` (~5): valid; each of 8 non-nullable
  required rejected when absent (pick a representative);
  experience_years accepts non-numeric string per F8;
  wage_source accepts non-vocabulary string per F9; annual_wage
  accepts None.
- ``InferredRoleContractTest`` (~4): valid; missing required;
  annual_wage + months_until_hire accept None;
  months_until_hire accepts negative (per §0 numeric range NOT
  enforced).
- ``PeopleJsonContractTest`` (~10-12):
  - valid full payload accepted (default fixture = production
    post-pop shape with key_people_summary OMITTED).
  - valid payload with key_people_summary present accepted
    (per F1: contract accepts BOTH presence and absence).
  - missing non-nullable required field (people /
    inferred_roles / inferred_roles_summary / confidence)
    rejected.
  - empty ``people`` list accepted (per §0 minItems=1 NOT
    enforced).
  - empty ``inferred_roles`` list accepted (per §0 minItems=1
    NOT enforced).
  - ``business_naics_6`` accepts None.
  - ``business_naics_6`` accepts absent (Optional default).
  - ``key_people_summary`` accepts None.
  - ``key_people_summary`` accepts absent (production post-pop
    shape).
  - PersonContract extra='ignore' for legacy fallback fields
    (role / name / months_until_hire on people items per F2).
  - Nested PersonContract validation propagates through
    top-level.
  - Wrong outer JSON type rejected (string where list
    expected).
- ``ModuleConstantsTest`` (~2): stage label pinned + 6-field
  pin.

**No tests for** (per §0):
- Literal-rejection (no Literals to test — no enums in this
  schema).
- min_length / max_length / pattern rejection (none enforced).
- Cross-field invariants (none exist per §4).
- @model_validator behavior (none exist).
- inferred_roles_summary == format_roles_summary(inferred_roles)
  consistency (REJECTED per §4).

### Commit 5d-3 — Retrofit + Contract 5 fixture / test alignment

Files modified:
- ``python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py``
  (single-line field type change + import per §5.1).
- ``tests/_p3_40_contract_5_fixtures.py``
  (replace the 2-field stub with a call to 5d's
  ``valid_people_json_dict()``).
- ``tests/test_p3_40_contract_5_subcontracts.py``
  (``OpacityConfirmationTest::test_arbitrary_nested_shape_accepted_for_other_dict_field``
  repurposed from people_json to financials_year1_json --
  next 5e R-residual target).

Full-suite verification after 5d-3:
- All Contract 5 + 5b + 5c + 5d suite tests pass.
- Contracts 1-7 + 5b + 5c + 5d cross-suite green.
- Expected total: 602 (today) + ~20-25 (5d-2) = ~620-625
  passed.

**After 5d-3 lands, the 5b/5c/5d sub-contract retrofit series
COMPLETES. Contract 6 R16 + Contract 7 R9 become actionable.**

---

## 7. Open flags for Nick's review

9 flags. Dispositions reflect §0 value-constraint policy.

### F0 — Sub-contract granularity

**(Recommended) (a) 3 sub-contracts in single module**
(``PeopleJsonContract`` + ``PersonContract`` +
``InferredRoleContract``). Matches 5b/5c F0 precedent +
broader F0 multi-shape pattern.

**(b) Flat single PeopleJsonContract with nested shapes as
``Dict[str, Any]``.** Rejected per the 5b/5c F0 disposition.

### F1 — ``key_people_summary`` disposition (THE load-bearing PSL2 case)

**(Recommended) (a) Type as ``Optional[str] = None``** despite
schema-required. Per T3: intake_consult.py:6241 POPS this
field before persistence; production drafts will NEVER carry
it. The contract MUST accept the field's absence.

This is the strongest PSL2 application in the 5b/5c/5d series.
5b/5c had nullable-required fields (schema explicitly allows
null); 5d has a schema-required-but-stripped-by-production
field — a divergence that, if not handled, would fire the
gate on every persisted draft.

**(b) Type as ``str`` (schema-faithful).** Rejected — would
fail-loud on every persisted payload. R-c R-residual covers
the longer-term harmonization (either stop popping in intake,
or drop key_people_summary from the GPT schema).

**(c) Type as ``Optional[str]`` (key-required + value-
nullable).** Rejected — key is INTENTIONALLY absent in
production, not just nullable.

### F2 — Legacy fallback person-item fields (downstream-defensive)

**(Recommended) (a) ``extra="ignore"`` on PersonContract +
R-b R-residual to audit DB + clean up downstream defensive
reads at post_intake_headcount/schedule.py:693-706.** Matches
5b F2 precedent (naics_code / business_naics).

Per T3 (e): post_intake_headcount/schedule.py reads person
items via fallback chain
``role_title or full_name or role or name`` -- ``role`` and
``name`` are NOT in the schema. Similarly, ``months_until_hire``
is read from people-items but the schema only places it on
inferred_roles. ``extra="ignore"`` tolerates these defensively
without typing them as contract fields.

**(b) Add ``role`` / ``name`` / ``months_until_hire`` as
Optional fields on PersonContract.** Rejected — no evidence
they're in any production payload; would clutter the contract
with hypothetical fields. R-b covers the audit + cleanup.

### F3 — Stage label naming

**(Recommended) (a) ``PEOPLE_JSON_STAGE_LABEL =
"INTAKE_DRAFT::people_json"``.** Mirrors 5b/5c F3 pattern.
No new gate per PSL5.

### F4 — ``extra`` policy on all 3 sub-contracts

**(Recommended) (a) ``extra="ignore"`` on every sub-contract**
(top-level PeopleJsonContract + PersonContract +
InferredRoleContract). PSL4 + §0. Same as 5b F4 / 5c F4.

### F5 — Value-level constraints (ALL REJECTED per §0)

**(Recommended) (a) ALL value-level constraints REJECTED.**
``people.minItems=1`` + ``inferred_roles.minItems=1`` NOT
enforced. ``annual_wage > 0`` NOT enforced. ``months_until_hire
>= 0`` NOT enforced. ``confidence`` numeric range NOT enforced.

**(b) Selectively pin people non-empty since the schema
requires at least one person.** Rejected per §0 — empty
people-array represents legitimate production states (e.g.,
pre-finalize edit mode) and downstream code handles empty
gracefully.

### F6 — Composition with Contract 5's fixtures

**(Recommended) (a) Add ``valid_people_json_dict()`` builder
in new ``_p3_40_contract_5d_fixtures.py``; Contract 5's
fixtures import it.** Matches 5b/5c F6 precedent.

### F7 — Required-vs-Optional disposition for ``business_naics_6``

**(Recommended) (a) Type as ``Optional[str] = None``** (key-
optional + value-nullable). Matches 5b/5c F7. Legacy-draft
safety.

**(b) Type as ``Optional[str]`` (no default — required key,
value-nullable).** Rejected for first cut — R-g R-residual
covers tightening post DB audit.

### F8 — ``experience_years`` is schema-typed as string

**(Recommended) (a) Type as bare ``str``** per §0. The schema
says STRING (free-form like "8 years" or "10+ years"). Do NOT
attempt int coercion or pattern matching. Documentary flag.

### F9 — ``wage_source`` documentary vocabulary

**(Recommended) (a) Type as bare ``str``** per §0. The
vocabulary client_override / gpt_estimate / unknown is
documented at consultant.py:218-221 but is NOT in the schema
``enum``. Trivially obvious per §0; documentary flag for
parity with 5b/5c's enum-handling flags.

Expected total: 9 flags. None require Literal /
Field(constraint) / validators per §0.

---

## 8. Known residual cleanups (out of scope for Contract 5d)

**P3.40 Contract Layer Cleanup Pass 6/6 final dispositions:**
- R-a → **DEFERRED**: `confidence` range; §0 prohibits.
- R-b → **ASSESSED + KEPT** in Cleanup 3/6 (legacy DB support; post_intake_headcount/schedule.py fallback chain retained per directive's "THE classic legacy data support case" hint).
- R-c → **DEFERRED**: `key_people_summary` post-pop pattern; either-direction harmonization is intake-side work.
- R-d → **DEFERRED to intake-remediation workstream** (NOT contract-layer cleanup). The `key_people_summary` pop at intake_consult.py:6241 + :10978 is intentional design (commit e57ff49 — single-source-of-truth enforcement). The summary field is a denormalized view of `people_json["people"][].paragraph`; the pop prevents drift between the summary and the per-person source data. The field will be re-surfaced in the writing phase. The downstream submission gate at financials.py:164 reads the popped field and hard-fails. Cloud Claude's audit (post-Contract-7) flagged this as a contradiction. Claude Code VS's intake-side research ([docs/architecture/intake_side_research_post_audit.md](intake_side_research_post_audit.md), commit 8a98e26) established that (1) the pop is design, not bug; (2) the proper fix is Option 3 (replace gate's proxy-summary check with structural check on primary data — people array non-empty + paragraphs populated); (3) the fix requires intake-domain context to do correctly without breaking parallel intake machinery; (4) the bug class includes a parallel finding for `target_market_summary` (Contract 5c R-d-bis). This residual is therefore reclassified from 'contract-layer cleanup deferred' to 'intake-remediation workstream, owned by intake refactor pass.' Fix #1 (steady-state viability) and Fix #2 (headcount derivation) do NOT depend on this gate being fixed — they operate post-submission on the planning side. The contract layer correctly types `key_people_summary` as `Optional[str] = None` per PSL2 production-reality-wins. The contract is sound. The downstream gate needs intake-side surgery that belongs to a separate workstream.
- R-e → **DEFERRED**: Contract 3 fact_template path harmonization (same as 5b R-f / 5c R-e).
- R-f → **DEFERRED**: Downstream consumer typed-instance upgrade.
- R-g → **DEFERRED**: Tighten Optional pending DB audit.
- R-h → **DEFERRED**: `progress_schema` patch flow harmonization.
- R-i → **DONE**: Contract 6 R16 + Contract 7 R9 unblocked; addressed in Cleanup 2/6.

- **R-a.** ``confidence`` field range — schema is unbounded
  ``number``. Per §0 no range constraint (matches 5b R-b /
  5c R-a).
- **R-b.** ~~Downstream defensive person-item reads (``role`` /
  ``name`` / ``months_until_hire`` on people items) at
  post_intake_headcount/schedule.py:693-706. Audit DB for any
  legacy person-item carrying these keys; if zero hits, clean
  up the fallback chain.~~ **ASSESSED in P3.40 Contract Layer
  Cleanup Commit 3/6; FALLBACK CHAIN KEPT for legacy DB
  support.** Reader/writer audit confirmed ZERO current code
  writes ``role`` / ``name`` to person items, and
  ``months_until_hire`` only writes to inferred_roles items
  per the GPT schema. However, the cleanup directive
  explicitly flagged this case: "THE classic 'legacy data
  support' case ... Likely keep the fallback". PersonContract
  has ``extra="ignore"`` tolerating legacy person-item shapes
  at the gate; the schedule.py fallback chain is the
  consumer that actually uses them for staffing-row
  generation. Removing the chain would silently break
  staffing rows for any legacy person item still using the
  old keys. KEPT with explicit ASSESSED+KEPT comments at the
  consumer site. A future DB audit could confirm zero legacy
  data exposure and warrant removal.
- **R-c.** ``key_people_summary`` post-pop pattern. Two paths
  to harmonize:
  - (i) Stop popping in intake_consult.py:6241; persist
    key_people_summary so the contract field can tighten to
    ``str`` (schema-faithful).
  - (ii) Drop key_people_summary from the GPT schema entirely;
    the in-memory reconstruction is the source of truth.
  R-residual to decide; first-cut contract accepts both shapes
  via Optional[str] = None.
- **R-d.** ``financials.py:164`` reads ``pc_obj.get(
  "key_people_summary")`` which always returns None on
  persisted drafts (per R-c). Either remove the read or
  reconstruct from people array at this site too.
- **R-e.** Contract 3 ``fact_template`` field-path
  declarations at post_intake_mapping.py reference
  ``people_json`` paths -- harmonize against typed contract
  roster post-landing (matches 5b R-f / 5c R-e).
- **R-f.** Upgrade downstream consumers (runner.py +
  post_intake_headcount + financials.py + post_intake_mapping)
  to read from the typed PeopleJsonContract instance rather
  than the raw dict (matches 5b R-g / 5c R-f).
- **R-g.** Tighten ``Optional[str] = None`` to ``Optional[str]``
  (key-required + value-nullable) for ``business_naics_6``
  once a DB audit confirms no legacy omissions (matches 5b
  R-h / 5c R-g).
- **R-h.** ``progress_schema`` patch flow harmonization with
  the typed contract roster (matches 5b R-e / 5c R-d). Note:
  progress_schema is collection-progress tracking, not
  per-turn patching like 5c.
- **R-i.** Contract 6 R16 + Contract 7 R9 **NOW ACTIONABLE
  POST-LANDING**. With 5b + 5c + 5d all typed, the
  business_facts composition for Mirror (Contract 7 R9) and
  the industry-baseline business-facts typing (Contract 6
  R16) can proceed in subsequent commits.

---

## 9. Workflow

Same as Contracts 1-7 + 5b + 5c: trace + spec each ship as
single commits, held for Nick review.

**Trace shipped at 0761191.** This is the spec doc.

After spec approval, implementation lands per §6 (3 commits:
5d-1 module + fixtures, 5d-2 sub-contract tests, 5d-3
retrofit + Contract 5 alignment). Push + email per commit per
the standard pattern.

Pre-1a re-verification per Contracts 4-7 + 5b + 5c discipline
(re-grep schema source + key_people_summary pop site + 2
nested schemas before Commit 5d-1 lands).

**After 5d-3 lands, the 5b/5c/5d sub-contract retrofit series
COMPLETES.** Suite expected at ~620-625 passed. Boundary 1
(INTAKE → POST_INTAKE) has all 3 OpenAI-schema-enforced fields
structurally typed; remaining 5 IntakeDraftContract fields
(financials_json, financials_year1_json, marketing_model_json,
planning_context_summary_json, fulfillment_json) are Python-
aggregated shapes per the 5e/f/g/h R-residual track (different
retrofit pattern, separate workflow).

Contract 6 R16 + Contract 7 R9 unblock immediately post-5d-3.

If during Commit 5d-1 anything diverges from production, flag
back the same way Contracts 1-7 + 5b + 5c did — no silent
adjustment.

Expected full-suite total after 5d-3:
~602 (today) + ~20-25 (5d-2) = ~620-625 passed.
