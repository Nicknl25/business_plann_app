# P3.40 Contract 5d — PeopleJsonContract (Trace)

**Status:** Pre-spec trace doc. Spec follows after Nick reviews
this trace. No code lands from this commit.

**Scope:** Sub-contract retrofit for
``IntakeDraftContract.people_json`` (currently
``Dict[str, Any]`` per Contract 5 F0 (b) first cut). Tightens
the field type to a typed sub-contract matching the OpenAI-
schema-enforced payload produced by
``people_capability_finalize`` (per
[people_capability_consultant.py:80-147](../../python/client_intake_and_finmo/people_capability_consultant.py#L80)).

**Parent contract:** Contract 5 — IntakeDraftContract (landed
end-to-end). Contract 5b (operating_model_json) landed at
fc91083 + Contract 5c (target_market_json) landed at 8942527.
**Contract 5d is the FINAL sub-contract retrofit in the
5b/5c/5d series.** After 5d-3 lands, Contract 6 R16 + Contract
7 R9 unblock.

**Companion trace docs:**
- 5b: [p3_40_contract_5b_operating_model_json_trace.md](p3_40_contract_5b_operating_model_json_trace.md)
- 5c: [p3_40_contract_5c_target_market_json_trace.md](p3_40_contract_5c_target_market_json_trace.md)

**§0 policy held verbatim from 5b/5c specs.** Type STRUCTURE,
not VALUES. Bare types only; no Literal narrowing, no Field
constraints, no @model_validator, no @field_validator.

**Pattern:** Retrofit (NOT new boundary contract). No new
PhaseCode / EventCode / FailFastCode; no new gate site;
existing Contract 5 enforcement stack covers it.

---

## 1. Trace task findings (T1-T5)

Five trace tasks per the Contract 5d directive. Headline
findings fold into §3-§6 of the spec doc.

### 1.1 Five headline findings

1. **The OpenAI schema is STRICT** (``additionalProperties:
   false`` + ``strict: True``). 6 required top-level fields at
   [people_capability_consultant.py:138-145](../../python/client_intake_and_finmo/people_capability_consultant.py#L138).
   Companion ``_progress_schema()`` at line 150-184 for
   collection-progress extraction (subset of the final schema;
   not persisted directly).

2. **CRITICAL T3 finding -- ``key_people_summary`` is in the
   schema as REQUIRED but POPPED before persistence at
   [intake_consult.py:6241](../../python/api_handlers/intake_consult.py#L6241):**
   ``people_json.pop("key_people_summary", None)``. Production
   drafts will NEVER carry this field. Per PSL2 production-
   reality-wins: type as ``Optional[str] = None`` despite
   schema-required. This is a stronger Optional-tightening
   case than 5b/5c's nullable-required pattern -- here the
   field is intentionally stripped.

3. **2 nested object types** in the schema, each warrants its
   own typed sub-sub-contract per PSL3:
   - ``PersonContract`` (9 fields per
     people_capability_consultant.py:94-114)
   - ``InferredRoleContract`` (5 fields per
     people_capability_consultant.py:124-131)
   No enum vocabularies anywhere in this schema -- simpler
   than 5b (5 enums) or 5c (5 enums).

4. **1 production extra written into people_json IS in the
   schema** (cross-flow): ``business_naics_6`` populated from
   ``ops_json["business_naics_6"]`` at
   [intake_consult.py:6228](../../python/api_handlers/intake_consult.py#L6228)
   (also writes at :9464, :10224). The field IS in the GPT
   schema as nullable string; the cross-flow just provides a
   value when GPT didn't supply one. No "production extra NOT
   in schema" analog to 5b's 4 extras or 5c's 3 CSVs.

5. **Legacy fallback fields in downstream consumers --
   schema-NOT-listed.** post_intake_headcount/schedule.py:693
   reads person items via fallback chain ``role_title or
   full_name or role or name`` -- ``role`` and ``name`` are
   NOT in the GPT schema; they're defensive fallbacks for
   hypothetical legacy people-item shapes (analog to 5b's
   ``naics_code`` / ``business_naics`` fallbacks in runner.py).
   Similarly, ``months_until_hire`` is read from people-items
   at schedule.py:702 but the schema only places that field
   inside ``inferred_roles`` items (NOT inside people items).

### 1.2 Trace divergences (folded into §3-4)

Per T3 + T4 the contract needs explicit positions on:
- ``key_people_summary``: Optional[str] = None (intentionally
  stripped at persistence).
- Person-item legacy fallback keys (``role``, ``name``,
  ``months_until_hire``): accepted via ``extra="ignore"`` on
  PersonContract; R-residual cleanup for the downstream
  defensive reads.

---

## 2. T1 — OpenAI schema source location

**Primary location:**
[python/client_intake_and_finmo/people_capability_consultant.py:80-147](../../python/client_intake_and_finmo/people_capability_consultant.py#L80),
function ``_final_schema()``. Returns a wrapper dict with
``name`` + ``schema`` keys.

**Companion progress schema:**
[people_capability_consultant.py:150-184](../../python/client_intake_and_finmo/people_capability_consultant.py#L150)
``_progress_schema()`` for backend-only collection-progress
extraction. Subset of the final schema (only people array + a
subset of per-person fields + confidence). The progress shape
is NOT persisted to ``people_json``; it's an in-memory
tracking shape consumed by the intake conversation flow.

**Persistence path:** ``people_capability_finalize`` returns a
dict matching ``_final_schema()``. intake_consult.py post-
processes (lines 6225-6238: cross-flow business_naics_6 from
ops + enrich people via apply_oews_wages_to_people + enrich
inferred_roles + add inferred_roles_summary via
format_roles_summary), then **POPS key_people_summary** at
line 6241, then persists via ``append_messages(...people_json=
people_json...)`` at the standard intake_consult.py write
sites.

**Lifecycle:** GPT call returns pristine 6-field payload →
intake_consult.py enriches (cross-flows business_naics_6,
enriches per-person/per-role wages, derives
inferred_roles_summary) → pops key_people_summary → persisted
to DB → reload from DB on next turn → may re-enrich. The
shape at Contract 5's consumer-side gate (runner.py:189) is
the POST-POP shape (5 of 6 schema fields present;
key_people_summary intentionally absent).

---

## 3. T2 — Field enumeration

6 required top-level fields per
people_capability_consultant.py:138-145. Schema-level
nullability (``["X", "null"]``) determines Optional vs
required.

### 3.1 Top-level fields (6 required per schema)

| # | Field | Schema type | Optional? | Notes |
|---|---|---|---|---|
| 1 | ``people`` | ``array`` of PersonContract, ``minItems: 1`` | required | minItems NOT enforced per §0 |
| 2 | ``key_people_summary`` | ``string`` | **POPPED at persistence** -- type as Optional[str] = None per PSL2 | T3 critical finding |
| 3 | ``inferred_roles`` | ``array`` of InferredRoleContract, ``minItems: 1`` | required | minItems NOT enforced per §0 |
| 4 | ``inferred_roles_summary`` | ``string`` | required | Generated post-process via format_roles_summary at intake_consult.py:6231 |
| 5 | ``business_naics_6`` | ``["string", "null"]`` | nullable-required | Cross-flow from ops_json at intake_consult.py:6228 |
| 6 | ``confidence`` | ``number`` | required | scalar (no min/max in schema) |

Field-count breakdown:
- **3 non-nullable required schema fields** (always present):
  people, inferred_roles, inferred_roles_summary, confidence
  → wait that's 4. Recount:
  - people, inferred_roles_summary, confidence (always
    present)
  - inferred_roles is non-nullable-required schema-wise but
    has a fallback `[]` at intake_consult.py:6233-6234 when
    enrichment fails → still always present.
  So 4 non-nullable required.
- **1 nullable-required schema field**: business_naics_6.
- **1 schema-required-but-production-stripped field**:
  key_people_summary (PSL2 → Optional[str] = None).
- 4 + 1 + 1 = 6. ✓

### 3.2 Nested object — PersonContract (9 fields per people_capability_consultant.py:94-114)

| # | Field | Schema type | Optional? | Notes |
|---|---|---|---|---|
| 1 | ``full_name`` | ``string`` | required | |
| 2 | ``role_title`` | ``string`` | required | |
| 3 | ``primary_responsibilities`` | ``string`` | required | |
| 4 | ``relevant_background`` | ``string`` | required | |
| 5 | ``experience_years`` | ``string`` | required | schema says STRING (free-form like "8 years"), not number |
| 6 | ``why_strengthens_business`` | ``string`` | required | |
| 7 | ``paragraph`` | ``string`` | required | |
| 8 | ``annual_wage`` | ``["number", "null"]`` | nullable-required | Set by GPT or by apply_oews_wages_to_people enrichment |
| 9 | ``wage_source`` | ``string`` | required | values: client_override / gpt_estimate / unknown (per docstring at people_capability_consultant.py:218-221) -- bare str per §0 |

### 3.3 Nested object — InferredRoleContract (5 fields per people_capability_consultant.py:124-131)

| # | Field | Schema type | Optional? |
|---|---|---|---|
| 1 | ``role_title`` | ``string`` | required |
| 2 | ``annual_wage`` | ``["number", "null"]`` | nullable-required |
| 3 | ``wage_source`` | ``string`` | required |
| 4 | ``months_until_hire`` | ``["number", "null"]`` | nullable-required |
| 5 | ``notes`` | ``string`` | required |

### 3.4 Enum vocabularies (NONE in schema)

Unlike 5b (5 enums) and 5c (5 enums), the people_json schema
has **ZERO ``enum`` constraints**. The ``wage_source``
vocabulary (client_override / gpt_estimate / unknown) is
documented in the consultant system prompt at
people_capability_consultant.py:218-221 but is NOT pinned in
the JSON schema as an enum. Type as bare ``str`` per §0 (the
absence of schema enum makes this trivial).

### 3.5 Schema constraints to BAN per §0

These appear in the schema and must NOT translate to Pydantic
constraints:
- ``people.minItems: 1`` — list-length NOT enforced.
- ``inferred_roles.minItems: 1`` — list-length NOT enforced.

No schema patterns or numeric bounds anywhere.

---

## 4. T3 — Production-reality verification (CRITICAL)

Same level of scrutiny as Contracts 5b/5c T3. Production
people_json shape diverges from the GPT schema in 2 ways.

### 4.1 (a) ``key_people_summary`` POPPED before persistence

[intake_consult.py:6240-6241](../../python/api_handlers/intake_consult.py#L6240):

```python
if isinstance(people_json, dict):
  people_json.pop("key_people_summary", None)
```

This is the CRITICAL T3 finding. The OpenAI schema lists
``key_people_summary`` as a REQUIRED string. But production
intentionally strips it before persistence -- it's reconstructed
in-memory from the people array via fact-template rendering for
downstream consumption (intake_consult.py:6243-6282).

**Spec disposition required (F-flag):** type as
``Optional[str] = None`` per PSL2. The contract MUST accept
the field's absence in production payloads. Tightening to
``str`` (schema-faithful) would fail-loud on every persisted
payload — that's the exact "retrofit-fires-in-production"
risk the directive's §0 + PSL2 prevents.

### 4.2 (b) ``business_naics_6`` cross-flow from ops_json

[intake_consult.py:6228](../../python/api_handlers/intake_consult.py#L6228)
(also :9464, :10224): ``people_json["business_naics_6"] =
ops_json.get("business_naics_6")``.

The field IS in the GPT schema as nullable string; this is
NOT a production extra outside the schema. The cross-flow
just provides a value when GPT didn't supply one. No spec
action needed beyond noting the cross-flow in the field's
docstring.

### 4.3 (c) ``inferred_roles_summary`` post-process generation

[intake_consult.py:6231](../../python/api_handlers/intake_consult.py#L6231):
``people_json["inferred_roles_summary"] = format_roles_summary(enriched_roles)``.
With fallback at :6235-6236: ``if "inferred_roles_summary"
not in people_json: people_json["inferred_roles_summary"] =
""``.

The field IS in the GPT schema as required string; the
post-process just regenerates it deterministically from the
inferred_roles array. Production reality: always present.

### 4.4 (d) Per-person wage enrichment

[intake_consult.py:6229-6230](../../python/api_handlers/intake_consult.py#L6229)
calls ``apply_oews_wages_to_people()`` which enriches per-
person ``annual_wage`` + ``wage_source`` fields (per
people_roles.py:516-571). Returns ``dict(person)`` preserving
all original fields, only updating wage-related keys. No extra
keys injected.

### 4.5 (e) Legacy fallback person-item fields (downstream-defensive)

[post_intake_headcount/schedule.py:693](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L693)
reads via fallback chain:

```python
role_title = str(
  item.get("role_title")
  or item.get("full_name")
  or item.get("role")     # NOT in schema
  or item.get("name")     # NOT in schema
  or ""
).strip()
```

``role`` and ``name`` are NOT in the GPT schema; they're
defensive fallbacks for hypothetical legacy person-item
shapes. Similarly,
[schedule.py:702-706](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L702)
reads ``months_until_hire`` from people-items, but the schema
only places that field inside ``inferred_roles`` items.

**Two interpretations** (analog to 5b T3 (b)):
- (A) Truly-legacy people-items in DB carry these field
  names. Contract must accept them as Optional fields on
  PersonContract.
- (B) Pure defensive dead code; no current people-item
  carries them. Contract should NOT include them; spec's
  R-residual list flags them for downstream cleanup.

Per the 5b precedent (F2 (a) — extra="ignore" + R-residual):
spec recommends ``extra="ignore"`` on PersonContract +
R-residual to audit + clean up the defensive reads. No
contract fields for ``role`` / ``name`` /
``months_until_hire`` on PersonContract.

### 4.6 (f) Edit-mode + patch flow

The progress schema (people_capability_consultant.py:150-184)
is for collection-progress tracking, NOT per-turn patching.
There's no analog to 5c's ``_turn_schema`` patch flow with a
properties whitelist. Edit-mode reruns
``people_capability_finalize`` with full schema validation,
regenerating the post-process fields each time.

No drift mechanism detected. Post-load shape stable.

---

## 5. T4 — Downstream consumers

Per the directive: identify who reads people_json fields after
Contract 5's gate.

### 5.1 Reader inventory

| File | Lines | What's read | Pattern |
|---|---|---|---|
| [runner.py:213](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L213) | parse_json_dict | Full blob | Loaded into ``draft_data`` |
| [runner.py:237](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L237) | ``people_json`` local re-parse | Full blob | Downstream-handle |
| [runner.py:283, 1092](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L283) | ``business_naics_6`` | Field | NAICS fallback chain (cross-cuts ops + people fallback chain) |
| [runner.py:290, 389, 966, 1021, 1178, 1604, 1763, 1913, 1949](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L290) | Full blob copied | ``copy.deepcopy(people_json or {})`` | Passed downstream as-is |
| [post_intake_mapping.py:702, 873, 1061, 1064, 1378](../../python/client_intake_and_finmo/post_intake_mapping.py#L702) | Required-context-key declarations | Full blob | GPT prompt block registration |
| [post_intake_headcount/schedule.py:683-717](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L683) | ``people[].role_title``, ``full_name``, ``role`` (legacy), ``name`` (legacy), ``annual_wage``, ``wage_source``, ``months_until_hire``; top-level ``business_naics_6`` | Field-by-field | Builds ``key_people_from_intake`` staffing rows; legacy fallback chain for role identification |
| [post_intake_headcount/schedule.py:1102-1124](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1102) | ``_people_json_with_resolved_key_person_wages`` | Re-enrichment path | Calls back into ``apply_oews_wages_to_people`` |
| [post_intake_headcount/feasibility_repair.py:115, 168](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L115) | people_json passed-through | Full blob | Forwarded to repair loop |
| [financials.py:157-164](../../python/api_handlers/financials.py#L157) | ``key_people_summary`` (post-pop -- always None) + ``people`` + ``inferred_roles`` | Field-by-field | API-handler validates people presence at submission |
| [people_roles.py:516-571](../../python/client_intake_and_finmo/people_roles.py#L516) | ``people[].annual_wage``, ``wage_source`` | Per-person enrichment | OEWS wage application |

### 5.2 Composition opportunity

- Contract 5b (operating_model_json): NO composition. Disjoint
  field sets EXCEPT the ``business_naics_6`` cross-flow (5b
  contains the source; 5d contains a copy). Both contracts
  type the field independently as ``Optional[str] = None``.
- Contract 5c (target_market_json): NO composition. Disjoint.
- Contract 3 ``fact_template``: references people_json field
  paths via fact placeholders (e.g.,
  ``{{fact:people.key_people_summary}}``). Per 5b R-f /
  5c R-e: harmonize as R-residual when 5b/c/d all land.
- Contract 6 R16 / Contract 7 R9 unblocked once 5b + 5c + 5d
  all land.

### 5.3 Retrofit non-breaking

Per 5b/5c precedent: typed sub-contract is a subset of
``Dict[str, Any]``. Existing downstream consumers read
field-by-field via ``people_json.get(...)``. After retrofit:
- Gate validates IntakeDraftContract then discards the
  validated instance; raw dict continues downstream unchanged.
- Downstream consumers see the same Dict[str, Any].

R-residual (5b R-g / 5c R-f analog): upgrade downstream
consumers to typed instance reads.

### 5.4 Critical headcount-coupling risk

post_intake_headcount/schedule.py builds staffing rows from
``people_json["people"]`` -- if Contract 5d tightens too far
(e.g., requiring ``key_people_summary`` per the schema), the
gate fires on EVERY production draft (which never carries it
post-pop). PSL2 F-flag (key_people_summary Optional) prevents
this.

---

## 6. T5 — Sub-contract structure decision

### 6.1 Field-count breakdown

- Top-level: 6 schema fields (post-PSL2: 4 always-present + 1
  nullable + 1 popped-Optional) = 6 typed fields
- ``PersonContract``: 9 fields
- ``InferredRoleContract``: 5 fields

Total nesting depth: 1 level (top → list-of-entry-objects).
Same depth as 5c.

### 6.2 Sub-contract granularity recommendation

**3 sub-contracts in a single module** (mirrors 5b/5c F0 pattern):

```
PeopleJsonContract            <- top-level, 6 typed fields
  ├── people: List[PersonContract]
  ├── inferred_roles: List[InferredRoleContract]
  └── (4 scalars: key_people_summary [Optional per PSL2/T3],
       inferred_roles_summary, business_naics_6 [nullable],
       confidence)
```

2 sub-sub-contracts: ``PersonContract``,
``InferredRoleContract``. Same-module pattern per F0.
Module path:
``python/client_intake_and_finmo/post_intake_contracts/people_json_contract.py``.

### 6.3 Module-level constants

```python
PEOPLE_JSON_STAGE_LABEL = "INTAKE_DRAFT::people_json"
```

No enum tuples (no Literal[...] per §0; no enums in the schema
anyway).

### 6.4 Composition with IntakeDraftContract

Single-line retrofit at
[intake_draft_contract.py:176](../../python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py#L176):

```python
# Before:
people_json: Dict[str, Any]

# After:
people_json: PeopleJsonContract
```

Plus import at the top of the module (alongside 5b's
OperatingModelJsonContract + 5c's TargetMarketJsonContract
imports).

### 6.5 Expected module LOC

200-300 LOC. Slightly larger than 5c (287 LOC) because
PersonContract has 9 fields, but no enum vocabularies + no
schema-pattern constraints to document. Smaller than 5b's
274 module by a bit (no enum vocabulary list to declare in
the docstring).

---

## 7. Spec-doc flag candidates (preview only — for §7 of spec)

Surfacing here as a checklist for the spec doc.

- **F0** — Sub-contract granularity (3 sub-contracts in one
  module per T5). PSL3 lean.
- **F1** — ``key_people_summary`` disposition. Schema-required
  but production-popped per T3 (a). Spec recommends
  ``Optional[str] = None`` per PSL2 production-reality-wins.
  This is the load-bearing flag of 5d.
- **F2** — Legacy fallback person-item fields (``role`` /
  ``name`` / ``months_until_hire`` on people items) per T3 (e).
  Spec recommends ``extra="ignore"`` on PersonContract +
  R-residual to audit + clean up downstream defensive reads
  (5b F2 / 5c F2 precedent).
- **F3** — Stage label naming
  ``PEOPLE_JSON_STAGE_LABEL = "INTAKE_DRAFT::people_json"``
  per 5b/5c F3 pattern.
- **F4** — ``extra`` policy on all 3 sub-contracts.
  ``extra="ignore"`` per PSL4 / §0 / 5b F3 / 5c F3.
- **F5** — Value-level constraints (schema minItems=1 on
  people + inferred_roles; no patterns; no numeric bounds; no
  enums). Per §0: ALL REJECTED. (Simpler flag than 5b/5c F5
  because the schema has fewer constraints to reject.)
- **F6** — Composition with Contract 5's fixtures. Updating
  Contract 5's test fixtures + 5d's new sub-contract fixtures
  must align (per 5b/5c F6 precedent).
- **F7** — Required-vs-Optional disposition for the 1
  nullable-required field (``business_naics_6``). Type as
  ``Optional[str] = None`` per 5b/5c F7. Plus key_people_summary
  per F1.
- **F8** — ``experience_years`` is typed as ``string`` in the
  schema (not number — free-form like "8 years" or "10+
  years"). Documentary flag: per §0 type as bare ``str``; do
  NOT attempt int coercion or pattern matching.
- **F9** — ``wage_source`` documentary vocabulary (per
  consultant docstring at people_capability_consultant.py:
  218-221: client_override / gpt_estimate / unknown). Per §0
  type as bare ``str`` -- the vocabulary is NOT in the schema
  enum so this is trivially obvious; documentary flag for
  parity with 5b/5c's enum-handling flags.

Expected total: 9 flags. None require Literal /
Field(constraint) / validators per §0.

---

## 8. Pre-spec residuals (for §8 of spec)

R-residuals surfaced by this trace, to fold into the spec's §8:

- **R-a.** ``confidence`` field range — schema is unbounded
  ``number``. Per §0 no range constraint (matches 5b R-b /
  5c R-a).
- **R-b.** Downstream defensive person-item reads (``role`` /
  ``name`` / ``months_until_hire`` on people items) at
  post_intake_headcount/schedule.py:693-706. Audit DB for any
  legacy person-item carrying these keys; if zero hits, clean
  up the fallback chain (matches 5b R-a -- DB audit pattern).
- **R-c.** ``key_people_summary`` post-pop pattern. The schema
  marks it required but intake_consult.py:6241 strips it. Two
  paths to harmonize:
  - (i) Stop popping; persist key_people_summary so the
    contract field can tighten to ``str`` (schema-faithful).
  - (ii) Drop key_people_summary from the GPT schema entirely;
    the in-memory reconstruction is the source of truth.
  R-residual to decide; first-cut contract accepts both shapes
  via Optional[str] = None.
- **R-d.** ``financials.py:164`` reads ``pc_obj.get(
  "key_people_summary")`` which always returns None on
  persisted drafts (per R-c). Either remove the read or
  reconstruct from people array at this site too.
- **R-e.** Contract 3 ``fact_template`` field-path
  declarations at post_intake_mapping.py:1829 reference
  ``people_json`` paths -- harmonize against typed contract
  roster post-landing (matches 5b R-f / 5c R-e).
- **R-f.** Upgrade downstream consumers (runner.py +
  post_intake_headcount + financials.py + post_intake_mapping)
  to read from the typed PeopleJsonContract instance rather
  than the raw dict (matches 5b R-g / 5c R-f).
- **R-g.** Tighten ``Optional[str] = None`` to ``Optional[str]``
  (required key, value-nullable) for ``business_naics_6`` once
  a DB audit confirms no legacy omissions (matches 5b R-h /
  5c R-g).
- **R-h.** ``progress_schema`` patch flow harmonization with
  the typed contract roster (matches 5b R-e / 5c R-d).
- **R-i.** Contract 6 R16 + Contract 7 R9 unblocked **NOW
  ACTIONABLE** once 5b + 5c + 5d all land.

---

## 9. Workflow

Same pattern as Contracts 1-7 + 5b + 5c: trace + spec each
ship as single commits, held for Nick review.

**This is the trace doc.** After Nick reviews, the spec doc
covers §0-9 (§0 = value-constraint policy held verbatim).

After spec approval, implementation lands per the 3-commit
sequence (5b/5c precedent):
- **Commit 5d-1:** PeopleJsonContract module + sub-sub-contracts
  + fixtures.
- **Commit 5d-2:** Sub-contract tests mirroring 5b/5c-2 test
  patterns. Expected 15-25 tests.
- **Commit 5d-3:** Retrofit IntakeDraftContract.people_json
  field type ``Dict[str, Any]`` → ``PeopleJsonContract``.
  Update Contract 5 existing fixtures + tests. Run full
  Contract 5 + 5b + 5c + 5d + cross-contract suites. Expected
  suite delta 602 → ~620-625.

**Pre-1a re-verification per Contracts 4-7 + 5b + 5c
discipline.** Before Commit 5d-1 lands, re-grep:
- people_capability_consultant.py:138-145 required[] list
- intake_consult.py:6225-6241 enrichment + pop sites
- post_intake_headcount/schedule.py:683-717 legacy fallback
  chain
to confirm spec values match production verbatim.

After 5d lands, **the 5b/5c/5d sub-contract retrofit series
COMPLETES.** Contract 6 R16 + Contract 7 R9 become
actionable; remaining IntakeDraftContract Dict[str, Any]
fields (financials_json, financials_year1_json,
marketing_model_json, planning_context_summary_json,
fulfillment_json) are Python-aggregated shapes (5e/f/g/h R-
residuals, not OpenAI-schema-enforced — different retrofit
pattern).

If during Commit 5d-1 anything diverges from production, flag
back the same way Contracts 1-7 + 5b + 5c did — no silent
adjustment.
