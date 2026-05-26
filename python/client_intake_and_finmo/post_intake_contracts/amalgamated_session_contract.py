"""AmalgamatedSessionContract -- typed contract for the Mirror
dataclass at the INDUSTRY_BASELINE -> AMALGAMATED_SESSION
boundary (Boundary 3).

**FINAL contract in the P3.40 sequence.** After this contract +
its enforcement helpers + observability invariant tests land,
Boundaries 1-7 are end-to-end contract-typed.

Spec: ``docs/architecture/p3_40_contract_7_amalgamated_session_spec.md``
(commit c5ecb6a). Trace:
``docs/architecture/p3_40_contract_7_amalgamated_session_trace.md``
(commit 9a353c3).

FIRST DATACLASS-SHAPED BOUNDARY in the P3.40 series. Contracts
1-6 typed dict-shaped boundary surfaces; Contract 7 types the
``Mirror`` dataclass at mirror.py:75-86. Gate sites convert via
``dataclasses.asdict(mirror)`` per F14 -- recursive conversion
handles the nested RecentDecision dataclass automatically.

Multi-shape boundary per F0 (a) / Contract 6 F0 pattern:
6 sub-contracts in a single module:

  Shape A -- MirrorContract (9 data fields). Top-level boundary
    surface, mirrors the Mirror dataclass at mirror.py:75-86.
    Carries the F5 plan_state_alias_sync @model_validator (Bug 2
    fix invariant).
  Shape B -- RecentDecisionContract (6 fields). Ring-buffer entry
    per mirror.py:64-72; phantom-write per v2 §D-2 (typed but
    Optional default None per F3).
  Shape D -- ValidationStateProjectionContract (11 fields).
    Bug 3 bounded projection per mirror.py:146-157. Carries 4
    @model_validators per F6 (i)-(iv): cap on
    failing_check_names, cap on failing_lever_margins,
    truncation flag consistency, outside_band filter.
  Shape E -- LeverMarginEntryContract (8 fields). Inner dict in
    failing_lever_margins per mirror.py:135-145.
  Shape F -- GetBandsViewContract (composition per F1).
    Re-imported from Contract 6's
    industry_baseline_resolved_contract.py; ZERO redefinition.
  Top-level wrapper -- AmalgamatedSessionContract (composes
    MirrorContract; extra='forbid' top-level per F13).

(Shape C -- PlanStateSectionContract -- is NOT a separate
sub-contract per F2 DEFER. plan_state is typed as
``Dict[Literal[5 SECTIONS], Dict[str, Any]]`` inside
MirrorContract; per-section sub-contract typing is R8
R-residual.)

Composition policy (per F1 + F2):
- F1: re-import ``GetBandsViewContract`` from Contract 6 for
  ``MirrorContract.bands``. Same class identity ensures
  type-checking parity across Contracts 6 + 7.
- F2: defer Contract 1 per-section composition. plan_state
  sections are post-revise snapshots, not 1:1 with Contract 1's
  full FinmoModelInputContract shape. R8 R-residual.

extra-key policy (per F13):
- ``extra="forbid"`` on top-level AmalgamatedSessionContract
  (6 fields fully known).
- ``extra="forbid"`` on MirrorContract (9 data fields fully
  known per mirror.py:75-86).
- ``extra="ignore"`` on the other 4 sub-contracts
  (RecentDecisionContract, ValidationStateProjectionContract,
  LeverMarginEntryContract) -- producers may add diagnostic
  fields that the contract gate doesn't structure-read.

Bug 2 + Bug 3 refresh-semantic invariants encoded as
@model_validators per F5 + F6 -- the bug fixes ARE the contract:

  F5 plan_state_alias_sync (MirrorContract):
    Bug 2 fix at mirror.py:163-180 establishes that when
    plan_state contains ANY of the 3 alias keys
    (balance_sheet, capex_rd_balance_seed, capex_rd), all
    three keys must hold the same payload. The contract pins
    this so a future refactor that breaks alias-sync surfaces
    as ContractViolation rather than silent state divergence.

  F6 (i) failing_check_names_cap (ValidationStateProjectionContract):
    Bug 3 fix at mirror.py:128 caps the list at
    _VALIDATION_STATE_RENDER_CAP = 12. Field(max_length=12)
    enforces at the field-level; this validator is documentary.

  F6 (ii) failing_lever_margins_cap (ValidationStateProjectionContract):
    Mirror of (i) for the lever margins list per
    mirror.py:135-145.

  F6 (iii) truncation_flag_consistency (ValidationStateProjectionContract):
    If failing_check_names is at-or-above cap (= 12),
    failing_check_names_truncated MUST be True (Bug 3
    truncation flag semantic per mirror.py:154-155). Same for
    failing_lever_margins_truncated. The full bidirectional
    invariant (when below cap, flag MUST be False unless raw
    count was exactly cap) requires upstream EvaluatePlanResult
    context not available at the contract layer; spec §4.2
    documents this as the one-half check.

  F6 (iv) lever_margins_all_outside_band (ValidationStateProjectionContract):
    Bug 3 producer filter at mirror.py:130-133 only emits
    entries where outside_band=True. The contract enforces
    that producer-side filter so a future regression
    (skipping the filter) surfaces immediately.

Literal pinning per F7 + F8:
  - strictness: Literal["mini_finmo", "full_acceptance_gate"]
    verbatim from evaluation_types.py:110 docstring.
  - section: Literal[5 SECTIONS] verbatim from
    evaluation_types.py:39. Used in MirrorContract.plan_state +
    MirrorContract.bands keys + LeverMarginEntryContract.section.

Module-level constants exported:
  - AMALGAMATED_SESSION_STAGE_LABEL
  - SUPPORTED_SECTIONS (5-tuple)
  - SUPPORTED_STRICTNESS_VALUES (2-tuple)
  - VALIDATION_STATE_RENDER_CAP (= 12, per mirror.py:34)
  - PLAN_STATE_ALIAS_TRIPLET (3-tuple, per Bug 2 fix at
    mirror.py:175-180)

F14 dataclass-to-dict conversion pattern (for Commit 3 gate
wirings):
  Gate sites convert the Mirror dataclass via
  ``dataclasses.asdict(mirror)`` -- recursive conversion handles
  the nested RecentDecision dataclass automatically. No
  explicit adapter classmethod needed for first cut. If a
  future Mirror field holds a non-dataclass object asdict can't
  serialize, R14 R-residual covers the upgrade path (add
  ``MirrorContract.from_mirror(mirror)`` classmethod and treat
  as Commit 2 work).

Residual cleanups deferred (spec §8):
  - R8.  Per-section PlanStateSectionContract typing (F2
         deferral). Composes Contract 1 sub-shapes per section.
  - R9.  ASSESSED (Cleanup Commit 2), NO CODE CHANGE
         WARRANTED. Production Mirror.business_facts is built
         at runner.py:261-271 from FLAT DRAFT-ROW COLUMNS
         (name, business_name, address, start_date,
         address_street/city/state/zip/country) -- NOT from
         5b/5c/5d JSON content. Zero structural overlap with
         the typed sub-contracts (OperatingModelJsonContract /
         TargetMarketJsonContract / PeopleJsonContract). The
         R9 hypothesis ("compose 5b/c/d when they land")
         doesn't match production reality; the field is
         genuinely heterogeneous draft-column data. Mirror.
         business_facts stays as Dict[str, Any] -- composing
         5b/c/d here would type fields production doesn't
         populate. Contract 5's consumer-side gate at
         runner.py:189 already provides the structural
         assurance for the 3 typed sub-contracts; that
         enforcement doesn't transitively apply to
         Mirror.business_facts because the two surfaces are
         disjoint.
  - R10. Drop mirror.recent_decisions phantom-write per v2 §D-2.
  - R11. Drop mirror.sequence_position + mirror.budget
         phantom-required fields per v2 §D-3.
  - R12. F6 (iii) full bidirectional check requires upstream
         EvaluatePlanResult context; currently one-half only.
  - R13. Refresh-point gates inside set_plan_state_section +
         set_validation_state if a future diagnostic shows
         refresh-time violations matter.
  - R14. MirrorContract.from_mirror(mirror) explicit adapter
         classmethod if asdict() proves insufficient.
  - R15. evaluate_plan re-fetches mirror.bands -- architectural
         cleanup per v1 §E-2.
  - R16. Operating-model levers no revise_* tool per v2 §E-3.
  - R17. WC scalar patch shape formalization in
         CascadeLever.direction per v2 §E-4.
  - R18. End-to-end AmalgamatedSessionContract round-trip
         regression test.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  model_validator,
)

# F1 -- compose Contract 6 GetBandsViewContract for mirror.bands.
# Same class identity prevents type drift across Contracts 6 + 7.
from client_intake_and_finmo.post_intake_contracts.industry_baseline_resolved_contract import (
  GetBandsViewBandContract,
  GetBandsViewContract,
)
# Re-export ContractViolation so gate callers import from one place.
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label for the boundary gates. Names the actual producer
#: -> consumer direction per the v2 inventory's Boundary 3 framing.
AMALGAMATED_SESSION_STAGE_LABEL = "INDUSTRY_BASELINE->AMALGAMATED_SESSION"

#: 5 SECTIONS verbatim from evaluation_types.py:39. Used as
#: Literal members in MirrorContract.plan_state keys +
#: MirrorContract.bands keys + LeverMarginEntryContract.section.
SUPPORTED_SECTIONS = ("stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet")

#: 2-value strictness vocabulary per evaluation_types.py:110
#: docstring. Used as Literal members in
#: ValidationStateProjectionContract.strictness.
SUPPORTED_STRICTNESS_VALUES = ("mini_finmo", "full_acceptance_gate")

#: Bug 3 bounded-projection cap, verbatim from
#: mirror.py:34 (_VALIDATION_STATE_RENDER_CAP = 12). Referenced
#: by F6 (i) + (ii) + (iii) invariants on
#: ValidationStateProjectionContract.
VALIDATION_STATE_RENDER_CAP = 12

#: Bug 2 fix 3-way alias triplet per mirror.py:175-180. When
#: plan_state contains ANY of these section keys, ALL three
#: must hold the same payload (F5 invariant). Used by
#: MirrorContract.plan_state_alias_sync @model_validator.
PLAN_STATE_ALIAS_TRIPLET = ("balance_sheet", "capex_rd_balance_seed", "capex_rd")


# ---------------------------------------------------------------------------
# Shape B -- RecentDecisionContract (6 fields per mirror.py:64-72)
# ---------------------------------------------------------------------------

class RecentDecisionContract(BaseModel):
  """One ring-buffer entry per ``RecentDecision`` dataclass at
  mirror.py:64-72. Phantom-write per v2 §D-2 -- the setter
  ``record_decision`` is called but no production reader
  consumes the buffer. R10 R-residual covers eventual cleanup.

  6 fields total. tool_name + inputs_summary required; the rest
  are Optional or defaults.
  """

  tool_name: str = Field(min_length=1)
  inputs_summary: str
  delta_all_pass: Optional[int] = None
  delta_worst_distance: Optional[float] = None
  result_summary: str = ""
  at: Optional[str] = None

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Shape E -- LeverMarginEntryContract (8 fields per mirror.py:135-145)
# ---------------------------------------------------------------------------

class LeverMarginEntryContract(BaseModel):
  """One entry inside ValidationStateProjectionContract.failing_lever_margins.
  8 fields per the inner dict literal at mirror.py:135-145.

  F6 (iv) invariant: every entry MUST have outside_band=True.
  The producer at mirror.py:130-133 filters explicitly:
  ``failing_margins = [m for m in evaluate_plan_result.lever_margins
  if getattr(m, "outside_band", False)]``. The contract enforces
  the filter so a future regression (skipping it) surfaces as
  ContractViolation. The invariant is enforced at the parent
  ValidationStateProjectionContract level
  (lever_margins_all_outside_band validator) -- this contract
  permits outside_band=False so that test fixtures can construct
  rejection cases.

  section types as Optional[Literal[5 SECTIONS]] per F8.
  """

  lever_id: Optional[str] = None
  section: Optional[Literal["stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet"]] = None
  current: Optional[float] = None
  band_min: Optional[float] = None
  band_max: Optional[float] = None
  outside_band: bool
  pinned_min: bool = False
  pinned_max: bool = False

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Shape D -- ValidationStateProjectionContract (11 fields per Bug 3)
# ---------------------------------------------------------------------------

class ValidationStateProjectionContract(BaseModel):
  """Bug 3 bounded projection per mirror.py:146-157. 11 fields
  total. F6 (i)-(iv) cross-field invariants enforce the cap +
  truncation flag + outside_band filter.

  F7: strictness types as Literal of 2 values per
  evaluation_types.py:110.

  Field-level Bug 3 caps:
  - failing_check_names: max_length=12 (F6 (i))
  - failing_lever_margins: max_length=12 (F6 (ii))
  """

  all_pass: bool
  round_number: int = Field(ge=0)
  strictness: Literal["mini_finmo", "full_acceptance_gate"]
  failing_check_count: int = Field(ge=0)
  worst_failing_check: Optional[str] = None
  worst_failing_distance: Optional[float] = None
  failing_check_names: List[str] = Field(
    default_factory=list, max_length=VALIDATION_STATE_RENDER_CAP,
  )
  failing_check_names_truncated: bool
  failing_lever_margins: List[LeverMarginEntryContract] = Field(
    default_factory=list, max_length=VALIDATION_STATE_RENDER_CAP,
  )
  failing_lever_margins_truncated: bool
  evaluated_at: Optional[str] = None

  model_config = ConfigDict(extra="ignore")

  # -------------------------------------------------------------------------
  # F6 (i) + (ii) -- failing list caps (Bug 3 invariants)
  # -------------------------------------------------------------------------

  @model_validator(mode="after")
  def failing_check_names_cap(self) -> "ValidationStateProjectionContract":
    """F6 (i): Bug 3 cap. The Field(max_length=12) declaration
    enforces this at field-level; this validator is documentary
    and produces a clear error message tying back to the
    constant + producer site."""
    if len(self.failing_check_names) > VALIDATION_STATE_RENDER_CAP:
      raise ValueError(
        f"failing_check_names exceeds Bug 3 cap of "
        f"{VALIDATION_STATE_RENDER_CAP} (mirror.py:34, "
        f"_VALIDATION_STATE_RENDER_CAP); got "
        f"{len(self.failing_check_names)} entries. Producer at "
        f"mirror.py:128 should have applied the cap."
      )
    return self

  @model_validator(mode="after")
  def failing_lever_margins_cap(self) -> "ValidationStateProjectionContract":
    """F6 (ii): mirror of F6 (i) for lever margins per
    mirror.py:135-145."""
    if len(self.failing_lever_margins) > VALIDATION_STATE_RENDER_CAP:
      raise ValueError(
        f"failing_lever_margins exceeds Bug 3 cap of "
        f"{VALIDATION_STATE_RENDER_CAP}; got "
        f"{len(self.failing_lever_margins)} entries. Producer at "
        f"mirror.py:135-145 should have applied the cap."
      )
    return self

  # -------------------------------------------------------------------------
  # F6 (iii) -- truncation flag consistency
  # -------------------------------------------------------------------------

  @model_validator(mode="after")
  def truncation_flag_consistency(self) -> "ValidationStateProjectionContract":
    """F6 (iii): if a list is at-or-above cap, the corresponding
    truncated flag MUST be True. This catches the common-case
    regression where the cap was applied but the truncation flag
    wasn't set. The full bidirectional check (when below cap,
    flag MUST be False unless raw count was exactly cap)
    requires upstream EvaluatePlanResult context not available
    at the contract layer; R12 R-residual covers the upgrade
    when consumers carry that context."""
    if (
      len(self.failing_check_names) >= VALIDATION_STATE_RENDER_CAP
      and not self.failing_check_names_truncated
    ):
      raise ValueError(
        f"failing_check_names_truncated must be True when "
        f"failing_check_names length is at-or-above cap "
        f"({VALIDATION_STATE_RENDER_CAP}); got "
        f"len={len(self.failing_check_names)} and "
        f"truncated={self.failing_check_names_truncated}"
      )
    if (
      len(self.failing_lever_margins) >= VALIDATION_STATE_RENDER_CAP
      and not self.failing_lever_margins_truncated
    ):
      raise ValueError(
        f"failing_lever_margins_truncated must be True when "
        f"failing_lever_margins length is at-or-above cap "
        f"({VALIDATION_STATE_RENDER_CAP}); got "
        f"len={len(self.failing_lever_margins)} and "
        f"truncated={self.failing_lever_margins_truncated}"
      )
    return self

  # -------------------------------------------------------------------------
  # F6 (iv) -- outside_band filter (Bug 3 producer-side filter)
  # -------------------------------------------------------------------------

  @model_validator(mode="after")
  def lever_margins_all_outside_band(self) -> "ValidationStateProjectionContract":
    """F6 (iv): Bug 3 producer at mirror.py:130-133 filters
    explicitly: ``failing_margins = [m for m in
    evaluate_plan_result.lever_margins if
    getattr(m, "outside_band", False)]``. Every entry in
    failing_lever_margins MUST have outside_band=True. An entry
    with outside_band=False would indicate the producer filter
    was bypassed (regression). Surface as ContractViolation."""
    for i, entry in enumerate(self.failing_lever_margins):
      if not entry.outside_band:
        raise ValueError(
          f"failing_lever_margins[{i}].outside_band must be True "
          f"(Bug 3 producer filter at mirror.py:130-133 should "
          f"exclude in-band entries); got outside_band=False for "
          f"lever_id={entry.lever_id!r}"
        )
    return self


# ---------------------------------------------------------------------------
# Shape A -- MirrorContract (9 data fields per mirror.py:75-86)
# ---------------------------------------------------------------------------

class MirrorContract(BaseModel):
  """The Mirror dataclass per mirror.py:75-86. 9 data fields
  (recent_decisions_cap excluded as internal config, matching
  the Mirror.to_dict() precedent at mirror.py:182-192).

  Composition:
  - F1: bands types as ``Dict[Literal[5 SECTIONS], GetBandsViewContract]``
    -- composes Contract 6.
  - F2 DEFER: plan_state types as
    ``Dict[Literal[5 SECTIONS], Dict[str, Any]]`` -- per-section
    typing is R8 R-residual.

  Phantom-write / phantom-required fields per v2 §D + F3/F4:
  - recent_decisions: Optional[List[...]] = None (F3 -- v2 §D-2
    phantom-write).
  - sequence_position: Optional[Dict] = None (F4 -- v2 §D-3
    phantom-required).
  - budget: Optional[Dict] = None (F4 -- v2 §D-3 phantom-required).

  F5 invariant: plan_state_alias_sync. The Bug 2 fix at
  mirror.py:163-180 establishes that when plan_state contains
  any of the 3 alias keys (balance_sheet,
  capex_rd_balance_seed, capex_rd), all three keys MUST hold
  the same payload after a set_plan_state_section call.

  extra='forbid' per F13.
  """

  invariants: Dict[str, str]
  authority: str
  business_facts: Dict[str, Any]
  plan_state: Dict[
    Literal["stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet"],
    Dict[str, Any],
  ] = Field(default_factory=dict)
  sequence_position: Optional[Dict[str, Any]] = None
  bands: Dict[
    Literal["stage_ramp", "drivers", "payroll", "capex_rd", "balance_sheet"],
    GetBandsViewContract,
  ] = Field(default_factory=dict)
  validation_state: Optional[ValidationStateProjectionContract] = None
  recent_decisions: Optional[List[RecentDecisionContract]] = None
  budget: Optional[Dict[str, Any]] = None

  model_config = ConfigDict(extra="forbid")

  # -------------------------------------------------------------------------
  # F5 -- Bug 2 fix plan_state_alias_sync invariant
  # -------------------------------------------------------------------------

  @model_validator(mode="after")
  def plan_state_alias_sync(self) -> "MirrorContract":
    """F5: the Bug 2 fix at mirror.py:163-180 establishes that
    when plan_state contains ANY of the 3 alias keys
    (balance_sheet, capex_rd_balance_seed, capex_rd), ALL three
    present keys must hold the same payload after a
    set_plan_state_section call. Future regression of the
    alias-sync surfaces as ContractViolation.

    Sub-condition: if NONE of the 3 alias keys is present
    (pre-first-commit Mirror state), no constraint.

    NOTE: plan_state's outer dict type is
    Dict[Literal[5 SECTIONS], Dict[str, Any]], which means the
    alias key 'capex_rd_balance_seed' (NOT in the 5-SECTIONS
    Literal) would be rejected by Pydantic's Literal validation
    BEFORE reaching this @model_validator. So in practice this
    invariant fires for the 2 keys present in the Literal:
    balance_sheet + capex_rd. The 'capex_rd_balance_seed' alias
    is the v1-legacy key that the read-side closure at
    session_factory._build_current_payload_for treats as an
    alias for the other two; it doesn't appear in plan_state
    under modern code paths. Documented for future maintainers
    if the Literal is ever extended.
    """
    alias_keys = PLAN_STATE_ALIAS_TRIPLET  # 3-tuple
    present_aliases = {
      k: self.plan_state.get(k)
      for k in alias_keys
      if k in self.plan_state
    }
    if not present_aliases:
      return self  # no aliases yet; pre-commit state -- no constraint
    if len(present_aliases) == 1:
      return self  # only one key present; nothing to compare
    # All present aliases must hold the same payload
    values = list(present_aliases.values())
    first = values[0]
    for k, v in present_aliases.items():
      if v != first:
        raise ValueError(
          f"plan_state alias-sync violated: keys "
          f"{list(present_aliases.keys())} hold differing "
          f"payloads. Bug 2 fix at mirror.py:163-180 requires "
          f"balance_sheet / capex_rd_balance_seed / capex_rd "
          f"all carry the same payload after "
          f"set_plan_state_section commits."
        )
    return self


# ---------------------------------------------------------------------------
# Top-level AmalgamatedSessionContract
# ---------------------------------------------------------------------------

class AmalgamatedSessionContract(BaseModel):
  """Top-level wrapper for the Boundary 3 surface.

  Per F0 (a): single Contract 7 module with 6 sub-contracts.
  This wrapper exists for one-stop import + end-to-end
  validation; the canonical boundary surface is
  ``MirrorContract`` (Shape A).

  The wrapper is intentionally thin -- a single mirror field
  bundling the full Mirror state. Future expansion (e.g., to
  include session-driver state alongside the mirror) goes here
  as additional fields rather than as a separate contract.

  extra='forbid' per F13.
  """

  mirror: MirrorContract

  model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "AMALGAMATED_SESSION_STAGE_LABEL",
  "SUPPORTED_SECTIONS",
  "SUPPORTED_STRICTNESS_VALUES",
  "VALIDATION_STATE_RENDER_CAP",
  "PLAN_STATE_ALIAS_TRIPLET",
  "RecentDecisionContract",
  "LeverMarginEntryContract",
  "ValidationStateProjectionContract",
  "MirrorContract",
  "AmalgamatedSessionContract",
  # Re-exported from Contract 6 (F1 composition):
  "GetBandsViewBandContract",
  "GetBandsViewContract",
  # Re-exported from Contract 1 for one-stop import at gate sites:
  "ContractViolation",
]
