# P3.40 Contract 5c — TargetMarketJsonContract (Trace)

**Status:** Pre-spec trace doc. Spec follows after Nick reviews
this trace. No code lands from this commit.

**Scope:** Sub-contract retrofit for
``IntakeDraftContract.target_market_json`` (currently
``Dict[str, Any]`` per Contract 5 F0 (b) first cut). Tightens
the field type to a typed sub-contract matching the OpenAI-
schema-enforced shape produced by ``target_market_finalize`` at
[target_market_consultant.py:129-247](../../python/client_intake_and_finmo/target_market_consultant.py#L129).

**Parent contract:** Contract 5 — IntakeDraftContract (landed
end-to-end). Contract 5b retrofit (operating_model_json) landed
at fc91083 (suite: 575 passing). Contract 5c follows the SAME
pattern.

**Predecessors / siblings:**
- Contract 5 (commit series ending at the IntakeDraftContract
  consumer-side gate).
- Contract 5b ``OperatingModelJsonContract`` (4-sub-contract
  module landed at b7b8da6 + 662d2a1 + fc91083). Established
  the §0 value-constraint policy precedent applied here.

**Companion: §0 policy held verbatim from Contract 5b spec.**
Type STRUCTURE, not VALUES. All str fields bare str (no Literal
narrowing even when OpenAI schema enums); all list fields
``List[Any]``; all dict fields ``Dict[str, Any]``; all numbers
bare ``int`` / ``float`` / ``int|float``; all bool fields bare
``bool``. BANNED: Field constraints, Literal narrowing,
@model_validator cross-field, @field_validator content checks,
confloat/conint/constr.

**Unblocks downstream R-residuals (shared with 5b/5d):**
- Contract 6 R16 (industry baseline business-facts typing).
- Contract 7 R9 (Mirror.business_facts compose Contracts 5b/c/d).
Both become actionable once 5b + 5c + 5d all land.

**Pattern:** Retrofit (NOT new boundary contract). Per the
retrofit directive: no new PhaseCode / EventCode / FailFastCode;
no new gate site; existing Contract 5 enforcement stack covers
it. Per the established 5b precedent: small spec + 3-commit
implementation.

---

## 1. Trace task findings (T1-T5)

Five trace tasks per the Contract 5c directive. Headline
findings fold directly into the spec's §3 + §4 + §6.

### 1.1 Five headline findings

1. **The OpenAI schema is STRICT** (``additionalProperties:
   false`` + ``strict: True``). 11 required top-level fields at
   [target_market_consultant.py:233-244](../../python/client_intake_and_finmo/target_market_consultant.py#L233).
   7 of 11 fields are nullable per ``["array", "null"]`` typing
   (the b2b_* arrays + gender_age_intent + income_intent +
   selections).

2. **3 production extras NOT in the GPT schema** (analog to
   Contract 5b's 4 extras): CSV-string flattenings of the b2b_*
   array fields, added at persistence time. Schema-typed:
   - ``target_market_b2b_industry`` (CSV of ``b2b_naics_6``)
   - ``target_market_b2b_size`` (CSV of ``b2b_size_bands``)
   - ``target_market_b2b_age`` (CSV of ``b2b_age_bands``)
   Producers at
   [target_market.py:870-877 + 1181-1189](../../python/api_handlers/target_market.py#L870)
   (per T3 research). Consumer at
   [financials.py:122-155](../../python/api_handlers/financials.py#L122)
   reads them with FALLBACK derivation from the schema fields
   (if CSV missing, re-derive from list).

3. **3 nested object types** in the schema, each warrants its
   own typed sub-sub-contract per PSL3:
   - ``GenderAgeIntentEntry`` (3 fields: gender_focus, age_min,
     age_max)
   - ``IncomeIntentEntry`` (2 fields: income_min, income_max)
   - ``SelectionsEntry`` (2 fields: segment, acs_codes)
   The b2b_* arrays + b2b_industry_terms are flat arrays of
   strings (no nested objects); type as ``List[Any]`` per §0.

4. **Patch flow does NOT introduce extras.** ``_turn_schema()``
   at [target_market_consultant.py:250-309](../../python/client_intake_and_finmo/target_market_consultant.py#L250)
   carries per-turn patches with strict `additionalProperties:
   false` enforcement. The patch's ``properties`` whitelist
   excludes the 3 CSV extras entirely. Intent router's
   ``allowed_fields["target_market"]`` at
   intent_router.py:1451-1471 also excludes the extras. The 3
   CSV extras are regenerated from list fields at finalization
   only.

5. **No legacy-shape divergence detected.** Patches validated
   by OpenAI strict mode; edit-mode reruns ``target_market_
   finalize`` with full schema validation; fallback readers
   tolerate missing CSV extras gracefully. The contract roster
   is stable: 11 schema fields + 3 production extras = 14
   typed fields.

### 1.2 Trace divergences (folded into §3-4)

Per T3 the contract needs an explicit position on each
diverging field. §3 enumerates the contract roster; §4
enumerates per-field disposition.

---

## 2. T1 — OpenAI schema source location

**Primary location:**
[python/client_intake_and_finmo/target_market_consultant.py:129-247](../../python/client_intake_and_finmo/target_market_consultant.py#L129),
function ``_final_schema()``. Returns a wrapper dict with
``name`` + ``schema`` keys.

**Companion turn schema:**
[target_market_consultant.py:250-309](../../python/client_intake_and_finmo/target_market_consultant.py#L250)
``_turn_schema()``. Returns the per-turn ``{assistant_message,
finalize_ready, patch}`` shape. The ``patch`` field carries
PARTIAL target_market_json fields and is strictly whitelisted
to a subset of the final schema's fields. **The patch shape
does NOT introduce extras** (T3 finding 4).

**Persistence path:** ``target_market_finalize`` (analog to
Contract 5b's ``consultant_finalize``) returns a dict that
intake_consult.py + target_market.py post-processes (adds 3
CSV extras at lines [target_market.py:870-877 + 1181-1189](../../python/api_handlers/target_market.py#L870)),
then persists via ``append_messages(...target_market_json=
market_value...)`` at intake_consult.py many sites (per T1
grep: 32+ call sites — including 8121 read, 8256 / 9848 / 9880
/ 10830 / 10910 / 11103 writes).

**Lifecycle:** GPT call returns pristine 11-field payload →
target_market.py adds 3 CSV extras at finalize time →
persisted to DB → reload from DB on next turn → may patch via
``_turn_schema`` (only schema-listed fields) → re-finalize
regenerates CSVs. The shape at Contract 5's consumer-side gate
(runner.py:189) is the POST-FINALIZE shape with 3 CSV extras
present.

---

## 3. T2 — Field enumeration

11 required top-level fields per
target_market_consultant.py:233-244. Schema-level nullability
(``["X", "null"]``) determines Optional vs required.

### 3.1 Top-level fields (11 required)

| # | Field | Schema type | Optional? | Notes |
|---|---|---|---|---|
| 1 | ``consumer_type`` | ``string`` enum | required | enum: consumer / b2b / mixed |
| 2 | ``gender_age_intent`` | ``["array", "null"]`` of GenderAgeIntentEntry | Optional | nullable per schema |
| 3 | ``income_intent`` | ``["array", "null"]`` of IncomeIntentEntry | Optional | nullable per schema |
| 4 | ``selections`` | ``["array", "null"]`` of SelectionsEntry | Optional | nullable per schema |
| 5 | ``b2b_industry_terms`` | ``["array", "null"]`` of ``string`` | Optional | nullable; flat array |
| 6 | ``b2b_naics_6`` | ``["array", "null"]`` of ``string`` with pattern + minItems/maxItems | Optional | per §0 pattern + minItems + maxItems NOT enforced |
| 7 | ``b2b_size_bands`` | ``["array", "null"]`` of ``string`` enum | Optional | enum NOT pinned per §0 |
| 8 | ``b2b_age_bands`` | ``["array", "null"]`` of ``string`` enum | Optional | enum NOT pinned per §0 |
| 9 | ``target_market_summary`` | ``string`` | required | non-nullable |
| 10 | ``marketing_plan_summary`` | ``string`` | required | non-nullable |
| 11 | ``confidence`` | ``number`` | required | scalar (no min/max in schema) |

Field-count breakdown:
- **4 non-nullable required schema fields**: consumer_type,
  target_market_summary, marketing_plan_summary, confidence.
- **7 nullable-required schema fields**: gender_age_intent,
  income_intent, selections, b2b_industry_terms, b2b_naics_6,
  b2b_size_bands, b2b_age_bands.
- 4 + 7 = 11. ✓

### 3.2 Nested object — GenderAgeIntentEntry (3 fields per target_market_consultant.py:139-151)

| # | Field | Schema type | Optional? |
|---|---|---|---|
| 1 | ``gender_focus`` | ``string`` enum | required (enum: female / male / all NOT pinned per §0) |
| 2 | ``age_min`` | ``number`` | required |
| 3 | ``age_max`` | ``number`` | required |

### 3.3 Nested object — IncomeIntentEntry (2 fields per target_market_consultant.py:155-164)

| # | Field | Schema type | Optional? |
|---|---|---|---|
| 1 | ``income_min`` | ``number`` | required |
| 2 | ``income_max`` | ``number`` | required |

### 3.4 Nested object — SelectionsEntry (2 fields per target_market_consultant.py:167-184)

| # | Field | Schema type | Optional? |
|---|---|---|---|
| 1 | ``segment`` | ``string`` enum | required (enum: Education / Household Structure / Housing Economics / Employment NOT pinned per §0) |
| 2 | ``acs_codes`` | ``array`` of ``string`` | required (item-type pinning NOT enforced per §0 → ``List[Any]``) |

### 3.5 Enum vocabularies (documentary only — bare str per §0)

The schema lists 5 enum vocabularies. Per §0 / F5: ALL type as
bare ``str``. Documented here for completeness only:
- ``consumer_type``: consumer / b2b / mixed
- ``gender_focus`` (nested in GenderAgeIntentEntry): female /
  male / all
- ``segment`` (nested in SelectionsEntry): Education /
  Household Structure / Housing Economics / Employment
- ``b2b_size_bands`` (item enum): 1-4 / 5-9 / 10-19 / 20-99 /
  100-499 / 500-999 / 1000-2499 / 2500-4999 / 5000-9999 / 10000+
- ``b2b_age_bands`` (item enum): 0 / 1 / 2 / 3 / 4 / 5 / 6-10 /
  11-15 / 16-20 / 21-25 / 26+

### 3.6 Schema constraints to BAN per §0

These appear in the schema and must NOT translate to Pydantic
constraints:
- ``b2b_naics_6.items.pattern: "^[0-9]{6}$"`` — pattern NOT
  enforced. Items type as ``Any``.
- ``b2b_naics_6.minItems: 1, maxItems: 20`` — list-length NOT
  enforced.
- All enum vocabularies — Literal narrowing BANNED. Bare ``str``.

---

## 4. T3 — Production-reality verification (CRITICAL)

Same level of scrutiny as Contract 5b T3. Production
target_market_json shape diverges from the GPT schema in 1 way
(extras only). No legacy drift detected.

### 4.1 (a) Persisted extras NOT in the GPT schema

3 CSV-string extras added at finalize time, BEFORE persistence:

| # | Field | Producer site | Type | Trigger |
|---|---|---|---|---|
| 1 | ``target_market_b2b_industry`` | target_market.py:870, 1181 | ``str`` (CSV) | Joined from ``sorted(b2b_naics_6)`` |
| 2 | ``target_market_b2b_size`` | target_market.py:876, 1188 | ``str`` (CSV) | Joined from ``b2b_size_bands`` in canonical order |
| 3 | ``target_market_b2b_age`` | target_market.py:877, 1189 | ``str`` (CSV) | Joined from ``b2b_age_bands`` in canonical order |

These are RETROFIT COMPATIBILITY FIELDS for flat-column SQL
persistence (the ``intake_consult_drafts`` table stores them as
separate columns per
[intake_submission.py:107-109, 187-189](../../python/api_handlers/intake_submission.py#L107) —
T3 finding).

**Spec decision (F-flag preview):** type the 3 extras
explicitly as Optional contract fields per the Contracts 5b
precedent (F1) — Discoverability win for future maintainers.

### 4.2 (b) Patch flow does NOT introduce extras

The ``_turn_schema()`` per-turn patch at
target_market_consultant.py:250-309 has
``additionalProperties: false`` with a strict properties
whitelist of just 6 fields (``consumer_type``,
``gender_age_intent``, ``income_intent``,
``b2b_industry_terms``, ``b2b_size_bands``, ``b2b_age_bands``).
The 3 CSV extras are NOT in the patch schema.

Intent router's ``allowed_fields["target_market"]`` at
intent_router.py:1451-1471 similarly excludes the 3 CSV
extras. Patches cannot introduce new keys.

The 3 CSV extras are regenerated from list fields at
``target_market_finalize`` time, ensuring CSV-vs-list
consistency post-finalize.

### 4.3 (c) No legacy drift detected

Per T3 research:
- Turn patches validated by OpenAI strict mode (no extras).
- Edit-mode reruns ``target_market_finalize()`` with full
  schema validation, regenerating CSVs.
- Fallback readers (financials.py:122-155) handle missing CSV
  extras gracefully (re-derive from list fields).
- ``intake_submission.py:240-263`` enforces CSV-field presence
  for b2b/mixed at submission time; nulls them for
  consumer-only.

**Conclusion:** post-load shape stable; 11 schema fields + 3
CSV extras = 14 typed contract fields. Legacy-draft risk is
minimal but R-residual cleanup follows the 5b R-h pattern
(audit before tightening).

### 4.4 (d) No downstream defensive-fallback fields beyond extras

Unlike 5b's runner.py legacy fallbacks (``naics_code`` /
``business_naics``), the only downstream "fallback" read for
target_market_json is the financials.py:122-155 derivation
of the 3 CSV extras from the schema list fields. That's
fallback to SCHEMA FIELDS, not to unrecognized legacy fields
— so the contract doesn't need to accommodate additional
unknown keys beyond the 3 enumerated CSV extras.

---

## 5. T4 — Downstream consumers

Per the directive: identify who reads target_market_json fields
after Contract 5's gate.

### 5.1 Reader inventory

| File | Lines | What's read | Pattern |
|---|---|---|---|
| [runner.py:212](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L212) | parse_json_dict | Full blob | Loaded into ``draft_data`` |
| [runner.py:236](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L236) | ``market_json`` local re-parse | Full blob | Local handle for downstream calls |
| [runner.py:289, 388, 965, 1603, 1912, 1948](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L289) | Full blob copied | ``copy.deepcopy(market_json or {})`` | Passed to downstream as-is |
| [post_intake_mapping.py:701, 872, 1061, 1091, 1379](../../python/client_intake_and_finmo/post_intake_mapping.py#L701) | Required-context-key declarations | Full blob | GPT prompt block registration |
| [post_intake_mapping.py:1829](../../python/client_intake_and_finmo/post_intake_mapping.py#L1829) | ``target_market_json`` derived-fact source path | Path declaration | Fact-template renderer |
| [financials.py:122-155](../../python/api_handlers/financials.py#L122) | ``target_market_b2b_industry``, ``target_market_b2b_size``, ``target_market_b2b_age``, ``b2b_naics_6``, ``b2b_size_bands``, ``b2b_age_bands`` | Field-by-field | API-handler validates CSV-extras presence for b2b/mixed; falls back to list-derivation if missing |
| [intake_submission.py:107-109, 187-189](../../python/api_handlers/intake_submission.py#L107) | The 3 CSV extras + b2b_* lists | Required column writes | flat_fields persistence |
| [intake_submission.py:240-263](../../python/api_handlers/intake_submission.py#L240) | The 3 CSV extras | Presence validation | Reject submission if missing for b2b/mixed |

### 5.2 Composition opportunity

- Contract 5b (operating_model_json): no composition. Disjoint
  field sets.
- Contract 5d (people_json): no composition. Disjoint.
- Contract 3 ``fact_template``: similar to 5b, references
  target_market_json field paths via fact placeholders — no
  direct embedding. Harmonize as R-residual when 5b/c/d all
  land.
- Contract 6 R16 / Contract 7 R9 unblocked once 5b + 5c + 5d
  all land.

### 5.3 Retrofit non-breaking

Per 5b precedent: typed sub-contract is a subset of
``Dict[str, Any]``. Existing downstream consumers read
field-by-field via ``market_json.get(...)`` — duck-typed dict
access. After retrofit:
- Pydantic returns ``TargetMarketJsonContract`` instance at the
  gate; Contract 5's downstream code reads from the raw dict at
  runner.py:236 (``market_json = parse_json_dict(...)``).
- Gate validates IntakeDraftContract then discards the
  validated instance; raw dict continues downstream unchanged.
- So downstream consumers see the same Dict[str, Any].

R-residual (5b R-g analog): upgrade downstream consumers to
typed instance reads post-landing.

---

## 6. T5 — Sub-contract structure decision

### 6.1 Field-count breakdown

- Top-level: 11 schema fields + 3 production extras = 14
  typed fields
- ``GenderAgeIntentEntry``: 3 fields
- ``IncomeIntentEntry``: 2 fields
- ``SelectionsEntry``: 2 fields

Total nesting depth: 1 level (top → list-of-entry-objects).
Simpler than 5b which had 2 levels (OperatingModelJsonContract
→ LobModelContract → ProductContract).

### 6.2 Sub-contract granularity recommendation

**4 sub-contracts in a single module** (mirrors Contract 5b F0
pattern):

```
TargetMarketJsonContract     <- top-level, 14 typed fields
  ├── gender_age_intent: Optional[List[GenderAgeIntentEntry]]
  ├── income_intent: Optional[List[IncomeIntentEntry]]
  ├── selections: Optional[List[SelectionsEntry]]
  ├── b2b_industry_terms: Optional[List[Any]]    <- flat string array; no sub-contract
  ├── b2b_naics_6: Optional[List[Any]]           <- flat string array; no sub-contract
  ├── b2b_size_bands: Optional[List[Any]]        <- flat string array; no sub-contract
  ├── b2b_age_bands: Optional[List[Any]]         <- flat string array; no sub-contract
  └── (3 CSV extras + 4 non-nullable required + confidence)
```

3 sub-sub-contracts: ``GenderAgeIntentEntry``,
``IncomeIntentEntry``, ``SelectionsEntry``. Same-module pattern
per the F0 single-module multi-shape precedent. Module:
``python/client_intake_and_finmo/post_intake_contracts/target_market_json_contract.py``.

Re-imported into intake_draft_contract.py so the retrofit field
type change is a single-line edit.

### 6.3 Module-level constants

```python
TARGET_MARKET_JSON_STAGE_LABEL = "INTAKE_DRAFT::target_market_json"
```

No enum tuples (no Literal[...] per §0 means no exported
vocabularies to pin).

### 6.4 Composition with IntakeDraftContract

Single-line retrofit at
[intake_draft_contract.py:175](../../python/client_intake_and_finmo/post_intake_contracts/intake_draft_contract.py#L175):

```python
# Before:
target_market_json: Dict[str, Any]

# After:
target_market_json: TargetMarketJsonContract
```

Plus the import at the top of the module. No other changes to
Contract 5's structure.

### 6.5 Expected module LOC

150-300. Per §0 policy elimination of ~80% of typical Pydantic
boilerplate (no Field constraints, no validators, no Literal
vocabularies). 11 schema fields + 3 extras + 3 small nested
sub-contracts → smaller than 5b's 274 LOC.

---

## 7. Spec-doc flag candidates (preview only — for §7 of spec)

Surfacing here as a checklist for the spec doc. Final spec
lists each with a recommendation + rejected alternatives per
the Contracts 1-7 + 5b flag format.

- **F0** — Sub-contract granularity (4 sub-contracts in one
  module per T5). PSL3 lean.
- **F1** — Persisted-extras disposition (type the 3 CSV extras
  explicitly as Optional vs ``extra="ignore"`` alone per PSL4).
  T3 (a) finding. Spec recommends explicit typing (matches 5b
  F1 precedent).
- **F2** — No legacy fallback fields (T3 (d) finding). Differs
  from 5b F2 which had ``naics_code`` / ``business_naics``
  defensive reads. Spec recommends ``extra="ignore"`` for
  future drift but no R-residual cleanup needed (no defensive
  reads to remove).
- **F3** — Stage label naming. ``TARGET_MARKET_JSON_STAGE_LABEL =
  "INTAKE_DRAFT::target_market_json"`` per 5b F3 pattern.
- **F4** — ``extra`` policy on each sub-contract. PSL4 lean
  (``ignore`` on all 4). Same as 5b F4.
- **F5** — Value-level constraints (schema pattern on
  b2b_naics_6, minItems/maxItems on b2b_naics_6, enum on 5
  vocabularies). Per §0: ALL REJECTED. b2b_naics_6 items type
  as ``Any`` (NOT ``str`` with pattern); array length NOT
  bounded; all enums type as bare ``str``.
- **F6** — Composition with Contract 5's fixtures. Updating
  Contract 5's test fixtures + 5c's new sub-contract fixtures
  must align (per 5b F6 precedent).
- **F7** — Required-vs-Optional disposition for the 7 nullable-
  required schema fields (gender_age_intent, income_intent,
  selections, b2b_industry_terms, b2b_naics_6, b2b_size_bands,
  b2b_age_bands). Same as 5b F7: ``Optional[X] = None`` for
  legacy-draft safety; R-residual to tighten once DB audit
  confirms.
- **F8** — ``acs_codes`` typing inside SelectionsEntry. Schema
  says ``array of string``. Per §0: type as ``List[Any]`` (no
  item-type pinning). Documentary flag.

Expected total: 8 flags. None require ``Literal`` /
``Field(constraint)`` / validators per §0.

---

## 8. Pre-spec residuals (for §8 of spec)

R-residuals surfaced by this trace, to fold into the spec's §8:

- **R-a.** No DB audit needed for legacy fallback fields (T3
  (d): no defensive reads beyond the 3 CSV extras themselves).
  Differs from 5b R-a which had naics_code / business_naics.
- **R-b.** ``confidence`` field range — schema is unbounded
  ``number``. Per §0 no range constraint. Same pattern as 5b
  R-b.
- **R-c.** ``acs_codes`` item-type pinning deferred per §0. If
  a future consumer requires strict string-only validation,
  add at the consumer site (out of contract scope).
- **R-d.** ``b2b_naics_6`` pattern (``^[0-9]{6}$``) +
  minItems/maxItems deferred per §0. Pattern validation
  belongs in domain code (e.g., financials.py during NAICS
  resolution), not the contract.
- **R-e.** ``_turn_schema()`` patch-shape harmonization — patch
  whitelist at target_market_consultant.py:262-294 covers 6
  of the 14 contract fields. Align whitelist with typed
  contract roster post-landing (5b R-e analog).
- **R-f.** Contract 3 ``fact_template`` field-path declarations
  at post_intake_mapping.py:1829 reference
  ``target_market_json`` paths. Harmonize against typed
  contract roster post-landing (5b R-f analog).
- **R-g.** Upgrade downstream consumers (runner.py + financials.py +
  post_intake_mapping.py) to read from the typed
  TargetMarketJsonContract instance rather than the raw dict
  at runner.py:236 (5b R-g analog).
- **R-h.** Tighten ``Optional[X] = None`` to ``Optional[X]``
  for 7 nullable-required schema fields once a DB audit
  confirms no legacy omissions (5b R-h analog).
- **R-i.** Contracts 6 R16 + 7 R9 unblocked once 5b + 5c + 5d
  all land (shared with 5b).

---

## 9. Workflow

Same pattern as Contracts 1-7 + 5b: trace + spec each ship as
single commits, held for Nick review.

**This is the trace doc.** After Nick reviews, the spec doc
covers §0-9 (§0 = value-constraint policy held verbatim from
5b; §1-9 follows the 5b spec template).

After spec approval, implementation lands per the 3-commit
sequence (5b precedent):
- **Commit 5c-1:** TargetMarketJsonContract module + sub-sub-
  contracts + fixtures.
- **Commit 5c-2:** Sub-contract tests mirroring 5b test
  patterns. Expected 15-25 tests.
- **Commit 5c-3:** Retrofit IntakeDraftContract.target_market_
  json field type ``Dict[str, Any]`` → ``TargetMarketJsonContract``.
  Update Contract 5 existing fixtures + tests. Run full Contract
  5 + 5b + 5c + cross-contract suites. Expected suite delta
  575 → ~595-605.

**Pre-1a re-verification per Contracts 4-7 + 5b discipline.**
Before Commit 5c-1 lands, re-grep:
- target_market_consultant.py:233-244 schema required[] list
- target_market.py:870-877 + 1181-1189 CSV-extra producer sites
- financials.py:122-155 CSV-extra consumer site
to confirm spec values match production verbatim.

After 5c lands, proceed to 5d (people_json) — same §0 policy.
Once 5b + 5c + 5d all land, Contracts 6 R16 + 7 R9 become
actionable.

If during Commit 5c-1 anything diverges from production, flag
back the same way Contracts 1-7 + 5b did — no silent
adjustment.
