"""IntakeDraftContract -- typed contract for the 8-field intake-draft
JSON payload at the INTAKE -> POST_INTAKE boundary (Boundary 1).

Fifth of seven typed inter-stage contracts. Spec:
``docs/architecture/p3_40_contract_5_intake_draft_spec.md``
(commit 2f2d46f). Trace + T4 amendment:
``docs/architecture/p3_40_contract_5_intake_draft_trace.md``
(commits e7c739d + 1a190c7).

Contract 5 is the **most upstream** contract in the P3.40 series.
ZERO composition with prior contracts; ZERO re-imports of
FinmoModelInputContract / FinmoOutputContract /
PayrollHeadcountContract / DebtScheduleContract /
CapitalLeaseScheduleContract / BusinessFactsForSolverContract /
StageRampContract. Only ``ContractViolation`` is re-exported
(so gate callers import from one place).

Boundary surface: 8 SQL JSON columns on the
``intake_consult_drafts`` row, assembled INCREMENTALLY by
intake_consult.py across many chat turns (20+ append_messages
writer sites at intake_consult_draft.py:1781-1955) and read by
post-intake at
[runner.py:190-197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L190).

Field roster (per spec section 2):

  Tier A -- consultant-produced or python-aggregated (required):
    - operating_model_json   (consultant_finalize)
    - target_market_json     (target_market_finalize)
    - people_json            (people_capability_finalize)
    - financials_json        (financials_chat_turn accumulator)
    - financials_year1_json  (assemble_financials_year1)
    - marketing_model_json   (_compute_marketing_model_json)
    - planning_context_summary_json
                             (_build_planning_context_summary_payload)

  Tier F -- patch-system-only producer (Optional):
    - fulfillment_json       (_apply_scoped_patch ONLY)

All 8 fields type as opaque ``Dict[str, Any]`` per spec Flag 0 (b)
first-cut disposition. Sub-flag (c) DEFER: the 3 OpenAI-schema-
enforced shapes (operating_model_json, target_market_json,
people_json) become separate follow-up commits (5b/5c/5d), each
with its own focused trace + spec + implementation. Rationale per
Nick's approval:
- Typing 3 of 8 fields creates asymmetry vs the other 5 still-
  opaque shapes; uniform opacity at this layer is cleaner than
  partial typing.
- Each OpenAI schema warrants its own focused work
  (anyOf/oneOf/nested-union translations can have surprises).

Flag 1 (a): fulfillment_json types as ``Optional[Dict[str, Any]] =
None``. Per trace T4 (amended at 1a190c7): patch-system writes
only; no required consultant produces it; SQL column legitimately
NULL when no fulfillment.* patch ever ran. Downstream never
structurally consumes the field -- Contract 3 already typed it as
``Dict[str, Any]`` Tier-B closure-captured-but-explicitly-unused
per the closure docstring at orchestrator.py:625-630. The
v1-cited silent-drop call site is closed via the Contract 3 Tier-F
forwarded-but-unused pattern (Callable plumbed to
initial_grid/runner.py:53 but never invoked inside that file),
NOT via function deletion -- the underlying
``_estimate_balance_sheet_contextual_seed_with_gpt`` still exists
at post_intake_contracts/runner.py:1447 with declared params that
don't include fulfillment_context.

extra-key policy (per spec Flag 6 / PSL4):
- ``extra="forbid"`` on top-level IntakeDraftContract. The 8
  fields are the entire boundary surface today; new fields go
  through the spec process.
- No sub-contracts in Commit 1a; once Contract 5b/c/d sub-
  contracts ship, they'll use ``extra="ignore"`` per the
  established Contracts 1-4 convention.

Cross-field invariants (per spec section 4.1):
- ZERO @model_validator decorators in Commit 1a. All 8 fields are
  opaque Dict[str, Any] -- no cross-field invariants possible
  without typed sub-shapes. Cross-field invariant candidates
  (NAICS source agreement, marketing_model version pin,
  financials_year1 dual-access consistency) become sub-flags in
  the corresponding Contract 5b/c/etc. follow-up specs.

Residual cleanups deliberately deferred (spec section 8):

  - R8.  Sub-contract for ``operating_model_json`` (Contract 5b).
         OpenAI schema at intake_consultant.py:583 -> Pydantic.
  - R9.  Sub-contract for ``target_market_json`` (Contract 5c).
         OpenAI schema at target_market_consultant.py:659.
  - R10. Sub-contract for ``people_json`` (Contract 5d). OpenAI
         schema at people_capability_consultant.py:368.
  - R11. Sub-contracts for ``financials_json`` /
         ``financials_year1_json`` / ``marketing_model_json`` /
         ``planning_context_summary_json`` (Contracts 5e/f/g/h).
         Python-aggregated -- more trace work per shape.
  - R12. Audit + drop fulfillment_json entirely (per F1 (c)
         reasoning if a future audit confirms no downstream
         dependencies).
  - R13. Promote ``_apply_scoped_patch`` writers to typed
         patch-set updates (closes Trace Div-3 patch-system
         "no schema gate" v1 §F-2 bug).
  - R14. ``build_shared_context`` legacy-table import error
         swallow (v1 §F-3).
  - R15. Producer-side "finalize lock" gate (Flag 4 sub-flag (c)).
  - R16. Inverse retrofit: type
         ``BusinessFactsForSolverContract.fact_template`` + the
         draft-row business-fact scalar fields (F3 reasoning).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import (
  BaseModel,
  ConfigDict,
)

# Only re-export ContractViolation -- Contract 5 is upstream of
# every other P3.40 contract; nothing to compose.
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
)
# Contract 5b retrofit (Commit 5b-3): operating_model_json is no
# longer opaque Dict[str, Any] -- composes OperatingModelJsonContract
# for structural typing per spec §0 value-constraint policy.
from client_intake_and_finmo.post_intake_contracts.operating_model_json_contract import (
  OperatingModelJsonContract,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label for the consumer-side gate at this boundary. Used
#: in ContractViolation.stage and diagnostic_data.stage. Names the
#: actual producer -> consumer direction (intake assembly across
#: chat turns -> post-intake initial-grid runner read).
INTAKE_DRAFT_STAGE_LABEL = "INTAKE->POST_INTAKE"


# ---------------------------------------------------------------------------
# Top-level IntakeDraftContract
# ---------------------------------------------------------------------------

class IntakeDraftContract(BaseModel):
  """The 8-field intake-draft JSON payload at the INTAKE ->
  POST_INTAKE boundary.

  Field roster (per spec section 2):

  Tier A -- consultant-produced or python-aggregated (required):
    - operating_model_json
    - target_market_json
    - people_json
    - financials_json
    - financials_year1_json
    - marketing_model_json
    - planning_context_summary_json

  Tier F -- patch-system-only producer (Optional per Flag 1 (a)):
    - fulfillment_json

  Total: 8 typed fields. ``extra="forbid"`` per Flag 6.

  All fields opaque ``Dict[str, Any]`` per Flag 0 (b) first cut.
  Sub-contracts retrofit as Contracts 5b/c/d (OpenAI-schema-
  enforced shapes) + 5e/f/g/h (python-aggregated shapes).

  Excluded fields (per spec section 2.1):
  - ``realism_memo_json`` -- diagnostic, not driving planning
    (Flag 2 EXCLUDE).
  - business-fact scalar fields (business_name,
    business_naics_6, business_address, etc.) -- Contract 3's
    ``BusinessFactsForSolverContract.fact_template`` handles
    opaquely (Flag 3 EXCLUDE / R16 retrofit).
  """

  # Tier A -- consultant-produced or python-aggregated
  operating_model_json: OperatingModelJsonContract
  target_market_json: Dict[str, Any]
  people_json: Dict[str, Any]
  financials_json: Dict[str, Any]
  financials_year1_json: Dict[str, Any]
  marketing_model_json: Dict[str, Any]
  planning_context_summary_json: Dict[str, Any]

  # Tier F -- patch-system-only producer. Optional per Flag 1 (a):
  # SQL column legitimately NULL when no fulfillment.* patch ever
  # ran. Downstream never structurally consumes per trace T4.
  fulfillment_json: Optional[Dict[str, Any]] = None

  model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "INTAKE_DRAFT_STAGE_LABEL",
  "IntakeDraftContract",
  # Re-exported from finmo_model_input_contract for one-stop
  # import at gate call sites:
  "ContractViolation",
]
