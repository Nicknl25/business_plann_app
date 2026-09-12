"""PeopleJsonContract -- sub-contract retrofit for
IntakeDraftContract.people_json.

Tightens the field type from ``Dict[str, Any]`` (Contract 5
F0 (b) first cut) to a typed 3-sub-contract shape matching the
OpenAI-schema-enforced payload produced by
``people_capability_finalize`` at
people_capability_consultant.py:80-147.

**FINAL sub-contract retrofit in the 5b/5c/5d series.** After
Commit 5d-3 lands, Boundary 1 (INTAKE -> POST_INTAKE) has all
3 OpenAI-schema-enforced fields (operating_model_json /
target_market_json / people_json) structurally typed beyond
opaque Dict[str, Any] under the §0 structural-typing-only
policy.

Spec: ``docs/architecture/p3_40_contract_5d_people_json_spec.md``
(commit 40d974d, 746 LOC, 9 flags, 9 R-residuals).
Trace: ``docs/architecture/p3_40_contract_5d_people_json_trace.md``
(commit 0761191, 576 LOC, 5 trace tasks).

VALUE-CONSTRAINT POLICY (spec §0, held verbatim from Contracts
5b + 5c for 5b + 5c + 5d uniformly): the contract types JSON
SHAPE, not VALUES. Bare types only -- str / int / float / bool
/ List[Any] / Dict[str, Any]. No Literal narrowing for enum
vocabularies, no Field(min_length / max_length / pattern / ge /
le / gt / lt), no @model_validator(mode='after') cross-field
invariants, no @field_validator content checks.

Rationale: people data varies STRUCTURALLY by business type --
a sole proprietor's people array differs from a 50-person
franchise's; an early-stage business has different
inferred_roles than an operating one. Any Pydantic content
constraint creates false-positive ContractViolations for
business types where the value legitimately doesn't fit.
OpenAI's strict mode enforces value-level rules upstream;
intake_consult.py post-process generates inferred_roles_summary
+ cross-flows business_naics_6 + pops key_people_summary;
downstream code (post_intake_headcount/schedule.py +
financials.py + people_roles.py) handles per-field reads with
defensive fallbacks. Pydantic re-enforcing duplicates work AND
introduces drift risk.

Exceptions enforced:
  - Field PRESENCE (required vs Optional per F6 + F1 + F7)
  - Nested object STRUCTURE (sub-contracts per T5)
  - extra='ignore' on every sub-contract (per F3)
  - ``wage_source`` IS AN ENUM (Nick 2026-09-11). See below.

§0 IS DELIBERATELY REVERSED FOR ONE FIELD - READ THIS BEFORE
UNDOING IT. The policy above says no enum narrowing and no
@field_validator content checks, and F9 applied it to
``wage_source`` specifically: "the vocabulary is documented but
NOT pinned in the schema as an enum -- type as bare str". That
permissiveness had a cost, paid by a client.

On 2026-09-11 the intent router emitted a people row carrying
``wage_source: "client_reported"`` - a token NO python in this
repo writes, invented by the model on that turn. Nothing
rejected it, because a bare ``str`` accepts anything. Downstream,
people_roles.py protected a client's stated wage only when the
token was one of three exact spellings, so the guard missed, the
OEWS lookup ran, and Dr. Tobias Pelletier's stated $186,000 was
replaced by $102,870 - the 75th percentile for his own
occupation. That figure reached the delivered plan and the
workbook the client received.

Nick's ruling: "Provenance becomes an enum validated at the
boundary, not a free-text token GPT can invent - client_reported
was never a real value and nothing rejected it."

The rationale above still holds for every OTHER field: people
data varies structurally and a value constraint would
false-positive. It does NOT hold here, because ``wage_source``
is not client data at all - it is OUR provenance label about
client data, written by this codebase, with a closed set of
legal values. An open vocabulary on that field is not tolerance,
it is an unvalidated key.

The validator NORMALIZES rather than rejects: every known
synonym folds to the canonical token and an unrecognised one
resolves protectively (see person_identity.normalize_wage_source
for why the two failure directions are not symmetric). So a
stored draft carrying a legacy spelling still validates - this
change cannot strand a live run at INTAKE->POST_INTAKE, which a
strict Literal would have done to every draft on file.

Multi-shape sub-contract per F0 (a) / Contract 5b/5c F0 +
Contracts 6+7 F0 pattern: 3 sub-contracts in a single module.

  Top-level -- PeopleJsonContract (6 typed fields: 4 always-
    present + 1 nullable-required + 1 production-popped per
    T3 / F1).
  Nested -- PersonContract (9 fields per
    people_capability_consultant.py:94-114). Lives inside
    PeopleJsonContract.people.
  Nested -- InferredRoleContract (5 fields per
    people_capability_consultant.py:124-131). Lives inside
    PeopleJsonContract.inferred_roles.

extra-key policy per F3 + F2:
  - ``extra="ignore"`` on ALL 3 sub-contracts including
    top-level. Sub-contracts at this layer tolerate
    schema-version drift; top-level forbid lives at the draft
    level (Contract 5 F6).
  - PersonContract ``extra="ignore"`` ALSO accepts the legacy
    person-item fallback fields (``role`` / ``name`` /
    ``months_until_hire``) that post_intake_headcount/schedule.py:
    693-706 defensively reads. These are NOT in the GPT
    schema; analog to 5b's runner.py legacy fallbacks
    (naics_code / business_naics). R-b R-residual covers
    cleaning up the downstream defensive read chain.

Required-vs-Optional disposition per F6 + F1 + F7:
  - 4 always-present per persistence reality: bare type,
    required (no default).
    * ``people`` (List[PersonContract])
    * ``inferred_roles`` (List[InferredRoleContract])
    * ``inferred_roles_summary`` (str -- post-process generated
      at intake_consult.py:6231 via format_roles_summary;
      fallback "" at :6235-6236 ensures always present)
    * ``confidence`` (float)
  - 1 nullable-required schema field per F7:
    ``business_naics_6`` -> ``Optional[str] = None``. Cross-
    flow from ops_json at intake_consult.py:6228. Per F7 (a)
    accommodates OpenAI strict-mode KEY-present-value-null
    AND legacy drafts that may omit keys entirely.
  - 1 schema-required-but-production-popped per F1 / PSL2:
    ``key_people_summary`` -> ``Optional[str] = None``. The
    LOAD-BEARING PSL2 case of the 5b/5c/5d series. Schema
    marks it REQUIRED; intake_consult.py:6241 POPS it before
    persistence. Production drafts NEVER carry this field.
    Typing as required would fail 100% of production runs.

Enum vocabularies (NONE in schema -- simpler than 5b/5c):
  - The ``wage_source`` vocabulary on PersonContract +
    InferredRoleContract (client_override / gpt_estimate /
    unknown) is documented at people_capability_consultant.py:
    218-221 but is NOT pinned in the JSON schema as an enum.
    Per F9: type as bare ``str`` -- the absence of schema
    enum makes this trivial.

Schema constraints BANNED per §0 / F4:
  - ``people.minItems: 1`` -- list-length NOT enforced.
  - ``inferred_roles.minItems: 1`` -- list-length NOT
    enforced.
  No schema patterns or numeric bounds.

PersonContract.experience_years documentary per F8:
  - Schema types as ``string`` (NOT number). Free-form values
    like "8 years" or "10+ years" or "indefinite". Per §0
    type as bare ``str``; do NOT attempt int coercion or
    pattern matching.

R-residuals deferred (spec §8):
  - R-a. confidence field range -- not enforced per §0
         (matches 5b R-b / 5c R-a).
  - R-b. Downstream defensive person-item reads (``role`` /
         ``name`` / ``months_until_hire`` on people items) at
         post_intake_headcount/schedule.py:693-706. DB audit
         + downstream cleanup (matches 5b R-a DB-audit
         pattern).
  - R-c. key_people_summary post-pop pattern -- two paths to
         harmonize: stop popping, OR drop from GPT schema.
         First-cut contract accepts both shapes via
         Optional[str] = None.
  - R-d. financials.py:164 reads pc_obj.get("key_people_
         summary") which always returns None on persisted
         drafts (per R-c). Either remove the read or
         reconstruct from people array at this site too.
  - R-e. Contract 3 fact_template field-path harmonization
         (matches 5b R-f / 5c R-e).
  - R-f. Downstream consumers upgrade to typed instance reads
         (matches 5b R-g / 5c R-f).
  - R-g. Tighten Optional[X]=None to Optional[X] for
         business_naics_6 once DB audit confirms (matches 5b
         R-h / 5c R-g).
  - R-h. progress_schema (people_capability_consultant.py:
         150-184) shape-harmonization with this roster
         (matches 5b R-e / 5c R-d).
  - R-i. Contracts 6 R16 + 7 R9 NOW ACTIONABLE immediately
         post-5d-3 landing.

No new gate site per spec §5.4. Contract 5's existing
consumer-side gate at runner.py:189 automatically tightens
via recursive ``model_validate`` once the field type changes
in Commit 5d-3.

No new PhaseCode / EventCode / FailFastCode. Diagnostics
route through the existing INTAKE_DRAFT_CONTRACT stack (per
F3: no new stage label; existing INTAKE_DRAFT_STAGE_LABEL
covers retrofit).
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

try:
  from person_identity import normalize_wage_source  # type: ignore
except Exception:
  from client_intake_and_finmo.person_identity import (  # type: ignore
    normalize_wage_source,
  )


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label exported for discoverability per spec §3.1. Sub-
#: contract is invoked through Contract 5's existing
#: INTAKE_DRAFT_STAGE_LABEL diagnostic stack; this label only
#: surfaces if a future direct gate site is added (PSL5
#: future-proof, 5b/5c precedent).
PEOPLE_JSON_STAGE_LABEL = "INTAKE_DRAFT::people_json"


# ---------------------------------------------------------------------------
# PersonContract (9 fields per people_capability_consultant.py:94-114)
# ---------------------------------------------------------------------------

class PersonContract(BaseModel):
  """One key-person entry. 9 fields per
  people_capability_consultant.py:94-114.

  Per §0 policy:
    - ``experience_years`` types as bare ``str`` per F8 (schema
      says STRING -- free-form values like "8 years" or "10+
      years", NOT a number). NO int coercion or pattern
      matching.
    - ``wage_source`` vocabulary (client_override /
      gpt_estimate / unknown) documented at consultant.py:218-
      221 but NOT in schema enum; bare ``str`` per F9.
    - ``annual_wage`` numeric range NOT enforced per F4 (e.g.,
      no Field(gt=0)).

  extra='ignore' per F2 + F3: accepts the legacy fallback
  person-item fields (``role`` / ``name`` /
  ``months_until_hire``) that post_intake_headcount/schedule.py:
  693-706 defensively reads. These are NOT in the GPT schema.
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

  #: THE STABLE IDENTITY OF ONE HUMAN (Nick 2026-09-11). Assigned at
  #: capture in _merge_people_rows - the single helper every people write
  #: funnels through - and carried for the life of the draft. It MUST be
  #: declared here: ``extra="ignore"`` silently strips undeclared keys, so
  #: an id that is not a field would vanish at this boundary and the
  #: roster would be back to keying humans on a name the model re-picks
  #: each turn. Optional because drafts captured before this existed carry
  #: none, and a legacy draft must still cross the boundary.
  person_id: Optional[str] = None

  #: Set by the owner-pay door on the row it landed on - that door's whole
  #: meaning is "what you pay YOURSELF", so it knows. Recorded rather than
  #: re-derived, because the title pattern it used instead could not see
  #: "Certified Prosthetist-Orthotist" and minted a duplicate owner.
  is_owner: Optional[bool] = None

  model_config = ConfigDict(extra="ignore")

  @field_validator("wage_source", mode="before")
  @classmethod
  def _canonical_wage_source(cls, value: Any) -> str:
    """§0 EXCEPTION, ruled 2026-09-11 - see the module docstring for the
    incident. Normalizes rather than rejects, so a legacy spelling still
    crosses the boundary and no draft on file is stranded."""
    token, _recognised = normalize_wage_source(value)
    return token


# ---------------------------------------------------------------------------
# InferredRoleContract (5 fields per people_capability_consultant.py:124-131)
# ---------------------------------------------------------------------------

class InferredRoleContract(BaseModel):
  """One inferred-role entry. 5 fields per
  people_capability_consultant.py:124-131.

  ``months_until_hire`` correctly belongs here (per the
  schema), NOT on PersonContract -- the downstream
  post_intake_headcount/schedule.py:702-706 defensive read of
  ``months_until_hire`` from people-items is the legacy
  fallback (R-b cleanup target).

  Per §0:
    - ``months_until_hire`` numeric range NOT enforced (no
      Field(ge=0) -- negative values pass through).
    - ``wage_source`` bare str per F9.
  """
  role_title: str
  annual_wage: Optional[float] = None
  wage_source: str
  months_until_hire: Optional[float] = None
  notes: str

  model_config = ConfigDict(extra="ignore")

  @field_validator("wage_source", mode="before")
  @classmethod
  def _canonical_wage_source(cls, value: Any) -> str:
    """The same enum as PersonContract: an inferred role's provenance is
    written by this codebase too, and the OEWS enricher reads it the same
    way (people_roles.py applies the identical guard to both lists)."""
    token, _recognised = normalize_wage_source(value)
    return token


# ---------------------------------------------------------------------------
# Top-level PeopleJsonContract (6 typed fields)
# ---------------------------------------------------------------------------

class PeopleJsonContract(BaseModel):
  """People & capability intake payload per
  people_capability_consultant.py _final_schema() at
  people_capability_consultant.py:80-147.

  Field roster (6 typed fields):
    1. 4 always-present per persistence reality:
       people, inferred_roles, inferred_roles_summary, confidence
    2. 1 nullable-required schema field per F7:
       business_naics_6 -> Optional[str] = None
    3. 1 schema-required-but-production-popped per F1 / PSL2:
       key_people_summary -> Optional[str] = None
       (the LOAD-BEARING PSL2 case of the 5b/5c/5d series --
       schema marks REQUIRED; intake_consult.py:6241 POPS it
       before persistence; production payloads NEVER carry it)

  No enum vocabularies anywhere in the schema (simpler than
  5b's 5 enums + 5c's 5 enums).

  Schema constraints (people.minItems=1 +
  inferred_roles.minItems=1) NOT enforced per §0 / F4.

  Nested object lists keep typed sub-contract structure per T5:
    - people: List[PersonContract]
    - inferred_roles: List[InferredRoleContract]

  ``extra="ignore"`` per F3 tolerates future schema-version
  drift.
  """
  # --- 4 always-present per persistence reality ---
  people: List[PersonContract]
  inferred_roles: List[InferredRoleContract]
  inferred_roles_summary: str
  confidence: float

  # --- 1 nullable-required schema field (Optional[X] = None per F7) ---
  #: Cross-flow from operating_model_json.business_naics_6 at
  #: intake_consult.py:6228 (also :9464, :10224). Schema-typed
  #: as ["string", "null"].
  business_naics_6: Optional[str] = None

  # --- 1 schema-required-but-production-popped per F1 / PSL2 ---
  #: Schema lists as REQUIRED. intake_consult.py:6241 pops the
  #: field before persistence to draft. Production payloads
  #: NEVER carry this field. Typing as required would fail
  #: 100% of production runs. Per PSL2 production-reality-wins:
  #: type as Optional[str] = None despite schema-required.
  #: R-c R-residual covers the long-term harmonization (either
  #: stop popping, OR drop from GPT schema).
  key_people_summary: Optional[str] = None

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "PEOPLE_JSON_STAGE_LABEL",
  "PersonContract",
  "InferredRoleContract",
  "PeopleJsonContract",
]
