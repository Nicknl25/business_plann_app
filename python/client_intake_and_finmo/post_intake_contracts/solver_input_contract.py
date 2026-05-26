"""SolverInputContract — typed contract for the 21-field bundle at
the MODEL_INPUT → SOLVER (target_seeking) boundary (Boundary 5).

This is the third of seven typed inter-stage contracts. Spec:
``docs/architecture/p3_40_contract_3_solver_input_spec.md``
(commit 8fe3244).

Composes prior contracts (no redefinition; one type per shape):

  - ``applied_model_input_json``         -> Contract 1
                                            (``FinmoModelInputContract``)
  - ``catalog_source_model_input_json``  -> Contract 1
                                            (``FinmoModelInputContract``;
                                            kept-required per spec Flag 2)
  - ``applied_finmo_json``               -> Contract 2
                                            (``FinmoOutputContract``)
  - ``stage_ramp_contract`` (Optional)   -> Contract 2
                                            (``StageRampContract``)
  - ``payroll_headcount`` (Optional)     -> Contract 2
                                            (``PayrollHeadcountContract``)

New typed sub-contract added here:

  - ``business_facts`` -> ``BusinessFactsForSolverContract``

The other 13 fields type as opaque ``Dict[str, Any]`` per the spec
§2 Tier classification (Tier-A intake-domain shapes are deferred
to Contract 5; Tier-C persist-only payloads are pure round-trip;
Tier-F truly-unread payloads are kept required + opaque per Flag
2).

extra-key policy (per spec Flag 7):

  - ``extra="forbid"`` ONLY on top-level ``SolverInputContract``
  - ``extra="ignore"`` on ``BusinessFactsForSolverContract`` and on
    every re-imported sub-contract (Contract 1 / Contract 2
    already set their own ``extra`` policies; composition
    inherits them)

Cross-field invariants (per spec §4):

  1. ``planning_mode_in_supported_set`` — enforced by Literal[...]
     field declaration; no separate validator.
  2. ``stage_ramp_contract_quarter_ramp_grid_length`` — inherited
     via composition from Contract 2's ``StageRampContract``.
  3. ``payroll_headcount_rows_cover_all_horizon_quarters`` —
     inherited via composition from Contract 2's
     ``PayrollHeadcountContract``.
  4. ``planning_run_id_present_when_persisting`` (Flag 8(a) tighten)
     — typed as ``str = Field(min_length=1)`` rather than
     ``Optional[str]``. Defense-in-depth on top of the
     RuntimeError("planning_run_start_failed") at runner.py:83-85;
     same invariant guarded at adjacent boundaries.
  5. ``contract_versions_agree`` (Flag 8(b)) — cross-field validator
     requiring ``applied_model_input_json.contract_version ==
     catalog_source_model_input_json.contract_version``. Catches
     producer drift between the two model-input paths.

Residual cleanups deliberately deferred (spec §8):

  - **R8.** Removal of ~20 defensive ``or {}`` patterns in
    orchestrator.py body that the consumer-side gate makes
    redundant. Each is now dead defense; clean-up is a follow-up.
  - **R9.** Carry-over from Contract 2: delete
    ``client_statements_output_excel/data.py::validate_draft_data``.
  - **R10.** Intake-domain typed contracts (Contract 5):
    ``fact_template``, ``ops_json``, ``financials_json``,
    ``financials_year1_json``, ``people_json``, ``fulfillment_json``,
    ``marketing_model_json``. Per spec Flag 4 deferred from
    Contract 3.
  - **R11.** Solver output typed contract (Contract 4).
  - **R12.** Two-hop API wrapper consolidation
    (``_run_unified_post_grid_system_run`` +
    ``_run_planning_system_for_draft_unified``).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Literal, Optional

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  model_validator,
)

# Contract 1 composition: applied_model_input_json +
# catalog_source_model_input_json speak FinmoModelInputContract.
# ContractViolation is re-exported here so solver callers can raise
# it without importing from finmo_model_input_contract directly.
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
  FinmoModelInputContract,
)
# Contract 2 composition: applied_finmo_json (TC2),
# stage_ramp_contract (Flag 3), payroll_headcount (re-use Contract 2's
# typing rather than redefine). Imports the SAME class identities
# Contract 2 uses so type checks across boundaries unify.
from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (
  FinmoOutputContract,
  PayrollHeadcountContract,
  StageRampContract,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label for the producer/consumer gates at this boundary.
#: Used in ContractViolation.stage and diagnostic_data.stage.
#: Matches the boundary name in the v2 inventory.
SOLVER_STAGE_LABEL = "MODEL_INPUT→SOLVER"

#: Supported planning modes per TC1. Lifted verbatim from the
#: mode-unknown fail-fast at orchestrator.py:1100-1115. Pinned
#: in the contract via Literal[...] so a typo at the call site
#: surfaces as a ContractViolation rather than a fail-fast 4 frames
#: deeper. Lock-via-paired-tests (typo + correct spellings) lands
#: in Commit 1b.
SUPPORTED_PLANNING_MODES = ("growth", "stability", "runway_extension", "survival")


# ---------------------------------------------------------------------------
# BusinessFactsForSolverContract — the one new sub-contract
# ---------------------------------------------------------------------------

class BusinessFactsForSolverContract(BaseModel):
  """The ``business_facts`` payload at the solver boundary.

  Per trace T4: read at compute_adaptive_policy
  (orchestrator.py:1156), _bf_template extraction
  (orchestrator.py:1188-1195), business_stage_for_cascade
  (orchestrator.py:1605-1607), and the _build_finmo_callable
  closure (orchestrator.py:1361). Every read either treats the
  top-level dict as opaque or bottoms out in ``fact_template`` (an
  intake-domain shape deferred to Contract 5 per Flag 4).

  Typed minimally for first cut: ``fact_template`` is required as
  ``Dict[str, Any]`` (the only reads bottom out there); other
  top-level keys are permitted via ``extra="ignore"``. Contract 5
  will tighten the ``fact_template`` shape when intake-domain
  contracts land.
  """

  fact_template: Dict[str, Any]

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Top-level SolverInputContract
# ---------------------------------------------------------------------------

class SolverInputContract(BaseModel):
  """The 21-field bundle at the MODEL_INPUT → SOLVER boundary.

  Field roster (matching ``run_target_seeking_orchestrated_system_run``
  at orchestrator.py:1028 plus the 2 runtime IDs):

  Runtime identifiers (not data; included so the producer-side
  gate confirms they're set before bundle return):
    - ``draft_id: str``                 (min_length=1)
    - ``planning_run_id: str``          (min_length=1, Flag 8(a) tighten)

  Tier A (consumed-direct, typed sub-contracts where shape is known):
    - ``business_facts: BusinessFactsForSolverContract``
    - ``ops_json: Dict[str, Any]``                 (opaque, Flag 4)
    - ``financials_json: Dict[str, Any]``          (opaque, Flag 4)
    - ``financials_year1_json: Dict[str, Any]``    (opaque, Flag 4)
    - ``applied_model_input_json: FinmoModelInputContract``  (Flag 6)
    - ``applied_finmo_json: FinmoOutputContract``  (TC2)
    - ``planning_mode: Literal[...]``              (TC1)
    - ``planning_mode_reason: str``

  Tier B (closure-only via _build_finmo_callable; opaque per Flag 4):
    - ``people_json: Dict[str, Any]``
    - ``fulfillment_json: Dict[str, Any]``
    - ``marketing_model_json: Dict[str, Any]``

  Tier C (persist-only round-trip; opaque per TC3):
    - ``planning_context_summary_json: Optional[Dict[str, Any]]``
    - ``grid_application_summary: Optional[Dict[str, Any]]``

  Tier F (truly READER_MISSING but kept-required per Flag 2):
    - ``target_market_json: Dict[str, Any]``       (opaque)
    - ``planning_result: Dict[str, Any]``          (opaque)
    - ``catalog_source_model_input_json: FinmoModelInputContract``  (Flag 6)

  Optional fields per orchestrator entry signature:
    - ``stage_ramp_contract: Optional[StageRampContract]``   (Flag 3)
    - ``payroll_headcount: Optional[PayrollHeadcountContract]``

  Total: 21 typed fields. ``conn`` (DB connection) is passed
  alongside, not inside the contract.

  ``extra="forbid"`` per Flag 7 — the 21 fields are fully known
  at this boundary. Composed sub-contracts use their own ``extra``
  policy (Contract 1 forbids; Contract 2 ignores on row types).
  """

  # Runtime identifiers
  draft_id: str = Field(min_length=1)
  planning_run_id: str = Field(min_length=1)

  # Tier A — consumed-direct
  business_facts: BusinessFactsForSolverContract
  ops_json: Dict[str, Any]
  financials_json: Dict[str, Any]
  financials_year1_json: Dict[str, Any]
  applied_model_input_json: FinmoModelInputContract
  applied_finmo_json: FinmoOutputContract
  planning_mode: Literal["growth", "stability", "runway_extension", "survival"]
  planning_mode_reason: str

  # Tier B — closure-only
  people_json: Dict[str, Any]
  fulfillment_json: Dict[str, Any]
  marketing_model_json: Dict[str, Any]

  # Tier C — persist-only round-trip
  planning_context_summary_json: Optional[Dict[str, Any]] = None
  grid_application_summary: Optional[Dict[str, Any]] = None

  # Tier F — truly READER_MISSING but kept-required per Flag 2
  target_market_json: Dict[str, Any]
  planning_result: Dict[str, Any]
  catalog_source_model_input_json: FinmoModelInputContract

  # Optional per orchestrator entry signature
  stage_ramp_contract: Optional[StageRampContract] = None
  payroll_headcount: Optional[PayrollHeadcountContract] = None

  model_config = ConfigDict(extra="forbid")

  # -------------------------------------------------------------------------
  # Cross-field invariants (spec §4)
  # -------------------------------------------------------------------------

  @model_validator(mode="after")
  def contract_versions_agree(self) -> "SolverInputContract":
    """Invariant §4.5 / Flag 8(b). Both Contract-1-shaped fields
    must carry the same ``contract_version`` string.

    Each is independently pinned by Contract 1 to
    ``Literal["finmo_model_input_v3"]``. This is the cross-field
    equivalent: catches drift if the two paths ever migrate at
    different times (e.g., a v3 -> v4 producer change that updates
    one writer site but not the other).
    """
    applied_version = self.applied_model_input_json.contract_version
    catalog_version = self.catalog_source_model_input_json.contract_version
    if applied_version != catalog_version:
      raise ValueError(
        "applied_model_input_json.contract_version "
        f"({applied_version!r}) does not match "
        f"catalog_source_model_input_json.contract_version "
        f"({catalog_version!r}); both must be the same Contract 1 "
        "version string"
      )
    return self

  # Invariants §4.1 (planning_mode_in_supported_set),
  # §4.2 (stage_ramp_contract.quarter_ramp_grid length),
  # §4.3 (payroll_headcount rows-cover-all-horizon-quarters),
  # §4.4 (planning_run_id presence)
  # are each enforced declaratively (Literal[...] /
  # Field(min_length=1)) or inherited via composition from
  # Contracts 1/2; no separate @model_validator needed for them.


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "SOLVER_STAGE_LABEL",
  "SUPPORTED_PLANNING_MODES",
  "BusinessFactsForSolverContract",
  "SolverInputContract",
  # Re-exported from prior contracts for one-stop import at gate
  # call sites:
  "ContractViolation",
  "FinmoModelInputContract",
  "FinmoOutputContract",
  "PayrollHeadcountContract",
  "StageRampContract",
]
