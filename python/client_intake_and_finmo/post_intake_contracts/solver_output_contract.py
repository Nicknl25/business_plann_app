"""SolverOutputContract — typed contract for the 20-field dict
``run_target_seeking_orchestrated_system_run`` returns to its
caller (the API handler at intake_consult.py:7276+).

This is the fourth of seven typed inter-stage contracts. Spec:
``docs/architecture/p3_40_contract_4_solver_output_spec.md``
(commit d66cca0). Trace + Flag 0 resolution:
``docs/architecture/p3_40_contract_4_solver_output_trace.md``
(commits 7492a00 + 28c2444).

Flag 0 resolution: the v2-inventory "Boundary 6" surface
(``build_python_finmo_json(model_input_json)``) is already typed
end-to-end by Contract 1's gates at
``finmo_bridge.py:619`` (consumer-side) and
``post_intake_initial_grid/runner.py:1809-1822`` (producer-side).
Contract 4 pivots to Surface B -- the orchestrator's 14-key
return dict + 5 phantom-read API-handler fields = 20 typed
fields total -- consumed by the API handler at
``intake_consult.py:7276``.

Composition map (PSL1 / Flag 1):

  - ``model_input_json``         -> Contract 1
                                    (``FinmoModelInputContract``)
                                    -- final solver-mutated state
  - ``finmo_json``               -> Contract 2
                                    (``FinmoOutputContract``)
                                    -- producer same as Contract 2's
                                       typed shape (TC2 from Contract 3)
  - ``payroll_headcount``        -> Contract 2
                                    (``PayrollHeadcountContract``,
                                     Optional)
  - ``debt_schedule``            -> Contract 2
                                    (``DebtScheduleContract``,
                                     Optional)
  - ``capital_lease_schedule``   -> ``CapitalLeaseScheduleContract``
                                    NEW sub-contract here (Flag 5
                                    override per Nick's directive)

Flag 5 override rationale: debt_schedule and capital_lease_schedule
are sibling outputs from the same post-cash-pass region
(orchestrator.py:3128 debt; orchestrator.py:3144 capital_lease).
Typing one but not the other creates asymmetry; the producer
emits a structured shape either way. Typing captures what IS
being emitted rather than imposing new requirements upstream.
Matches the "don't loosen anything" stance applied throughout
Contracts 1-3 (Tier-F kept-required, Flag 8(a) tightening,
Contract 2 Flag 1 keep-required).

The 11 typed CapitalLeaseScheduleRow fields and 9 typed
CapitalLeaseScheduleContract envelope fields are lifted
VERBATIM from the writer at
``post_intake_capital_lease/schedule.py:197-261``
(``build_capital_lease_schedule_snapshot``). NOT in
workbook_payload_contract.py -- Contract 4 is its first
consumer; if Contract 2 or a future contract needs it, they
re-import from solver_output_contract.py.

Divergence from DebtScheduleContract envelope (documented for
future maintainers): capital_lease_schedule has 9 envelope fields
(schedule_method / depreciation_quarters / per_quarter_depreciation
/ opening_balance_seed / interest_rate at envelope level) vs
debt_schedule's 11 (no source_of_truth / lookup_function /
finmo_formula_unchanged / model_input_drivers / persisted_column
here). Row shape: 11 fields vs 19. No aliases (debt_schedule
has opening_debt/opening_principal_balance pairs). Lease-specific
fields: rou_asset_opening, rou_asset_closing,
lease_asset_depreciation. Same trace-before-write discipline as
DebtScheduleContract in Contract 2 Commit 1a.

Phantom-read fields (PSL2 / Flag 3): five fields the API handler
reads at intake_consult.py:7418-7434 that the solver never
stamps -- typed here as Optional[Dict[str, Any]] = None +
Optional[str] = None for draft_id. Documents the silent-empty
path at type level rather than ad-hoc .get() {} chains.
R-residual (R9): audit the API handler's downstream dependencies
on these fields, then drop both the contract fields AND the
handler reads as dead code.

Cross-field invariants (per spec section 4):

  1. plan_confidence Literal -- declarative, no validator.
     11 values enumerated verbatim from production
     (adaptation_cascade.py:52-59 constants + 3 ad-hoc strings).
  2. Composition-inherited invariants from Contracts 1 + 2.
  3. plan_confidence_matches_cascade_presence (Flag 4(c) add):
     if adaptation_cascade_diagnostics is not None,
     plan_confidence MUST NOT be "high_no_adaptation" (which
     means cascade did not fire). If adaptation_cascade_diagnostics
     is None, plan_confidence MUST be "high_no_adaptation" or
     "terminal_cause_7" (terminal cause skips cascade).

extra-key policy (per spec Flag 6 / PSL4):

  - ``extra="forbid"`` on top-level SolverOutputContract
    (the 20 fields are fully known at this boundary)
  - ``extra="ignore"`` on CapitalLeaseScheduleContract envelope
    and CapitalLeaseScheduleRow (writer may stamp additional
    keys the API handler doesn't read)

Residual cleanups deliberately deferred (spec section 8):

  - R8. Diagnostic-blob typing for target_seeking_diagnostics /
    adaptation_cascade_diagnostics / adaptive_policy /
    gpt_call_budget_diagnostic / handler_trace_diagnostic /
    solver_target_assertion / realism_memo_json /
    post_cascade_completion. Opaque first cut.
  - R9. Phantom-read audit + drop. Verify no downstream consumer
    needs the 5 phantom-read fields, then remove the contract
    fields AND the handler reads.
  - R10. Promote 3 ad-hoc plan_confidence strings to
    PLAN_CONFIDENCE_* constants. Code-hygiene.
  - R11. CapitalLeaseScheduleContract residual: not applicable
    here -- the override-(b) call landed the sub-contract.
  - R12. Inner-runner Phase-8 bypass cleanup ("status" field
    inherited from inner_result is a known Phase-8 leftover).
  - R13. Per-stamp-site producer gates at the two
    `return next_result` sites in orchestrator.py.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  model_validator,
)

# Contract 1 composition: model_input_json speaks FinmoModelInputContract.
# ContractViolation re-exported here so gate callers import from one place.
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
  FinmoModelInputContract,
)
# Contract 2 composition: finmo_json + payroll_headcount + debt_schedule.
# Same class identities Contract 2 uses; no type drift possible across
# boundaries.
from client_intake_and_finmo.post_intake_contracts.workbook_payload_contract import (
  DebtScheduleContract,
  FinmoOutputContract,
  PayrollHeadcountContract,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label for the consumer-side gate at this boundary. Used in
#: ContractViolation.stage and diagnostic_data.stage. Names the
#: producer -> consumer direction at the actual handoff (solver
#: returns to the API handler), not the v2-inventory's outdated
#: "SOLVER -> FINMO_BUILD" framing that the trace doc's Flag 0
#: resolution superseded.
SOLVER_OUTPUT_STAGE_LABEL = "SOLVER->API_HANDLER"

#: Closed set of plan_confidence values. Lifted verbatim from
#: production: 8 PLAN_CONFIDENCE_* constants at
#: adaptation_cascade.py:52-59 + 3 ad-hoc string-literal sites
#: (adaptation_cascade.py:909, :936; orchestrator.py:1690). Per
#: Flag 4(a) the Literal pins all 11. Per Flag 4(b) (deferred to
#: R10) the 3 ad-hoc strings should eventually be promoted to
#: PLAN_CONFIDENCE_* constants for symmetry, but that's
#: code-hygiene not contract-shape.
SUPPORTED_PLAN_CONFIDENCE_VALUES = (
  # 8 PLAN_CONFIDENCE_* constants (adaptation_cascade.py:52-59)
  "high_no_adaptation",
  "medium_gpt_band_relaxation",
  "medium_cohort_fallback",
  "low_target_tolerance_widened",
  "low_supplementary_levers_used",
  "low_planning_mode_shifted",
  "low_stage_family_widened",
  "generic_fallback_no_calibration",
  # 3 ad-hoc string-literal sites
  "restoration_after_cascade_exhausted",      # cascade.py:909
  "restoration_with_documented_adjustments",  # cascade.py:936
  "terminal_cause_7",                          # orchestrator.py:1690
)


# ---------------------------------------------------------------------------
# CapitalLeaseScheduleRow + CapitalLeaseScheduleContract (Flag 5 override)
# ---------------------------------------------------------------------------

class CapitalLeaseScheduleRow(BaseModel):
  """One row in ``capital_lease_schedule.rows`` as emitted by
  ``build_capital_lease_schedule_snapshot`` at
  ``post_intake_capital_lease/schedule.py:222-251``.

  11 typed fields. Numeric fields type as ``float`` per the
  Contract 2 1a-fix lesson: the writer uses ``_safe_int`` but
  downstream consumers may receive int / float / Decimal values;
  ``float`` accepts all three via Pydantic v2 coercion. Strict
  ``int`` typing would reject any future writer path that emits
  a fractional value (rounding artifact, computed average, etc.).

  ``date`` types as ``Optional[Any]`` because the writer pulls
  from ``finmo_row.get("date")`` without normalization -- production
  may emit str ISO-date, None, or other shapes.

  ``finmo_formula`` carries the parallel-builder formula string
  for diagnostic queries.
  """

  quarter_index: int = Field(ge=1, le=20)
  date: Optional[Any] = None
  opening_balance: float
  principal_payment: float
  interest_payment: float
  closing_balance: float
  rou_asset_opening: float
  rou_asset_closing: float
  lease_asset_depreciation: float
  interest_rate: float
  finmo_formula: str = Field(min_length=1)

  model_config = ConfigDict(extra="ignore")


class CapitalLeaseScheduleContract(BaseModel):
  """The ``capital_lease_schedule`` payload at the solver-output
  boundary, as emitted by ``build_capital_lease_schedule_snapshot``
  at ``post_intake_capital_lease/schedule.py:197-261``.

  9 typed envelope fields + 20 row entries (horizon_quarters
  default).

  Differences from Contract 2's DebtScheduleContract envelope:
  - schedule_method (Literal here; not present on debt).
  - depreciation_quarters + per_quarter_depreciation +
    opening_balance_seed + interest_rate at envelope level.
  - NO source_of_truth / lookup_function /
    finmo_formula_unchanged / model_input_drivers / persisted_column
    fields (debt has all five).

  Producer reference for envelope shape: line 251-261 of
  ``post_intake_capital_lease/schedule.py``.
  """

  contract_version: Literal["post_intake_capital_lease_schedule_v1"]
  schedule_role: Literal["persisted_final_capital_lease_schedule"]
  source_stage: str
  horizon_quarters: int = Field(ge=1)
  depreciation_quarters: int = Field(ge=1)
  opening_balance_seed: float
  interest_rate: float
  per_quarter_depreciation: float
  schedule_method: Literal["declining_balance_straight_line_depreciation"]
  rows: List[CapitalLeaseScheduleRow]

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Top-level SolverOutputContract
# ---------------------------------------------------------------------------

class SolverOutputContract(BaseModel):
  """The 20-field dict that
  ``run_target_seeking_orchestrated_system_run`` returns to its
  caller (intake_consult API handler at intake_consult.py:7276).

  Field roster (15 orchestrator-stamped + 5 API-handler
  phantom-read):

  Tier A -- composition with Contracts 1 + 2 (PSL1):
    - model_input_json: FinmoModelInputContract
    - finmo_json: FinmoOutputContract
    - payroll_headcount: Optional[PayrollHeadcountContract]
    - debt_schedule: Optional[DebtScheduleContract]
    - capital_lease_schedule: Optional[CapitalLeaseScheduleContract]
      (NEW sub-contract here per Flag 5 override)

  Tier B -- Literal pin (PSL5):
    - plan_confidence: Literal of 11 values

  Tier C -- opaque diagnostic blobs (PSL5 defers structured typing):
    - target_seeking_diagnostics, adaptation_cascade_diagnostics,
      adaptive_policy, gpt_call_budget_diagnostic,
      handler_trace_diagnostic, solver_target_assertion,
      realism_memo_json, post_cascade_completion

  Tier E -- Phase-8 bypass artifact (R12 cleanup):
    - status

  Tier D -- phantom-read fields (PSL2 (a)):
    - planning_run_json, numeric_solver_feedback_json,
      planning_runtime_json, planning_context_summary_json,
      draft_id

  Total: 20 typed fields. extra='forbid' top-level per Flag 6.
  """

  # Tier A -- composition with Contracts 1 + 2
  model_input_json: FinmoModelInputContract
  finmo_json: FinmoOutputContract
  payroll_headcount: Optional[PayrollHeadcountContract] = None
  debt_schedule: Optional[DebtScheduleContract] = None
  capital_lease_schedule: Optional[CapitalLeaseScheduleContract] = None

  # Tier B -- Literal pin (11 values per Flag 4(a))
  plan_confidence: Literal[
    "high_no_adaptation",
    "medium_gpt_band_relaxation",
    "medium_cohort_fallback",
    "low_target_tolerance_widened",
    "low_supplementary_levers_used",
    "low_planning_mode_shifted",
    "low_stage_family_widened",
    "generic_fallback_no_calibration",
    "restoration_after_cascade_exhausted",
    "restoration_with_documented_adjustments",
    "terminal_cause_7",
  ]

  # Tier C -- diagnostic blobs (opaque first cut)
  target_seeking_diagnostics: Dict[str, Any]
  adaptation_cascade_diagnostics: Optional[Dict[str, Any]] = None
  adaptive_policy: Dict[str, Any]
  gpt_call_budget_diagnostic: Optional[Dict[str, Any]] = None
  handler_trace_diagnostic: Optional[Dict[str, Any]] = None
  solver_target_assertion: Optional[Dict[str, Any]] = None
  realism_memo_json: Optional[Dict[str, Any]] = None
  post_cascade_completion: Optional[Dict[str, Any]] = None

  # Tier E -- Phase-8 bypass artifact
  status: Optional[str] = None

  # Tier D -- phantom-read fields (PSL2 (a))
  planning_run_json: Optional[Dict[str, Any]] = None
  numeric_solver_feedback_json: Optional[Dict[str, Any]] = None
  planning_runtime_json: Optional[Dict[str, Any]] = None
  planning_context_summary_json: Optional[Dict[str, Any]] = None
  draft_id: Optional[str] = None

  model_config = ConfigDict(extra="forbid")

  # -------------------------------------------------------------------------
  # Cross-field invariants (spec section 4)
  # -------------------------------------------------------------------------

  @model_validator(mode="after")
  def plan_confidence_matches_cascade_presence(
    self,
  ) -> "SolverOutputContract":
    """Invariant 4.3 / Flag 4(c). The two fields are co-stamped
    manually at orchestrator.py:1707 (plan_confidence) and 1709
    (adaptation_cascade_diagnostics inside an `if cascade_diagnostics
    is not None` block). They must agree:

      - If cascade FIRED (adaptation_cascade_diagnostics is not None),
        plan_confidence MUST NOT be "high_no_adaptation" (that
        value is the no-cascade init at orchestrator.py:1597).
      - If cascade DID NOT FIRE (adaptation_cascade_diagnostics is
        None), plan_confidence MUST be either "high_no_adaptation"
        or "terminal_cause_7" (terminal cause skips cascade per
        orchestrator.py:1690 assignment).

    Catches drift if a future code path stamps one without the
    other.
    """
    cascade_fired = self.adaptation_cascade_diagnostics is not None
    if cascade_fired and self.plan_confidence == "high_no_adaptation":
      raise ValueError(
        "adaptation_cascade_diagnostics is present (cascade fired) "
        "but plan_confidence is 'high_no_adaptation' (the no-cascade "
        "init value); one of the two stamps drifted -- see "
        "orchestrator.py:1707 + :1709 for the canonical co-stamp pair"
      )
    if not cascade_fired and self.plan_confidence not in (
      "high_no_adaptation",
      "terminal_cause_7",
    ):
      raise ValueError(
        f"adaptation_cascade_diagnostics is absent (cascade did not "
        f"fire) but plan_confidence is {self.plan_confidence!r}; "
        f"absent-cascade is only valid with 'high_no_adaptation' "
        f"(no-cascade init) or 'terminal_cause_7' (terminal skip)"
      )
    return self


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "SOLVER_OUTPUT_STAGE_LABEL",
  "SUPPORTED_PLAN_CONFIDENCE_VALUES",
  "CapitalLeaseScheduleRow",
  "CapitalLeaseScheduleContract",
  "SolverOutputContract",
  # Re-exported from prior contracts for one-stop import at gate
  # call sites:
  "ContractViolation",
  "FinmoModelInputContract",
  "FinmoOutputContract",
  "PayrollHeadcountContract",
  "DebtScheduleContract",
]
