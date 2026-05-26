"""OperatingModelJsonContract -- sub-contract retrofit for
IntakeDraftContract.operating_model_json.

Tightens the field type from ``Dict[str, Any]`` (Contract 5
F0 (b) first cut) to a typed 4-sub-contract shape matching the
OpenAI-schema-enforced payload produced by
``consultant_finalize`` at intake_consultant.py:583-684.

Spec: ``docs/architecture/p3_40_contract_5b_operating_model_json_spec.md``
(commit c332911, 729 LOC, 8 flags, 9 R-residuals).
Trace: ``docs/architecture/p3_40_contract_5b_operating_model_json_trace.md``
(commit 68caecc, 564 LOC, 5 trace tasks).

VALUE-CONSTRAINT POLICY (spec §0, load-bearing for 5b + 5c + 5d):
the contract types JSON SHAPE, not VALUES. Bare types only --
str / int / float / bool / List[Any] / Dict[str, Any]. No
Literal narrowing for enum vocabularies, no Field(min_length /
max_length / pattern / ge / le / gt / lt), no
@model_validator(mode='after') cross-field invariants, no
@field_validator content checks. Only structural typing.

Rationale: operating_model_json comes from intake. Intake data
varies STRUCTURALLY by business type -- a coffee shop produces
different content than a SaaS company than a service firm. Any
Pydantic content constraint creates false-positive
ContractViolations for business types where the value
legitimately doesn't fit. OpenAI's strict mode enforces
value-level rules upstream; Pydantic re-enforcing them
duplicates work AND introduces drift risk if the schema
evolves.

Exceptions enforced:
  - Field PRESENCE (required vs Optional per F7)
  - Nested object STRUCTURE (sub-contracts per T5)
  - extra='ignore' on every sub-contract (per F4)

Multi-shape boundary per F0 (a) / Contract 6+7 F0 pattern:
4 sub-contracts in a single module:

  Top-level -- OperatingModelJsonContract (27 typed fields:
    23 from the OpenAI schema + 4 production extras per T3).
  Nested -- LobModelContract (2 fields per
    intake_consultant.py:84-119).
  Nested -- ProductContract (9 fields per
    intake_consultant.py:91-115). Lives inside
    LobModelContract.products.
  Nested -- MilestoneContract (2 fields per
    intake_consultant.py:141-148).

extra-key policy per F4:
  - ``extra="ignore"`` on ALL 4 sub-contracts including
    top-level. Different from boundary contracts where top-level
    is ``forbid`` -- appropriate because operating_model_json is
    a SUB-CONTRACT of IntakeDraftContract (top-level forbid
    lives at the draft level, Contract 5 F6), and the OpenAI
    schema may legitimately add fields between schema versions.
  - ``extra="ignore"`` also covers the 2 legacy fallback fields
    (naics_code, business_naics) read defensively in
    runner.py:284-285 + 1093-1094 (R-a residual).

Required-vs-Optional disposition per F7:
  - 13 non-nullable required schema fields (consumer_type,
    business_type, business_description_summary,
    shipping_method, sales_modality, geographic_scope,
    geographic_coverage, countries, milestones,
    capacity_driver, primary_growth_lever, legal_entity,
    confidence) -> bare type, required (no default).
  - 10 nullable-required schema fields (business_stage,
    lob_models, unit_name, unit_description, unit_cadence,
    units_per_week_capacity, units_per_period_capacity,
    operating_periods_per_year, utilization_rate, unit_price)
    -> ``Optional[X] = None``. OpenAI strict mode guarantees
    KEY presence with possibly-null value; Optional[X] = None
    accommodates BOTH the current schema (key present, value
    null in multi-LOB case) AND legacy drafts that may pre-date
    the current schema and omit keys entirely. R-h R-residual
    covers tightening to ``Optional[X]`` (key-required +
    value-nullable) once a DB audit confirms no legacy
    omissions.
  - 4 production extras (business_naics_6,
    competitive_advantage, business_type_candidates,
    business_type_candidates_locked) -> ``Optional[X] = None``.
    Conditional per intake flow per T3 (a).

Enum vocabularies per F5 (REJECTED):
  - consumer_type, sales_modality, geographic_scope,
    capacity_driver, unit_cadence (top-level + nested in
    ProductContract) -- ALL type as bare ``str``. Per §0
    policy, Literal pinning is banned even though OpenAI
    schema enforces the enum upstream.

R-residuals deferred (spec §8):
  - R-a. DB audit + runner.py cleanup for legacy fallback
         fields (naics_code, business_naics).
  - R-b. confidence field range -- not enforced per §0.
  - R-c. unit_cadence enum-mismatch (top-level vs nested) --
         documentary only per §0.
  - R-d. competitive_advantage trigger condition documented in
         this docstring.
  - R-e. _apply_model_ops_patch allowed_keys whitelist
         (intake_consult.py:917-937) align with this roster.
  - R-f. Contract 3 fact_template field-path harmonization.
  - R-g. Downstream consumers upgrade to typed instance reads.
  - R-h. Tighten Optional[X]=None to Optional[X] for 10
         nullable-required fields once DB audit confirms no
         legacy omissions.
  - R-i. Contracts 6 R16 + 7 R9 unblocked once 5b + 5c + 5d
         all land.

No new gate site per spec §5.4. Contract 5's existing
consumer-side gate at runner.py:189 automatically tightens
via recursive ``model_validate`` once the field type changes
in Commit 5b-3.

No new PhaseCode / EventCode / FailFastCode. Diagnostics route
through the existing INTAKE_DRAFT_CONTRACT stack.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label exported for discoverability per F3. Sub-contract
#: is invoked through Contract 5's existing
#: INTAKE_DRAFT_STAGE_LABEL diagnostic stack; this label only
#: surfaces if a future direct gate site is added (PSL5
#: future-proof).
OPERATING_MODEL_JSON_STAGE_LABEL = "INTAKE_DRAFT::operating_model_json"


# ---------------------------------------------------------------------------
# ProductContract (9 fields per intake_consultant.py:91-115)
# ---------------------------------------------------------------------------

class ProductContract(BaseModel):
  """One product entry inside a LOB. Defined inside
  ``LobModelContract.products`` per the OpenAI schema's nested
  object structure.

  Per §0 policy: bare types only. ``unit_cadence`` schema enum
  (``weekly`` / ``monthly`` / ``contract``) NOT pinned to
  Literal -- accepts any string. ``unit_price`` system prompt
  says non-zero but per §0 NOT enforced via ``Field(gt=0)``.
  """

  product_name: str
  unit_name: str
  unit_description: str
  unit_cadence: str
  units_per_week_capacity: float
  units_per_period_capacity: float
  operating_periods_per_year: Optional[float] = None
  utilization_rate: Optional[float] = None
  unit_price: float

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# LobModelContract (2 fields per intake_consultant.py:84-119)
# ---------------------------------------------------------------------------

class LobModelContract(BaseModel):
  """One line-of-business entry. ``products`` types as
  ``List[ProductContract]`` per the schema's nested object
  array.

  Per §0 policy: ``minItems=1`` from the schema NOT enforced
  via ``Field(min_length=1)``.
  """

  lob_name: str
  products: List[ProductContract]

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# MilestoneContract (2 fields per intake_consultant.py:141-148)
# ---------------------------------------------------------------------------

class MilestoneContract(BaseModel):
  """One operational milestone."""

  description: str
  timing: str

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Top-level OperatingModelJsonContract (27 typed fields)
# ---------------------------------------------------------------------------

class OperatingModelJsonContract(BaseModel):
  """Operating-model intake payload per intake_consultant.py
  _final_schema() at intake_consultant.py:67-182. 23 required
  GPT-schema fields + 4 production extras (T3) = 27 typed fields.

  Field ordering grouped for readability:
    1. 13 non-nullable required schema fields (bare type, no default)
    2. 10 nullable-required schema fields (Optional[X] = None per F7)
    3. 4 production extras (Optional[X] = None per F1)

  Enum vocabularies (consumer_type / sales_modality /
  geographic_scope / capacity_driver / unit_cadence) all
  bare ``str`` per F5 / §0.

  Array fields (countries / milestones / lob_models /
  business_type_candidates) -- ``countries`` and
  ``business_type_candidates`` typed as ``List[Any]`` per §0
  (item-type pinning banned); ``milestones`` and ``lob_models``
  type as their nested sub-contracts per T5 (nested object
  STRUCTURE preserved).

  ``extra="ignore"`` per F4 accepts the 2 legacy fallback
  fields (naics_code, business_naics) per F2 + tolerates
  future schema-version drift.
  """

  # --- 13 non-nullable required GPT-schema fields ---
  consumer_type: str
  business_type: str
  business_description_summary: str
  shipping_method: str
  sales_modality: str
  geographic_scope: str
  geographic_coverage: str
  countries: List[Any]
  milestones: List[MilestoneContract]
  capacity_driver: str
  primary_growth_lever: str
  legal_entity: str
  confidence: float

  # --- 10 nullable-required GPT-schema fields (Optional[X] = None per F7) ---
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

  # --- 4 production extras (T3 -- NOT in GPT schema; Optional per F1) ---
  business_naics_6: Optional[str] = None
  competitive_advantage: Optional[str] = None
  business_type_candidates: Optional[List[Any]] = None
  business_type_candidates_locked: Optional[bool] = None

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "OPERATING_MODEL_JSON_STAGE_LABEL",
  "ProductContract",
  "LobModelContract",
  "MilestoneContract",
  "OperatingModelJsonContract",
]
