# P3.40 Contract 5c — TargetMarketJsonContract (Spec)

**Status:** Specification only. No code lands until Nick reviews
this doc. After review, implementation follows the commit
sequence in §6 below.

**Scope:** Sub-contract retrofit for
``IntakeDraftContract.target_market_json`` (currently
``Dict[str, Any]`` per Contract 5 F0 (b)). Tightens the field
type to a 4-sub-contract typed shape matching the OpenAI-schema-
enforced payload produced by ``target_market_finalize`` (per
[target_market_consultant.py:129-247](../../python/client_intake_and_finmo/target_market_consultant.py#L129)).

**Parent contract:** Contract 5 — IntakeDraftContract (landed
end-to-end). Contract 5b retrofit landed at fc91083 (suite:
575 passing). Contract 5c follows the SAME pattern.

**Companion trace doc:** [p3_40_contract_5c_target_market_json_trace.md](p3_40_contract_5c_target_market_json_trace.md)
(landed at 9196663, 529 LOC, 5 trace tasks + 8 candidate flags
+ 9 R-residuals).

---

## 0. Value-constraint policy (LOAD-BEARING)

**The contract types JSON SHAPE, not VALUES.** Held verbatim
from Contract 5b spec §0 (applies uniformly to 5b + 5c + 5d).

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
  (``GenderAgeIntentEntry``, ``IncomeIntentEntry``,
  ``SelectionsEntry`` per T5) become typed sub-contracts; policy
  applies recursively.
- ``extra="ignore"`` on every sub-contract per F4.

**BANNED constructs anywhere in Contract 5c**:
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

**Rationale.** Same as 5b: intake data varies STRUCTURALLY by
business type; content constraints fire false-positive
ContractViolations; OpenAI's strict mode enforces value-level
rules upstream; Pydantic re-enforcing duplicates work and
introduces drift risk.

---

## 1. Trace findings synthesis

Per the trace doc T1-T5 + the §0 policy, the contract structure
mirrors Contract 5b's compactness:

- **T1** — OpenAI schema source:
  [target_market_consultant.py:129-247](../../python/client_intake_and_finmo/target_market_consultant.py#L129)
  ``_final_schema()``. Strict ``additionalProperties: false``.
  Companion ``_turn_schema()`` at line 250-309 for per-turn
  patches (strictly whitelisted — does NOT introduce extras).
- **T2** — 11 required top-level schema fields (4 non-nullable
  + 7 nullable-required arrays) + 3 nested object types +
  5 enum vocabularies (all bare ``str`` per §0). Schema also
  has ``b2b_naics_6`` pattern + minItems=1/maxItems=20 + all
  enums — ALL REJECTED per §0.
- **T3** — 3 CSV-string production extras at finalize time
  (``target_market_b2b_industry`` / ``target_market_b2b_size``
  / ``target_market_b2b_age``). Per F1: type explicitly as
  Optional + ``extra="ignore"``.
- **T4** — Downstream consumers read field-by-field at ~10
  runner.py + post_intake_mapping sites + financials.py:122-155
  reads the 3 CSV extras with fallback derivation from list
  fields. Retrofit non-breaking.
- **T5** — 4-sub-contract structure in a single module per the
  F0 multi-shape pattern.

---

## 2. OpenAI schema → Pydantic translation table

Per §0. Field-by-field. ``Optional[X] = None`` default for
nullable-typed schema fields per F7 (legacy-draft safety per
5b precedent).

### 2.1 Top-level TargetMarketJsonContract (11 schema + 3 production extras = 14 fields)

| # | Field | Pydantic type | Required-shape | Source |
|---|---|---|---|---|
| **GPT schema fields (11 required per target_market_consultant.py:233-244)** | | | | |
| 1 | ``consumer_type`` | ``str`` | required | schema enum → bare str per §0 |
| 2 | ``gender_age_intent`` | ``Optional[List[GenderAgeIntentEntry]] = None`` | nullable-required | ``["array", "null"]`` of objects |
| 3 | ``income_intent`` | ``Optional[List[IncomeIntentEntry]] = None`` | nullable-required | ``["array", "null"]`` of objects |
| 4 | ``selections`` | ``Optional[List[SelectionsEntry]] = None`` | nullable-required | ``["array", "null"]`` of objects |
| 5 | ``b2b_industry_terms`` | ``Optional[List[Any]] = None`` | nullable-required | ``["array", "null"]`` of string — item-type pinning BANNED per §0 |
| 6 | ``b2b_naics_6`` | ``Optional[List[Any]] = None`` | nullable-required | ``["array", "null"]`` of string with pattern/minItems/maxItems — ALL BANNED per §0 |
| 7 | ``b2b_size_bands`` | ``Optional[List[Any]] = None`` | nullable-required | ``["array", "null"]`` of string enum — item enum BANNED per §0 |
| 8 | ``b2b_age_bands`` | ``Optional[List[Any]] = None`` | nullable-required | ``["array", "null"]`` of string enum — item enum BANNED per §0 |
| 9 | ``target_market_summary`` | ``str`` | required | |
| 10 | ``marketing_plan_summary`` | ``str`` | required | |
| 11 | ``confidence`` | ``float`` | required; numeric range NOT enforced per §0 | |
| **Production extras (3, per T3, NOT in OpenAI schema)** | | | | |
| 12 | ``target_market_b2b_industry`` | ``Optional[str] = None`` | conditional per T3 | CSV joined from ``b2b_naics_6`` |
| 13 | ``target_market_b2b_size`` | ``Optional[str] = None`` | conditional per T3 | CSV joined from ``b2b_size_bands`` |
| 14 | ``target_market_b2b_age`` | ``Optional[str] = None`` | conditional per T3 | CSV joined from ``b2b_age_bands`` |

**Field count math:** 4 non-nullable-required schema fields + 7
nullable-required schema fields + 3 conditional production
extras = 14 typed fields. ``extra="ignore"`` accepts any
additional fields silently (per F4 + future schema-version
drift safety).

### 2.2 GenderAgeIntentEntry (3 fields per target_market_consultant.py:139-151)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``gender_focus`` | ``str`` | required; enum (female / male / all) NOT pinned per §0 |
| 2 | ``age_min`` | ``float`` | required |
| 3 | ``age_max`` | ``float`` | required |

### 2.3 IncomeIntentEntry (2 fields per target_market_consultant.py:155-164)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``income_min`` | ``float`` | required |
| 2 | ``income_max`` | ``float`` | required |

### 2.4 SelectionsEntry (2 fields per target_market_consultant.py:167-184)

| # | Field | Pydantic type | Required-shape |
|---|---|---|---|
| 1 | ``segment`` | ``str`` | required; enum (Education / Household Structure / Housing Economics / Employment) NOT pinned per §0 |
| 2 | ``acs_codes`` | ``List[Any]`` | required; item-type pinning BANNED per §0 |

---

## 3. Field-by-field contract spec

Per §0 policy, the module is small. 4 sub-contracts in one
module file:
``python/client_intake_and_finmo/post_intake_contracts/target_market_json_contract.py``.

### 3.1 Module imports + constants

```python
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


#: Stage label exported for discoverability per F3. Sub-contract
#: is invoked through Contract 5's existing INTAKE_DRAFT_STAGE_
#: LABEL stack -- this label only surfaces if a future direct
#: gate site is added (PSL5 future-proof, 5b precedent).
TARGET_MARKET_JSON_STAGE_LABEL = "INTAKE_DRAFT::target_market_json"
```

No enum tuples. No invariant constants.

### 3.2 Sub-sub-contracts (define in dependency order)

```python
class GenderAgeIntentEntry(BaseModel):
  """One gender-age intent entry. 3 fields per
  target_market_consultant.py:139-151. Per §0: gender_focus
  schema enum (female / male / all) NOT pinned to Literal."""
  gender_focus: str
  age_min: float
  age_max: float

  model_config = ConfigDict(extra="ignore")


class IncomeIntentEntry(BaseModel):
  """One income-intent entry. 2 fields per
  target_market_consultant.py:155-164."""
  income_min: float
  income_max: float

  model_config = ConfigDict(extra="ignore")


class SelectionsEntry(BaseModel):
  """One segment-selection entry. 2 fields per
  target_market_consultant.py:167-184. Per §0: segment schema
  enum (Education / Household Structure / Housing Economics /
  Employment) NOT pinned; acs_codes inner array typed as
  List[Any] (item-type pinning BANNED)."""
  segment: str
  acs_codes: List[Any]

  model_config = ConfigDict(extra="ignore")
```

### 3.3 Top-level TargetMarketJsonContract

```python
class TargetMarketJsonContract(BaseModel):
  """Target-market intake payload per
  target_market_consultant.py _final_schema() at
  target_market_consultant.py:129-247. 11 required GPT-schema
  fields + 3 production extras (T3) = 14 typed fields.

  Field ordering grouped for readability:
    1. 4 non-nullable required schema fields (bare type, no default)
    2. 7 nullable-required schema fields (Optional[X] = None per F7)
    3. 3 production extras (Optional[X] = None per F1)

  Enum vocabularies (consumer_type / gender_focus / segment /
  b2b_size_bands items / b2b_age_bands items) all bare ``str``
  per F5 / §0.

  b2b_naics_6 schema pattern (``^[0-9]{6}$``) + minItems/
  maxItems NOT enforced per §0 -- items type as ``Any``;
  list-length NOT bounded.

  ``extra="ignore"`` per F4 tolerates future schema-version
  drift.
  """
  # --- 4 non-nullable required GPT-schema fields ---
  consumer_type: str
  target_market_summary: str
  marketing_plan_summary: str
  confidence: float

  # --- 7 nullable-required GPT-schema fields (Optional[X] = None per F7) ---
  gender_age_intent: Optional[List[GenderAgeIntentEntry]] = None
  income_intent: Optional[List[IncomeIntentEntry]] = None
  selections: Optional[List[SelectionsEntry]] = None
  b2b_industry_terms: Optional[List[Any]] = None
  b2b_naics_6: Optional[List[Any]] = None
  b2b_size_bands: Optional[List[Any]] = None
  b2b_age_bands: Optional[List[Any]] = None

  # --- 3 production extras (T3 -- NOT in GPT schema; Optional per F1) ---
  target_market_b2b_industry: Optional[str] = None
  target_market_b2b_size: Optional[str] = None
  target_market_b2b_age: Optional[str] = None

  model_config = ConfigDict(extra="ignore")
```

### 3.4 Public re-exports

```python
__all__ = [
  "TARGET_MARKET_JSON_STAGE_LABEL",
  "GenderAgeIntentEntry",
  "IncomeIntentEntry",
  "SelectionsEntry",
  "TargetMarketJsonContract",
]
```

### 3.5 Expected module LOC

150-300 LOC. Simpler than 5b's 274 LOC (one nesting level vs
two; flat b2b_* arrays type as ``List[Any]`` without
sub-contracts).

---

## 4. Cross-field invariants

**None.**

Per §0 value-constraint policy: content-level checks are out of
scope for sub-contract retrofits. No
``@model_validator(mode="after")``. No ``@field_validator``
beyond JSON-type-correctness. No cross-field business-logic
enforcement.

Examples of invariants that would TYPICALLY be encoded for a
boundary contract but are EXPLICITLY OUT OF SCOPE here:
- ``age_min <= age_max`` within GenderAgeIntentEntry — REJECTED
  per §0 (cross-field validator banned).
- ``income_min <= income_max`` within IncomeIntentEntry —
  REJECTED per §0.
- ``b2b_naics_6`` items match pattern ``^[0-9]{6}$`` — REJECTED
  per §0 (Field(pattern=...) banned).
- ``b2b_naics_6`` length 1-20 — REJECTED per §0
  (Field(min/max_length) banned).
- CSV-extras consistency: ``target_market_b2b_industry == ",".join(sorted(b2b_naics_6))`` —
  REJECTED per §0 (cross-field validator banned; the producer
  at target_market.py:870-877 enforces upstream).
- For b2b/mixed ``consumer_type``, b2b_* fields MUST be
  populated — REJECTED per §0 (conditional-required cross-field
  invariant banned; financials.py:143-155 enforces at submission
  time, NOT the contract layer).
- ``b2b_size_bands`` items in the schema enum vocabulary —
  REJECTED per §0 (Literal narrowing banned).
- ``confidence`` numeric range — REJECTED per §0 (Field(ge/le)
  banned).

These rules ARE production reality; they're enforced UPSTREAM
by OpenAI's strict schema, the per-turn patch whitelist, the
target_market_finalize CSV regeneration, OR DOWNSTREAM by the
financials.py submission validator. Contract 5c doesn't
duplicate.

---

## 5. Retrofit plan

### 5.1 Single-line field-type change

[intake_draft_contract.py:175](../../python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py#L175):

```python
# Before:
target_market_json: Dict[str, Any]

# After:
target_market_json: TargetMarketJsonContract
```

Plus import at the top of the module:

```python
from client_intake_and_finmo.post_intake_contracts.target_market_json_contract import (
  TargetMarketJsonContract,
)
```

No other changes to ``IntakeDraftContract`` structure or field
roster.

### 5.2 Contract 5 fixture impact

[tests/_p3_40_contract_5_fixtures.py:53-55](../../tests/_p3_40_contract_5_fixtures.py#L53)
currently emits a 1-field minimal stub for
``target_market_json``:

```python
"target_market_json": {
  "target_market_summary": "Test market",
},
```

After retrofit, this stub no longer validates (missing the 3
other non-nullable required schema fields: consumer_type,
marketing_plan_summary, confidence). The fixture gets replaced
with a call to ``valid_target_market_json_dict()`` imported
from the new ``_p3_40_contract_5c_fixtures.py`` module
(matches 5b F6 precedent).

### 5.3 Contract 5 test impact

[tests/test_p3_40_contract_5_subcontracts.py:155-165](../../tests/test_p3_40_contract_5_subcontracts.py#L155)
``OpacityConfirmationTest::test_arbitrary_nested_shape_accepted``
currently uses ``target_market_json`` as the still-opaque
field after 5b's retrofit:

```python
def test_arbitrary_nested_shape_accepted_for_other_dict_field(self) -> None:
  payload = valid_intake_draft_dict()
  payload["target_market_json"] = { ... arbitrary ... }
```

After 5c retrofit, this test must be repurposed to use another
still-opaque field (people_json — Contract 5d retrofit
follows). Pattern matches 5b-3's adjustment of the same test
class.

Per-field rejection tests in
``test_p3_40_contract_5_subcontracts.py:60`` +
``test_p3_40_contract_5_intake_draft.py:82-84`` for
``target_market_json`` — unchanged (the field is still
required at the top level; the existing "missing rejected"
tests stay valid).

Estimate: ~2 Contract 5 test updates needed (subcontracts
opacity test + the fixture import in
``_p3_40_contract_5_fixtures.py``). Lands in Commit 5c-3.

### 5.4 No new gate site

Per the retrofit nature: Contract 5's existing consumer-side
gate at runner.py:189 calls
``validate_intake_draft_at_boundary(payload, side=SIDE_CONSUMER)``.
After 5c retrofit, that gate AUTOMATICALLY tightens because
``IntakeDraftContract.model_validate`` now recursively
validates ``target_market_json`` against the new sub-contract.

**No changes to enforcement.py, phase_codes.py, fail_fast_codes.py,
or any wiring sites.** No new tests for "Contract 5c consumer
gate" — the existing
``test_p3_40_contract_5_consumer_gate.py`` invariants cover it
once the fixtures shift to validly-shaped target_market_json.

### 5.5 Downstream consumer impact (none expected)

Per trace T4: downstream consumers (runner.py +
post_intake_mapping.py + financials.py + intake_submission.py)
read target_market_json field-by-field via
``market_json.get("field")`` — duck-typed dict access. After
retrofit:
- Pydantic returns ``TargetMarketJsonContract`` instances at
  the gate; Contract 5's downstream code reads from the raw
  dict at runner.py:236.
- Gate validates IntakeDraftContract then discards the
  validated instance; raw dict continues downstream unchanged.
- Downstream consumers see the same Dict[str, Any] they see
  today.

R-residual R-g (5b R-g analog): upgrade downstream consumers
to typed instance reads. Out of scope for 5c.

---

## 6. Implementation sequence

Per the directive: 3 commits (mirrors 5b precedent).

### Commit 5c-1 — Sub-contract module + fixtures

Files added:
- ``python/client_intake_and_finmo/post_intake_contracts/target_market_json_contract.py``
  (150-300 LOC; 4 sub-contracts per §3)
- ``tests/_p3_40_contract_5c_fixtures.py`` (~120-150 LOC)

Fixtures provide minimal-valid builders:
- ``valid_gender_age_intent_entry_dict(gender_focus="all",
  age_min=18.0, age_max=65.0)`` → GenderAgeIntentEntry-shaped
  dict
- ``valid_income_intent_entry_dict(income_min=30000.0,
  income_max=120000.0)`` → IncomeIntentEntry-shaped dict
- ``valid_selections_entry_dict(segment="Education",
  acs_codes=["B15003_017E"])`` → SelectionsEntry-shaped dict
- ``valid_target_market_json_dict(consumer_type="consumer",
  include_gender_age=True, include_income=True,
  include_selections=True, include_b2b_arrays=False,
  include_csv_extras=False, **overrides)`` → full
  TargetMarketJsonContract-shaped dict. Defaults to a
  consumer-only profile (no b2b_* fields); toggles enable
  b2b/mixed cases.

**Pre-step:** re-verify the 11 required[] entries at
target_market_consultant.py:233-244 + the 3 CSV-extra producer
sites at target_market.py:870-877 + 1181-1189 before Commit
5c-1 lands (Contracts 4-7 + 5b pre-1a re-verification
discipline). If anything diverges, flag back.

### Commit 5c-2 — Sub-contract tests

File added:
- ``tests/test_p3_40_contract_5c_target_market_json.py``
  (~250-300 LOC; 5 test classes)

Test classes (~20-25 tests, mirrors 5b-2 structure):
- ``GenderAgeIntentEntryTest`` (~3): valid; missing required
  field rejected; bare-str gender_focus accepts non-schema
  value.
- ``IncomeIntentEntryTest`` (~2): valid; missing required
  rejected.
- ``SelectionsEntryTest`` (~3): valid; missing required
  rejected; acs_codes accepts mixed types per List[Any].
- ``TargetMarketJsonContractTest`` (~10-12):
  - valid consumer-only payload accepted (4 non-nullable
    required + 7 nullable defaults).
  - missing non-nullable required field rejected.
  - All 7 nullable-required fields accept None.
  - All 7 nullable-required fields accept absent (F7 legacy
    safety).
  - Each of the 3 CSV extras accepts absent (F1).
  - Bare-str enum vocabularies accept non-schema values
    (consumer_type=non-vocab, gender_focus=non-vocab,
    segment=non-vocab, b2b_size_bands item=non-vocab,
    b2b_age_bands item=non-vocab).
  - b2b_naics_6 accepts items that don't match the pattern
    (per §0 pattern BANNED).
  - b2b_naics_6 accepts >20 items (per §0 maxItems BANNED).
  - b2b_naics_6 accepts empty list (per §0 minItems=1
    BANNED).
  - Nested entry validation propagates through top-level
    (e.g., missing gender_focus in nested entry surfaces at
    the top-level validation).
  - extra='ignore' accepts unknown keys.
  - Wrong outer JSON type rejected (string where list expected).
- ``ModuleConstantsTest`` (~2): stage label pinned + 14
  typed-field pin.

**No tests for** (per §0):
- Literal-rejection (no Literals to test).
- Pattern-rejection (b2b_naics_6 pattern BANNED).
- min_length/max_length-rejection (b2b_naics_6 length-bounds
  BANNED).
- Cross-field invariants (none exist per §4).
- @model_validator behavior (none exist).
- Conditional-required (consumer_type=b2b implies b2b_*
  populated) — enforced downstream, not at this contract.

### Commit 5c-3 — Retrofit + Contract 5 fixture / test alignment

Files modified:
- ``python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py``
  (single-line field type change + import per §5.1).
- ``tests/_p3_40_contract_5_fixtures.py``
  (replace the 1-field stub with a call to 5c's
  ``valid_target_market_json_dict()``).
- ``tests/test_p3_40_contract_5_subcontracts.py``
  (``OpacityConfirmationTest::test_arbitrary_nested_shape_
  accepted_for_other_dict_field`` repurposed from
  target_market_json to people_json — the next 5d retrofit
  target).

Full-suite verification after 5c-3:
- All Contract 5 + 5b + 5c suite tests pass.
- Contracts 1-7 + 5b + 5c cross-suite green.
- Expected total: 575 (today) + ~20-25 (5c-2) = ~595-600
  passed.

---

## 7. Open flags for Nick's review

8 flags. Dispositions reflect §0 value-constraint policy.

### F0 — Sub-contract granularity

**(Recommended) (a) 4 sub-contracts in single module**
(``TargetMarketJsonContract`` +
``GenderAgeIntentEntry`` +
``IncomeIntentEntry`` +
``SelectionsEntry``). Matches Contract 5b F0 precedent + the
broader F0 multi-shape pattern from Contracts 6 + 7. PSL3
confirmed.

**(b) Flat single TargetMarketJsonContract with all nested
shapes as ``Dict[str, Any]``.** Rejected per the 5b F0
disposition.

### F1 — Persisted-extras disposition (3 CSV production extras per T3)

**(Recommended) (a) Type the 3 CSV extras as Optional fields
explicitly + ``extra="ignore"``.** Per the 5b F1 precedent.
Discoverability win for future maintainers.

**(b) Skip the 3 extras and rely on ``extra="ignore"`` alone.**
Rejected per 5b F1 disposition.

### F2 — No legacy fallback fields (differs from 5b F2)

**(Recommended) (a) ``extra="ignore"`` only + no R-residual
cleanup needed.** Per trace T3 (d): no defensive reads
analogous to 5b's ``naics_code`` / ``business_naics`` exist
for target_market_json. The only "fallback" pattern is
financials.py:122-155 deriving the 3 CSV extras from list
fields — that's fallback to SCHEMA FIELDS, not unknown legacy
fields.

### F3 — Stage label naming

**(Recommended) (a) ``TARGET_MARKET_JSON_STAGE_LABEL =
"INTAKE_DRAFT::target_market_json"``.** Mirrors 5b F3 pattern.
No new gate per PSL5; label only surfaces if a future direct
gate site is added.

### F4 — ``extra`` policy on all 4 sub-contracts

**(Recommended) (a) ``extra="ignore"`` on every sub-contract**
(top-level TargetMarketJsonContract + GenderAgeIntentEntry +
IncomeIntentEntry + SelectionsEntry). PSL4 + §0. Same as 5b F4.

### F5 — Value-level constraints (ALL REJECTED per §0)

**(Recommended) (a) ALL value-level constraints REJECTED.** No
Literal narrowing for the 5 enum vocabularies (consumer_type,
gender_focus, segment, b2b_size_bands items, b2b_age_bands
items — all bare ``str``). No ``Field(pattern="^[0-9]{6}$")``
on b2b_naics_6 items. No ``Field(min_length=1, max_length=20)``
on b2b_naics_6. No ``Field(ge/le)`` on age_min / age_max /
income_min / income_max / confidence. No model_validators for
``age_min <= age_max`` or ``income_min <= income_max``.

**(b) Selectively pin the b2b_naics_6 pattern (``^[0-9]{6}$``)
since NAICS codes have a strict format.** Rejected per §0 —
the pattern enforcement belongs in domain code (e.g.,
financials.py during NAICS resolution), not at the contract
boundary. Future-business-type variation may introduce
legitimate non-6-digit identifiers.

### F6 — Composition with Contract 5's fixtures

**(Recommended) (a) Add ``valid_target_market_json_dict()``
builder in new ``_p3_40_contract_5c_fixtures.py``; Contract
5's fixtures import it.** Matches 5b F6 precedent.

**(b) Inline a full 14-field stub in Contract 5's fixtures.**
Rejected per 5b F6 disposition.

### F7 — Required-vs-Optional disposition for the 7 nullable-required schema fields

**(Recommended) (a) Type as ``Optional[X] = None`` (key-
optional + value-nullable).** Matches 5b F7. Legacy-draft
safety: accommodates both current schema (key present, value
null in consumer-only case) AND drafts that may omit keys
entirely.

**(b) Type as ``Optional[X]`` (no default — required key,
value-nullable).** Tighter; matches OpenAI strict-mode
semantic exactly. Rejected for first cut — R-h R-residual
covers tightening once a DB audit confirms no legacy
omissions.

### F8 — ``acs_codes`` typing inside SelectionsEntry

**(Recommended) (a) ``List[Any]`` per §0.** Schema says
``array of string``; per §0 item-type pinning is BANNED.
Documentary flag — same pattern applies to all the b2b_* flat
arrays at the top level.

**(b) ``List[str]``.** Rejected per §0 (item-type pinning
BANNED). Pinning to ``str`` here would mean a future
schema-version drift that adds non-string codes (e.g., numeric
identifiers) silently fails the contract.

Expected total: 8 flags. None require ``Literal`` /
``Field(constraint)`` / validators per §0.

---

## 8. Known residual cleanups (out of scope for Contract 5c)

**P3.40 Contract Layer Cleanup Pass 6/6 final dispositions:**
- R-a → **DEFERRED**: `confidence` range; §0 prohibits constraint.
- R-b → **DEFERRED**: `acs_codes` item-type pinning; §0 prohibits.
- R-c → **DEFERRED**: `b2b_naics_6` pattern + length bounds; §0 prohibits at contract layer.
- R-d → **DEFERRED**: `_turn_schema()` patch harmonization is intake-side work.
- R-e → **DEFERRED**: Contract 3 fact_template path harmonization (same as 5b R-f).
- R-f → **DEFERRED**: Downstream consumer typed-instance upgrade (same as 5b R-g).
- R-g → **DEFERRED**: Tighten Optional pending DB audit (same as 5b R-h).
- R-h → **DEFERRED**: Conditional-required CSV-extras check enforced downstream at intake_submission.py:240-263.
- R-i → **DONE**: Contract 6 R16 + Contract 7 R9 unblocked; addressed in Cleanup 2/6.
- R-d-bis → **DEFERRED to intake-remediation workstream**. `target_market_summary` parallel bug. Surfaced during cloud Claude audit response research ([docs/architecture/intake_side_research_post_audit.md](intake_side_research_post_audit.md), commit 8a98e26). Structurally identical to Contract 5d R-d (`key_people_summary`): (1) `target_market_summary` popped at intake_consult.py:10863 (intentional, same single-source-of-truth pattern as `key_people_summary`); (2) downstream gate-read at financials.py:95 hard-fails on the popped field; (3) the summary is a denormalized view of the per-segment target market data; (4) same Option 3 fix applies (replace proxy-summary check with structural check on primary data); (5) same disposition: intake-remediation workstream, not contract-layer cleanup. This residual was not surfaced during the original Contract 5c spec drafting because the cleanup-pass discipline didn't catch the parallel between `key_people_summary` and `target_market_summary`. Documented here for the intake remediation pass to address both fields together.

- **R-a.** ``confidence`` field range — schema is unbounded
  ``number``. Per §0 no range constraint (matches 5b R-b).
- **R-b.** ``acs_codes`` item-type pinning deferred per §0
  (matches trace R-c). If a future consumer requires strict
  string-only validation, add at the consumer site (out of
  contract scope).
- **R-c.** ``b2b_naics_6`` pattern (``^[0-9]{6}$``) +
  minItems/maxItems deferred per §0 (matches trace R-d).
  Pattern validation belongs in domain code (e.g.,
  financials.py during NAICS resolution), not the contract.
- **R-d.** ``_turn_schema()`` patch-shape harmonization —
  patch whitelist at target_market_consultant.py:262-294
  covers 6 of the 14 contract fields. Align whitelist with
  typed contract roster post-landing (matches 5b R-e).
- **R-e.** Contract 3 ``fact_template`` field-path
  declarations at post_intake_mapping.py:1829 reference
  ``target_market_json`` paths. Harmonize against typed
  contract roster post-landing (matches 5b R-f).
- **R-f.** Upgrade downstream consumers (runner.py +
  financials.py + post_intake_mapping.py + intake_submission.py)
  to read from the typed TargetMarketJsonContract instance
  rather than the raw dict at runner.py:236. Yields
  end-to-end typed plumbing (matches 5b R-g).
- **R-g.** Tighten ``Optional[X] = None`` to ``Optional[X]``
  for the 7 nullable-required schema fields once a DB audit
  confirms no legacy omissions (matches 5b R-h).
- **R-h.** Conditional-required cross-field check
  (``consumer_type in {"b2b", "mixed"}`` implies the 3 b2b_*
  CSV extras present) currently enforced at
  intake_submission.py:240-263. Document for clarity; do NOT
  enforce at this contract layer per §0.
- **R-i.** Unblocked downstream R-residuals:
  - Contract 6 R16 (industry baseline business-facts typing).
  - Contract 7 R9 (Mirror.business_facts compose Contracts
    5b/c/d).
  Both become actionable once 5b + 5c + 5d all land.

---

## 9. Workflow

Same as Contracts 1-7 + 5b: trace + spec each ship as single
commits, held for Nick review.

**Trace shipped at 9196663.** This is the spec doc.

After spec approval, implementation lands per §6 (3 commits:
5c-1 module + fixtures, 5c-2 sub-contract tests, 5c-3 retrofit
+ Contract 5 alignment). Push + email per commit per the
standard pattern.

Pre-1a re-verification per Contracts 4-7 + 5b discipline
(re-grep schema source + CSV-extra producer sites + financials.py
consumer site before Commit 5c-1 lands).

After 5c lands, proceed to 5d (people_json) — same value-
constraint policy (§0) applies. Once all three (5b + 5c + 5d)
land, Contracts 6 R16 + 7 R9 become actionable.

If during Commit 5c-1 anything diverges from production, flag
back the same way Contracts 1-7 + 5b did — no silent
adjustment.

Expected full-suite total after 5c-3:
~575 (today) + ~20-25 (5c-2) = ~595-600 passed.
