"""TargetMarketJsonContract -- sub-contract retrofit for
IntakeDraftContract.target_market_json.

Tightens the field type from ``Dict[str, Any]`` (Contract 5
F0 (b) first cut) to a typed 4-sub-contract shape matching the
OpenAI-schema-enforced payload produced by
``target_market_finalize`` at target_market_consultant.py:129-247.

Spec: ``docs/architecture/p3_40_contract_5c_target_market_json_spec.md``
(commit 815dfba, 710 LOC, 8 flags, 9 R-residuals).
Trace: ``docs/architecture/p3_40_contract_5c_target_market_json_trace.md``
(commit 9196663, 529 LOC, 5 trace tasks).

VALUE-CONSTRAINT POLICY (spec §0, held verbatim from Contract
5b for 5b + 5c + 5d uniformly): the contract types JSON SHAPE,
not VALUES. Bare types only -- str / int / float / bool /
List[Any] / Dict[str, Any]. No Literal narrowing for enum
vocabularies, no Field(min_length / max_length / pattern / ge /
le / gt / lt), no @model_validator(mode='after') cross-field
invariants, no @field_validator content checks.

Rationale: target_market_json comes from intake. Target-market
data varies STRUCTURALLY by business type -- a consumer-only
coffee shop produces different content than a b2b SaaS company
than a b2b/mixed franchise. Any Pydantic content constraint
creates false-positive ContractViolations for business types
where the value legitimately doesn't fit. OpenAI's strict mode
enforces value-level rules upstream; the per-turn patch schema
at target_market_consultant.py:250-309 is strictly whitelisted
(no extras drift); target_market_finalize regenerates the 3
CSV extras at finalize time; downstream financials.py
fallback-derives missing CSVs from list fields. Pydantic
re-enforcing duplicates work AND introduces drift risk.

Exceptions enforced:
  - Field PRESENCE (required vs Optional per F6)
  - Nested object STRUCTURE (sub-contracts per T5 / F7+F8)
  - extra='ignore' on every sub-contract (per F3)

Multi-shape sub-contract per F0 (a) / Contract 5b F0 +
6+7 F0 pattern: 4 sub-contracts in a single module.

  Top-level -- TargetMarketJsonContract (14 typed fields: 11
    from the OpenAI schema + 3 production extras per T3).
  Nested -- GenderAgeIntentEntry (3 fields per
    target_market_consultant.py:139-151). Lives inside
    TargetMarketJsonContract.gender_age_intent.
  Nested -- IncomeIntentEntry (2 fields per
    target_market_consultant.py:155-164). Lives inside
    TargetMarketJsonContract.income_intent.
  Nested -- SelectionsEntry (2 fields per
    target_market_consultant.py:167-184). Lives inside
    TargetMarketJsonContract.selections.

The 4 flat b2b_* arrays (b2b_industry_terms, b2b_naics_6,
b2b_size_bands, b2b_age_bands) type as ``Optional[List[Any]] =
None`` -- per §0 item-type pinning BANNED (the schema's enum
constraints on items + b2b_naics_6 pattern + minItems=1 +
maxItems=20 ALL REJECTED per §0).

extra-key policy per F3:
  - ``extra="ignore"`` on ALL 4 sub-contracts including
    top-level. Sub-contracts at this layer tolerate
    schema-version drift; top-level forbid lives at the draft
    level (Contract 5 F6).

Required-vs-Optional disposition per F6 + F1:
  - 3 non-nullable required schema fields (consumer_type,
    marketing_plan_summary, confidence) -> bare type, required
    (no default).
  - 1 schema-required-but-production-popped per F1 / PSL2:
    ``target_market_summary`` -> ``Optional[str] = None``.
    Mirror of people_json ``key_people_summary``. Schema marks
    REQUIRED; intake_consult.py:10863 POPS before persistence
    (same single-source-of-truth pattern as commit e57ff49).
    Production drafts NEVER carry this field; typing as required
    would fail 100% of production runs (surfaced by NexGen E2E).
    R-d-bis contract-typing portion RESOLVED; gate portion still
    DEFERRED to intake-remediation workstream.
  - 7 nullable-required schema fields (gender_age_intent,
    income_intent, selections, b2b_industry_terms, b2b_naics_6,
    b2b_size_bands, b2b_age_bands) -> ``Optional[X] = None``.
    OpenAI strict mode guarantees KEY presence with possibly-
    null value; Optional[X] = None accommodates BOTH the
    current schema AND legacy drafts. R-g R-residual covers
    tightening to ``Optional[X]`` (key-required + value-nullable)
    post DB audit.
  - 3 production extras (target_market_b2b_industry,
    target_market_b2b_size, target_market_b2b_age per T3) ->
    ``Optional[str] = None``. CSV-joined at
    target_market_finalize time per
    target_market.py:870-877 + 1181-1189.

Enum vocabularies per F4 (REJECTED):
  - consumer_type (consumer / b2b / mixed)
  - gender_focus inside GenderAgeIntentEntry (female / male /
    all)
  - segment inside SelectionsEntry (Education / Household
    Structure / Housing Economics / Employment)
  - b2b_size_bands items (1-4 / 5-9 / 10-19 / ... / 10000+)
  - b2b_age_bands items (0 / 1 / ... / 26+)
  ALL type as bare ``str``. Per §0 policy, Literal pinning is
  banned even though OpenAI schema enforces the enum upstream.

Schema constraints BANNED per §0 / F4:
  - b2b_naics_6 items pattern (``^[0-9]{6}$``) -> items type
    as ``Any`` (item-type pinning banned)
  - b2b_naics_6 minItems=1 + maxItems=20 -> list-length NOT
    bounded
  - acs_codes inside SelectionsEntry: items type as ``Any``
    (per F8 documentary)

R-residuals deferred (spec §8):
  - R-a. confidence field range -- not enforced per §0
         (matches 5b R-b).
  - R-b. acs_codes item-type pinning deferred per §0.
  - R-c. b2b_naics_6 pattern + minItems/maxItems deferred per
         §0. Belongs in domain code (financials.py during NAICS
         resolution), not the contract layer.
  - R-d. _turn_schema() patch-shape harmonization with this
         roster (matches 5b R-e).
  - R-e. Contract 3 fact_template field-path harmonization
         (matches 5b R-f).
  - R-f. Downstream consumers upgrade to typed instance reads
         (matches 5b R-g).
  - R-g. Tighten Optional[X]=None to Optional[X] for 7
         nullable-required fields once DB audit confirms (5b
         R-h).
  - R-h. Conditional-required CSV-extras enforcement
         (consumer_type in {"b2b", "mixed"} implies the 3
         target_market_b2b_* fields present) currently
         enforced at intake_submission.py:240-263. Document
         only; do NOT enforce at this contract layer per §0.
  - R-i. Contracts 6 R16 + 7 R9 unblocked once 5b + 5c + 5d
         all land.

No new gate site per spec §5.4. Contract 5's existing
consumer-side gate at runner.py:189 automatically tightens
via recursive ``model_validate`` once the field type changes
in Commit 5c-3.

No new PhaseCode / EventCode / FailFastCode. Diagnostics route
through the existing INTAKE_DRAFT_CONTRACT stack (per F2: no
new stage label; existing INTAKE_DRAFT_STAGE_LABEL covers
retrofit).
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label exported for discoverability per spec §3.1. Sub-
#: contract is invoked through Contract 5's existing
#: INTAKE_DRAFT_STAGE_LABEL diagnostic stack; this label only
#: surfaces if a future direct gate site is added (PSL5
#: future-proof, 5b precedent).
TARGET_MARKET_JSON_STAGE_LABEL = "INTAKE_DRAFT::target_market_json"


# ---------------------------------------------------------------------------
# GenderAgeIntentEntry (3 fields per target_market_consultant.py:139-151)
# ---------------------------------------------------------------------------

class GenderAgeIntentEntry(BaseModel):
  """One gender-age intent entry. 3 fields per
  target_market_consultant.py:139-151.

  Per §0 policy: ``gender_focus`` schema enum (female / male /
  all) NOT pinned to Literal -- accepts any string. age_min <=
  age_max cross-field invariant REJECTED per §0 (content-level
  check banned).
  """

  gender_focus: str
  age_min: float
  age_max: float

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# IncomeIntentEntry (2 fields per target_market_consultant.py:155-164)
# ---------------------------------------------------------------------------

class IncomeIntentEntry(BaseModel):
  """One income-intent entry. 2 fields per
  target_market_consultant.py:155-164.

  Per §0 policy: income_min <= income_max cross-field invariant
  REJECTED (content-level check banned).
  """

  income_min: float
  income_max: float

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# SelectionsEntry (2 fields per target_market_consultant.py:167-184)
# ---------------------------------------------------------------------------

class SelectionsEntry(BaseModel):
  """One segment-selection entry. 2 fields per
  target_market_consultant.py:167-184.

  Per §0 policy: ``segment`` schema enum (Education / Household
  Structure / Housing Economics / Employment) NOT pinned;
  ``acs_codes`` inner array typed as ``List[Any]`` per F8 (item-
  type pinning BANNED even though the schema says items are
  strings).
  """

  segment: str
  acs_codes: List[Any]

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Top-level TargetMarketJsonContract (14 typed fields)
# ---------------------------------------------------------------------------

class TargetMarketJsonContract(BaseModel):
  """Target-market intake payload per
  target_market_consultant.py _final_schema() at
  target_market_consultant.py:129-247. 11 required GPT-schema
  fields + 3 production extras (T3) = 14 typed fields.

  Field ordering grouped for readability:
    1. 3 non-nullable required schema fields (bare type, no default)
    2. 1 schema-required-but-production-popped field
       (target_market_summary, Optional[str] = None per F1 / PSL2)
    3. 7 nullable-required schema fields (Optional[X] = None per F6)
    4. 3 production extras (Optional[str] = None per F1)

  Enum vocabularies (consumer_type / gender_focus inside
  GenderAgeIntentEntry / segment inside SelectionsEntry /
  b2b_size_bands items / b2b_age_bands items) all bare ``str``
  per F4 / §0.

  b2b_naics_6 schema pattern (``^[0-9]{6}$``) + minItems=1 +
  maxItems=20 NOT enforced per §0 / F4 -- items type as
  ``Any``; list-length NOT bounded.

  Nested object lists keep typed sub-contract structure per F7:
    - gender_age_intent: List[GenderAgeIntentEntry]
    - income_intent: List[IncomeIntentEntry]
    - selections: List[SelectionsEntry]
  Flat string arrays type as List[Any] (no sub-contract):
    - b2b_industry_terms / b2b_naics_6 / b2b_size_bands /
      b2b_age_bands

  ``extra="ignore"`` per F3 tolerates future schema-version
  drift.
  """

  # --- 3 non-nullable required GPT-schema fields ---
  consumer_type: str
  marketing_plan_summary: str
  confidence: float

  # --- 1 schema-required-but-production-popped per F1 / PSL2 ---
  #: Schema lists as REQUIRED. intake_consult.py:10863 pops the
  #: field before persistence to draft (mirrors people_json
  #: key_people_summary pop at intake_consult.py:6241). Production
  #: payloads NEVER carry this field. Typing as required would fail
  #: 100% of production runs (surfaced by NexGen E2E run -- contract
  #: fired at this line against real production payload). Per PSL2
  #: production-reality-wins: type as Optional[str] = None despite
  #: schema-required. Mirror of people_json key_people_summary at
  #: people_json_contract.py:294. R-d-bis contract-typing portion
  #: now RESOLVED; gate portion (financials.py + intake_submit_service
  #: gate-reads) still DEFERRED to intake-remediation workstream.
  target_market_summary: Optional[str] = None

  # --- 7 nullable-required GPT-schema fields (Optional[X] = None per F6) ---
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


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "TARGET_MARKET_JSON_STAGE_LABEL",
  "GenderAgeIntentEntry",
  "IncomeIntentEntry",
  "SelectionsEntry",
  "TargetMarketJsonContract",
]
