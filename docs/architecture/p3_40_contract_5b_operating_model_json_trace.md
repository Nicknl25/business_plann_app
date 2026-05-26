# P3.40 Contract 5b — OperatingModelJsonContract (Trace)

**Status:** Pre-spec trace doc. Spec follows after Nick reviews
this trace. No code lands from this commit.

**Scope:** Sub-contract retrofit for
``IntakeDraftContract.operating_model_json`` (currently
``Dict[str, Any]`` per Contract 5 F0 (b)). Tightens the field
type to a typed sub-contract matching the OpenAI-schema-
enforced shape that GPT produces at intake finalize.

**Parent contract:** Contract 5 — IntakeDraftContract
(landed end-to-end at the Contract 5 commit series). The
existing consumer-side gate at
[runner.py:189](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L189)
already validates the full draft payload; retrofitting
``operating_model_json`` automatically tightens that gate
without new wiring.

**Unblocks downstream R-residuals:**
- Contract 6 R16 (industry baseline business-facts typing) and
  Contract 7 R9 (Mirror.business_facts compose Contracts 5b/c/d)
  become actionable once 5b + 5c + 5d all land.

**Pattern:** Retrofit (NOT new boundary contract). Per the
retrofit directive: no new PhaseCode / EventCode /
FailFastCode; no new gate site; existing Contract 5 enforcement
stack covers it. Smaller-scope spec + implementation series.

---

## 1. Trace task findings (T1-T5)

Five trace tasks per the Contract 5b directive. Headline findings
fold directly into the spec's §3 (sub-contract structure) + §4
(production-divergence handling) + §6 (implementation sequence).

### 1.1 Five headline findings

1. **The OpenAI schema is STRICT** (``additionalProperties: false``
   + ``strict: True``). 23 required top-level fields enforced at
   the API layer per
   [intake_consultant.py:67-182](../../python/client_intake_and_finmo/intake_consultant.py#L67).
   Top-level unit_* fields are nullable per multi-LOB rule
   (system prompt at intake_consultant.py:636-639).

2. **Production POST-PROCESSES the GPT payload** by adding 4
   extra fields NOT in the GPT schema. Persisted alongside the
   23 schema fields:
   - ``business_naics_6`` (str, 6-digit NAICS)
   - ``competitive_advantage`` (str, sanitized text)
   - ``business_type_candidates`` (List[str])
   - ``business_type_candidates_locked`` (bool)
   Plus 2 internal ``_ops_restatement_*`` flags STRIPPED before
   persistence. Contract 5b must accept all 4 persisted extras.

3. **Three nested object types** in the schema, each warrants its
   own typed sub-sub-contract per PSL3:
   - ``LobModelContract`` (2 fields: lob_name, products[])
   - ``ProductContract`` (9 fields per
     intake_consultant.py:91-115)
   - ``MilestoneContract`` (2 fields: description, timing)
   ``countries`` is just ``List[str]`` (no sub-contract warranted).

4. **Downstream consumers read field-by-field, not as a blob.**
   [runner.py:284-285](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L284)
   has legacy-fallback reads: ``naics_code`` and ``business_naics``
   (NEITHER in the GPT schema NOR in the 4 production extras —
   defensive fallbacks for older drafts). Per PSL2 these must
   either: (a) be tolerated by the contract via ``extra="ignore"``,
   or (b) be EXPLICITLY R-listed for retroactive cleanup as part
   of 5b.

5. **No re-validation on draft reload.** intake_consult.py loads
   ops_json as-is from DB; mutates via patches; persists back.
   Edit-mode flows mean Contract 5b's typing must be robust
   across multi-turn intake — a payload typed once must remain
   valid after subsequent patches that ONLY modify schema-known
   keys.

### 1.2 Trace divergences (folded into §3-4)

Per T3 (extras) + T4 (legacy fallbacks) the contract needs an
explicit position on each diverging field. §3 enumerates the
contract roster; §4 enumerates per-field disposition.

---

## 2. T1 — OpenAI schema source location

**Primary location:**
[python/client_intake_and_finmo/intake_consultant.py:67-182](../../python/client_intake_and_finmo/intake_consultant.py#L67),
function ``_final_schema()``. Returns a wrapper dict with
``name`` + ``schema`` keys. ``schema`` is the strict JSON-schema
dict passed to OpenAI's Responses API.

**API call site:**
[intake_consultant.py:583-684](../../python/client_intake_and_finmo/intake_consultant.py#L583),
function ``consultant_finalize()``. Lines 651-666 wire the
schema into the API payload:

```python
schema_wrapper = _final_schema()
payload = {
  "model": model,
  "input": [...],
  "text": {
    "format": {
      "type": "json_schema",
      "name": schema_wrapper["name"],
      "schema": schema_wrapper["schema"],
      "strict": True,  # <-- enforces additionalProperties=False
    }
  },
}
```

**Persistence path:** ``consultant_finalize`` returns a dict that
intake_consult.py assigns to ``ops_json`` (e.g. at
intake_consult.py:9804, 10786), POST-PROCESSES (adds 4 extras
per T3), then persists via ``append_messages(...
operating_model_json=ops_json...)`` at:
- intake_consult.py:8251-8260
- intake_consult.py:9847, 9879
- intake_consult.py:10766, 10829
- intake_consult.py:11102
(and several other call sites — the pattern repeats per turn).

**Lifecycle:** GPT call returns pristine schema-conformant
payload → intake_consult mutates → persists → reload from DB
on next turn → may mutate again via patches → re-persist. The
shape at the Contract 5 consumer-side gate (runner.py:189) is
the POST-MUTATION shape, NOT the pristine GPT output.

---

## 3. T2 — Field enumeration

23 required top-level fields per intake_consultant.py:156-180.
Schema-level nullability (``["type", "null"]``) determines
Optional vs required.

### 3.1 Top-level fields (23 required)

| # | Field | Schema type | Optional? | Notes |
|---|---|---|---|---|
| 1 | ``consumer_type`` | ``string`` enum | required | enum: consumer / b2b / mixed |
| 2 | ``business_type`` | ``string`` | required | free-form (constrained by system prompt to candidates list) |
| 3 | ``business_stage`` | ``["string", "null"]`` | Optional | nullable per schema |
| 4 | ``business_description_summary`` | ``string`` | required | fact-template with placeholders |
| 5 | ``lob_models`` | ``["array", "null"]`` of LOB items | Optional | nullable per schema; items = LobModelContract |
| 6 | ``unit_name`` | ``["string", "null"]`` | Optional | null in multi-LOB case |
| 7 | ``unit_description`` | ``["string", "null"]`` | Optional | null in multi-LOB case |
| 8 | ``unit_cadence`` | ``["string", "null"]`` enum | Optional | enum: weekly / monthly / contract / None |
| 9 | ``units_per_week_capacity`` | ``["number", "null"]`` | Optional | null in multi-LOB case |
| 10 | ``units_per_period_capacity`` | ``["number", "null"]`` | Optional | null in multi-LOB case |
| 11 | ``operating_periods_per_year`` | ``["number", "null"]`` | Optional | null in multi-LOB case |
| 12 | ``utilization_rate`` | ``["number", "null"]`` | Optional | null in multi-LOB case |
| 13 | ``unit_price`` | ``["number", "null"]`` | Optional | null in multi-LOB case |
| 14 | ``shipping_method`` | ``string`` | required | free-form |
| 15 | ``sales_modality`` | ``string`` enum | required | enum: physical / online / hybrid |
| 16 | ``geographic_scope`` | ``string`` enum | required | enum: local / regional / national / international |
| 17 | ``geographic_coverage`` | ``string`` | required | ZIPs/counties/metros/states |
| 18 | ``countries`` | ``array`` of ``string`` | required | non-nullable array |
| 19 | ``milestones`` | ``array`` of MilestoneContract, ``minItems: 1`` | required | non-empty list |
| 20 | ``capacity_driver`` | ``string`` enum | required | enum: labor / system / demand |
| 21 | ``primary_growth_lever`` | ``string`` | required | free-form |
| 22 | ``legal_entity`` | ``string`` | required | short label |
| 23 | ``confidence`` | ``number`` | required | scalar (no min/max in schema) |

### 3.2 Nested object — ProductContract (9 fields per
intake_consultant.py:91-115)

| # | Field | Schema type | Optional? | Notes |
|---|---|---|---|---|
| 1 | ``product_name`` | ``string`` | required | |
| 2 | ``unit_name`` | ``string`` | required | |
| 3 | ``unit_description`` | ``string`` | required | |
| 4 | ``unit_cadence`` | ``string`` enum | required | enum: weekly / monthly / contract (NOT nullable per nested schema) |
| 5 | ``units_per_week_capacity`` | ``number`` | required | |
| 6 | ``units_per_period_capacity`` | ``number`` | required | |
| 7 | ``operating_periods_per_year`` | ``["number", "null"]`` | Optional | nullable per schema |
| 8 | ``utilization_rate`` | ``["number", "null"]`` | Optional | nullable per schema |
| 9 | ``unit_price`` | ``number`` | required | |

Per the system prompt at intake_consultant.py:622, unit_price
must be non-zero — the spec recommends ``Field(gt=0)`` (PSL2
production-reality lean).

### 3.3 Nested object — LobModelContract (2 fields)

| # | Field | Schema type | Optional? | Notes |
|---|---|---|---|---|
| 1 | ``lob_name`` | ``string`` | required | |
| 2 | ``products`` | ``array`` of ProductContract, ``minItems: 1`` | required | non-empty list |

### 3.4 Nested object — MilestoneContract (2 fields)

| # | Field | Schema type | Optional? | Notes |
|---|---|---|---|---|
| 1 | ``description`` | ``string`` | required | |
| 2 | ``timing`` | ``string`` | required | |

### 3.5 Enum vocabularies (Literal types)

Per the JSON-schema ``enum`` constraints. Spec recommends pinning
verbatim as Pydantic ``Literal`` types:

- ``consumer_type``: ``Literal["consumer", "b2b", "mixed"]``
- ``sales_modality``: ``Literal["physical", "online", "hybrid"]``
- ``geographic_scope``: ``Literal["local", "regional", "national", "international"]``
- ``capacity_driver``: ``Literal["labor", "system", "demand"]``
- ``unit_cadence`` (top-level): ``Optional[Literal["weekly", "monthly", "contract"]]``
- ``unit_cadence`` (nested in ProductContract): ``Literal["weekly", "monthly", "contract"]`` (NOT nullable per nested schema)

---

## 4. T3 — Production-reality verification (CRITICAL)

Per the directive's emphasis: **T3 is the step that prevents
retrofit-fires-in-production**. Production ops_json shape
DIVERGES from the GPT schema in 4 ways (a + b + c below).

### 4.1 (a) Persisted extras not in the GPT schema

After GPT returns the pristine 23-field payload,
intake_consult.py adds 4 fields BEFORE persistence:

| # | Field | Producer site | Type | Trigger |
|---|---|---|---|---|
| 1 | ``business_naics_6`` | intake_consult.py:5914, 8490, 8496, 9403, 9407, 9421, 9426 (writes); seeded via ``_ensure_ops_business_naics`` at intake_consult.py:8129 on draft load | ``str`` (6-digit NAICS) or ``None`` | Auto-populated when business_type present |
| 2 | ``competitive_advantage`` | intake_consult.py:8568 | ``str`` (sanitized text) | "ops" focus mode + ``comp_action == "confirm_proceed"`` |
| 3 | ``business_type_candidates`` | intake_consult.py:8479 | ``List[str]`` | Business-type selection flow (edit mode, restatement required) |
| 4 | ``business_type_candidates_locked`` | intake_consult.py:8480 | ``bool`` | Set ``True`` immediately after ``business_type_candidates`` populated |

**Internal flags STRIPPED before persistence** (do NOT appear in
DB-persisted payload, no contract handling needed):
- ``_ops_restatement_pending`` (bool, popped at intake_consult.py:8457)
- ``_ops_restatement_text`` (str, popped at intake_consult.py:8457)

**Spec decision required (F-flag):** type the 4 persisted extras
explicitly as Optional contract fields, OR rely on
``extra="ignore"`` per PSL4. Per the Contracts 2-7 precedent of
"type what production produces", the spec recommends EXPLICIT
typing (Option (a)). See §6 F2.

### 4.2 (b) Legacy fallback reads downstream

[runner.py:284-285](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L284)
+ [runner.py:1093-1094](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1093)
read 2 fields that are NEITHER in the GPT schema NOR in the
4 production extras:

```python
or (ops_json or {}).get("naics_code")
or (ops_json or {}).get("business_naics")
```

These are defensive fallbacks for hypothetical legacy drafts.
Two interpretations:

- **Interpretation A:** Truly-legacy drafts in the DB carry these
  field names (pre-business_naics_6 era). Contract must accept
  them as Optional fields.
- **Interpretation B:** Pure defensive dead code; no current
  ops_json carries them. Contract should NOT include them; the
  spec's R-residual list flags them for runner.py cleanup.

Spec-level F-flag covers this — need a one-time DB audit
(R-residual A) OR a git-blame trace (R-residual B) to decide. For
first cut, the spec recommends ``extra="ignore"`` to be safe;
post-landing the residual cleanup tightens.

### 4.3 (c) Mutation timeline + edit-mode robustness

Per the lifecycle in §2:
1. GPT call returns pristine 23-field payload.
2. intake_consult.py adds 4 extras + 2 internal flags.
3. Persisted to DB (internal flags stripped).
4. On next turn, draft loaded as-is — extras still present.
5. ``_apply_model_ops_patch`` at intake_consult.py:907-968 merges
   user-edit patches via an **allowed_keys whitelist** (17 keys —
   ``allowed_keys`` set at intake_consult.py:917-937). Patches
   CANNOT introduce new extra keys; the contract's
   ``extra="ignore"`` is therefore safe across edit cycles.
6. ``_normalize_ops_capacity_compat`` fills capacity gaps but
   does NOT add unknown keys.

**Conclusion:** post-load extras stay limited to the 4 enumerated
in §4.1 + the 2-3 legacy fallbacks in §4.2. The contract's
field roster is stable.

### 4.4 (d) Multi-LOB nullability behavior (production-confirmed)

Per the system prompt at intake_consultant.py:636-639:

```
- When multiple LOBs or multiple products are confirmed, set
  top-level unit_name, unit_description, unit_cadence,
  units_per_week_capacity, units_per_period_capacity,
  operating_periods_per_year, and unit_price to null.
- When only one LOB with one product is confirmed, set top-level
  unit fields, top-level operating_periods_per_year, and
  top-level utilization_rate to that single product.
```

The schema enforces nullability for these top-level fields; the
prompt instructs GPT to USE null in multi-LOB case. Post-GPT,
``_apply_model_ops_patch`` lines 946-967 copy single-product
values UP to the top level. So in production:
- **Single-product:** top-level unit_* fields populated (string +
  float values).
- **Multi-product:** top-level unit_* fields are null.

Both cases must validate — already covered by the Optional
typing in §3.1.

---

## 5. T4 — Downstream consumers

Per the directive: identify who reads operating_model_json
fields after Contract 5's gate.

### 5.1 Reader inventory

| File | Lines | What's read | Pattern |
|---|---|---|---|
| [runner.py:211](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L211) | per-section parse_json_dict | Full blob | Loaded into ``draft_data`` |
| [runner.py:235](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L235) | ops_json local re-parse | Full blob | Loaded for field-by-field reads |
| [runner.py:281-285](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L281) | ``business_type``, ``business_naics_6``, ``naics_code``, ``business_naics`` | Field-by-field | NAICS fallback chain (legacy fallback per §4.2) |
| [runner.py:288](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L288) | Full blob | Full blob | Forwarded into ``shared_context['operating_model_json']`` |
| [runner.py:298, 387, 491, 1018, 1177, 1762, 1846, 1911, 1947](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L298) | Full blob copied | ``copy.deepcopy(ops_json)`` | Passed to downstream callers as-is |
| [runner.py:562](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L562) | ``business_naics_6`` | Field | Used to derive ``naics_6`` digits |
| [runner.py:566](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L566) | ``business_stage`` | Field | Used for stage detection |
| [runner.py:1090](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1090) | ``business_type`` | Field | Re-read at second NAICS resolve site |
| [post_intake_mapping.py:683, 720, 1061, 1076](../../python/client_intake_and_finmo/post_intake_mapping.py#L683) | Required-context-key declarations | Full blob | ``required_context_keys`` registration for GPT prompt blocks |
| [post_intake_mapping.py:700, 734, 871, 1168, 1233, 1378](../../python/client_intake_and_finmo/post_intake_mapping.py#L700) | Listed in GPT prompt context groups | Full blob | Marshalled into GPT prompts |
| [post_intake_mapping.py:1825-1827](../../python/client_intake_and_finmo/post_intake_mapping.py#L1825) | ``operating_model_json.business_type`` derived-fact source path | Path declaration | Fact-template renderer |
| [post_intake_mapping.py:2557](../../python/client_intake_and_finmo/post_intake_mapping.py#L2557) | ``ops_json`` context-row key | Full blob | Marketing/realism reviewer GPT context |

### 5.2 Composition opportunity vs Contract 3 fact_template

Per the directive's T4: "Contract 3's Flag 4 deferred typing of
``fact_template`` ... confirm whether operating_model_json fields
appear inside fact_template or are read independently."

Cross-check finds:
- ``fact_template`` is consumed inside
  ``BusinessFactsForSolverContract.fact_template`` (Contract 3).
  Its content is a JSON-like template with ``{{fact:ops.unit_price}}``
  placeholders (per intake_consultant.py:631-634).
- The placeholders REFERENCE operating_model_json field paths
  but the template itself doesn't EMBED the operating_model_json
  payload — it's resolved at render time by the fact-template
  renderer at post_intake_mapping.py:1825-1827.
- **Conclusion:** no direct composition between
  OperatingModelJsonContract and ``fact_template``. Both reference
  the same source fields but live in separate contract surfaces.
  R-residual: harmonize fact-template field path declarations
  against the typed OperatingModelJsonContract roster when 5b
  lands.

### 5.3 Cross-contract read-site implications

- Contract 1 (FinmoModelInputContract): does NOT read
  operating_model_json directly.
- Contract 6 (IndustryBaselineResolvedContract): R16 named in
  the directive — once 5b lands, Contract 6's business-facts
  typing can compose ``OperatingModelJsonContract`` fields.
- Contract 7 (AmalgamatedSessionContract): R9 named in the
  directive — once 5b + 5c + 5d all land, Contract 7's
  ``business_facts`` typing can compose Contracts 5b/c/d.
- All downstream consumers will benefit from the typed shape;
  retrofit is non-breaking because the existing ``Dict[str, Any]``
  typing is a strict superset of ``OperatingModelJsonContract``
  (any valid contract dict is a valid Dict[str, Any]).

---

## 6. T5 — Sub-contract structure decision

Per the directive: if 10+ fields with nested sub-objects,
sub-sub-contracts may be warranted.

### 6.1 Field-count breakdown

- Top-level: 23 schema fields + 4 production extras = 27 fields
- ``LobModelContract``: 2 fields (+ nested list)
- ``ProductContract``: 9 fields (per LOB product entry)
- ``MilestoneContract``: 2 fields

### 6.2 Sub-contract granularity recommendation

**4 sub-contracts in a single module** (mirrors the F0 multi-shape
pattern from Contracts 6 + 7):

```
OperatingModelJsonContract     <- top-level, 27 fields, the
                                  retrofit target for
                                  IntakeDraftContract.operating_
                                  model_json
  ├── lob_models: Optional[List[LobModelContract]]
  │     └── products: List[ProductContract]
  ├── milestones: List[MilestoneContract]
  └── countries: List[str]    <- inline; no sub-contract
                                 (str list trivial)
```

3 sub-sub-contracts: ``LobModelContract``, ``ProductContract``,
``MilestoneContract``. Same module per the F0 single-module
multi-shape precedent. Module:
``python/client_intake_and_finmo/post_intake_contracts/operating_model_json_contract.py``.

Re-imported into intake_draft_contract.py so the retrofit field
type change is a single-line edit.

### 6.3 Module-level constants

Per the Contracts 1-7 precedent of pinning enum vocabularies as
exported tuples:

```python
OPERATING_MODEL_JSON_STAGE_LABEL = ...  # SEE F3 below
SUPPORTED_CONSUMER_TYPES = ("consumer", "b2b", "mixed")
SUPPORTED_SALES_MODALITIES = ("physical", "online", "hybrid")
SUPPORTED_GEOGRAPHIC_SCOPES = ("local", "regional", "national", "international")
SUPPORTED_CAPACITY_DRIVERS = ("labor", "system", "demand")
SUPPORTED_UNIT_CADENCES = ("weekly", "monthly", "contract")
```

### 6.4 Composition with IntakeDraftContract

Single-line retrofit at
[intake_draft_contract.py:174](../../python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py#L174):

```python
# Before:
operating_model_json: Dict[str, Any]

# After:
operating_model_json: OperatingModelJsonContract
```

Plus the import at the top of the module. No other changes to
Contract 5's structure.

---

## 7. Spec-doc flag candidates (preview only — for §7 of spec)

Surfacing here as a checklist for the spec doc to address. The
final spec lists each with a recommendation + rejected
alternatives per the Contracts 1-7 flag format.

- **F0** — Sub-contract granularity (4 sub-contracts in one
  module per T5). PSL3 lean.
- **F1** — Persisted-extras disposition (type explicitly as
  Optional vs ``extra="ignore"`` per PSL4). T3 (a) finding.
  Spec recommends explicit typing for the 4 known extras +
  ``extra="ignore"`` to tolerate future drift.
- **F2** — Legacy fallback fields ``naics_code`` +
  ``business_naics`` per T3 (b). Either accept as Optional or
  R-residual cleanup the runner.py reads. Spec recommends
  ``extra="ignore"`` (no contract fields) + R-residual to delete
  runner.py defensive fallbacks pending a DB audit.
- **F3** — Stage label naming. Contracts 1-7 use boundary names
  (e.g., ``"INDUSTRY_BASELINE->AMALGAMATED_SESSION"``). Contract
  5b is a sub-contract, not a boundary — likely
  ``"INTAKE_DRAFT::operating_model_json"`` or similar. PSL5
  lean: no new gate, so the label only surfaces if a future
  direct gate site needs it.
- **F4** — ``extra`` policy on each sub-contract. PSL4 lean
  (``ignore`` on all 4 sub-contracts including top-level).
  Different from boundary contracts where top-level is
  ``forbid`` — appropriate because OpenAI schema may evolve and
  producer may legitimately add fields between schema versions.
- **F5** — Numeric constraints (``unit_price > 0`` per system
  prompt at intake_consultant.py:622, ``confidence`` range?
  ``utilization_rate ∈ [0, 1]`` per the system prompt's "decimal
  fraction" guidance). PSL2 production-reality lean. Spec
  recommends ``Field(gt=0)`` on unit_price + ``Field(ge=0, le=1)``
  on utilization_rate; defer confidence range pending audit.
- **F6** — Composition with Contract 5's fixtures. Updating
  Contract 5's test fixtures + 5b's new sub-contract fixtures
  must align. Spec covers this in §5 retrofit plan.
- **F7** — ``business_stage`` Literal? T1 finds the schema
  types it as ``["string", "null"]`` with no enum, but downstream
  consumers (runner.py:566) lowercase-and-strip it for
  comparison. Spec needs to decide whether to pin a Literal
  vocabulary (which would tighten beyond the schema, against
  PSL1) or keep as ``Optional[str]``. Lean: ``Optional[str]``
  (PSL1).

Expected ~6-8 flags in the spec.

---

## 8. Pre-spec residuals (for §8 of spec)

R-residuals surfaced by this trace, to fold into the spec's §8:

- **R-a.** ``naics_code`` + ``business_naics`` runner.py
  defensive fallbacks (T3 (b)). Audit DB for any draft with
  these fields; if zero hits, delete fallbacks; if non-zero,
  add Optional contract fields.
- **R-b.** ``confidence`` field range — schema is unbounded
  ``number`` per intake_consultant.py:154. Audit production
  values; pin a Literal or numeric range if cohort distribution
  warrants.
- **R-c.** ``unit_cadence`` enum schema mismatch: top-level
  declares ``enum: ["weekly", "monthly", "contract", None]``
  per intake_consultant.py:124 (NOTE: includes literal Python
  ``None`` in the enum list — this is a JSON-schema quirk; valid
  but unusual). Nested ProductContract enum is
  ``["weekly", "monthly", "contract"]`` (no None). Pre-1a
  re-verification: confirm both schemas in source verbatim.
- **R-d.** ``competitive_advantage`` production extra (T3 (a))
  is only set when ``comp_action == "confirm_proceed"`` — its
  absence is the common case. Spec must type it as Optional;
  document the trigger condition for future maintainers.
- **R-e.** ``_apply_model_ops_patch`` allowed_keys whitelist at
  intake_consult.py:917-937 contains 17 of the 23 schema fields
  (excludes business_stage, business_description_summary,
  milestones, confidence). Future R-residual: align whitelist
  with the typed contract roster.
- **R-f.** Contract 3 ``fact_template`` field-path declarations
  at post_intake_mapping.py:1825-1827 reference
  ``operating_model_json.business_type`` and similar paths.
  Once 5b lands, harmonize these path declarations against
  the typed OperatingModelJsonContract roster.

---

## 9. Workflow

Same pattern as Contracts 1-7: trace + spec each ship as single
commits, held for Nick review.

**This is the trace doc.** After Nick reviews, the spec doc
covers §1-9 above plus the field-by-field translation table
(§2 of spec). After spec approval, implementation lands per
the directive's 2-3 commit sequence:

- **Commit 5b-1:** OperatingModelJsonContract module + sub-sub-
  contracts + fixtures.
- **Commit 5b-2:** Sub-contract tests mirroring Contract 5's
  test patterns + update Contract 5 existing fixtures to use
  valid OperatingModelJsonContract-shaped values.
- **Commit 5b-3:** Retrofit IntakeDraftContract.operating_model_
  json field type ``Dict[str, Any]`` → ``OperatingModelJsonContract``.
  Update top-level Contract 5 tests + run full Contract 5 + 5b
  + cross-contract suites to confirm no regression.

**Pre-1a re-verification per Contracts 4-7 discipline.** Before
Commit 5b-1 lands, re-grep:
- intake_consultant.py:67-182 schema field roster + enum values
- intake_consult.py:917-937 allowed_keys whitelist
- runner.py:284-285 + 1090-1094 legacy fallback reads
to confirm spec values match production verbatim.

After 5b lands, proceed to 5c (target_market_json) and 5d
(people_json) — same pattern. Once all three land, Contract 6
R16 and Contract 7 R9 become actionable.
