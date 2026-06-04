"""WorkbookPayloadContract — typed contract for the
``DraftWorkbookData`` payload at the FINMO_BUILD → WORKBOOK
boundary (Boundary 7).

This is the second of seven typed inter-stage contracts. Spec:
``docs/architecture/p3_40_contract_2_workbook_payload_spec.md``
(commit 6043850).

The 6 dict fields wrapped by
``client_statements_output_excel/data.py::DraftWorkbookData`` are
each typed here:

  - ``model_input_json``   -> composes Contract 1
                              (``FinmoModelInputContract``)
  - ``finmo_json``         -> ``FinmoOutputContract``
  - ``payroll_headcount``  -> ``PayrollHeadcountContract``
  - ``debt_schedule``      -> ``DebtScheduleContract``
  - ``planning_run_json``  -> ``PlanningRunJsonForWorkbookContract``
                              (thin; only the workbook-reachable path)
  - ``run_diagnostics``    -> ``RunDiagnosticsContract``  (Optional)

extra-key policy (per spec Flag 2, amended):

  - ``extra="forbid"`` ONLY on ``WorkbookPayloadContract`` (6 fields
    are fully known at the workbook boundary)
  - ``extra="ignore"`` on ALL sub-contract envelopes AND row types,
    because the writers documented in trace tasks T4-T8 add many
    keys the workbook doesn't read (e.g.
    ``finmo_json.accounting_check``, ``payroll_headcount.quarter_totals``,
    ``run_diagnostics.workbook_path``); forbid on rows would reject
    valid production payloads.

Cross-field invariants (per spec §4):

  1. ``WorkbookPayloadContract.stage_ramp_reachable_when_planning_run_populated``
     — chain-raise per Adjustment A. Mirrors the production semantic
     at ``client_statements_output_excel/data.py:185`` which raises
     RuntimeError when ``planning_run_json`` is populated but the
     canonical stage_ramp path is missing.
  2. ``FinmoOutputContract.quarter_rows_length_matches_periods``
  3. ``PayrollHeadcountContract.rows_cover_all_horizon_quarters``
  4. ``FinmoOutputContract.quarter_rows_carry_days_in_quarter``
     — addresses v2 inventory B7 F2 residual (DIV/0 silent
     failures in the workbook's day-count formulas).

Residual cleanups deliberately deferred (spec §8):

  - **R8.** Producer-side validation gates for each of the 5 JSON
    fields at their respective writer call sites (one gate per
    writer is a follow-up; current commit ships consumer-side
    only).

  - **R9.** ``validate_draft_data`` deletion. Once Commit 3 lands,
    the old function is dead. Delete in a follow-up.

  - **R10.** Typed contract for the ``WorkbookBuildContext``
    registry shape, addressing the v2 B7 F4 checks-sheet
    silent-skip residual.

  - **R11.** Deep migration of ``data.py`` defensive patterns to
    typed contract attribute access. Contract 2 Commit 4 (optional)
    does the top-level; helper patterns are R11.

  - **R12.** Reconcile ``debt_schedule`` writer shape with other
    consumers (numeric_solver, fail_fast). Flag 1 (a) keeps the
    field required + typed here; non-workbook consumers should
    eventually validate via this same contract.

Producer reference for ``debt_schedule`` row shape:
``build_debt_schedule_snapshot`` at
``python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py:355-417``.
The orchestrator at
``python/client_intake_and_finmo/post_intake_solver/orchestrator.py:3098``
post-stamps ``persisted_column`` after build; that field is typed
as Optional below.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  field_validator,
  model_validator,
)

# Contract 1 composition: WorkbookPayloadContract.model_input_json
# is typed as FinmoModelInputContract so both gates speak the same
# shape.
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
  FinmoModelInputContract,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label for the producer/consumer gates at this boundary.
#: Used in ContractViolation.stage and diagnostic_data.stage. Matches
#: the boundary name in the v2 inventory.
WORKBOOK_STAGE_LABEL = "FINMO_BUILD→WORKBOOK"

#: Total period count: 1 stub + 20 live quarters. Matches Contract 1's
#: PERIOD_COUNT; redefined here so workbook callers don't need to
#: cross-import.
PERIOD_COUNT = 21

#: Horizon for per-quarter coverage invariants (payroll, debt schedule).
#: Live quarters are 1..20.
LIVE_QUARTER_COUNT = 20


# ---------------------------------------------------------------------------
# Shared period shape (data.periods entries)
# ---------------------------------------------------------------------------

class WorkbookPeriod(BaseModel):
  """One entry in ``DraftWorkbookData.periods``.

  The shape is whatever the 3-path fallback chain at
  ``client_statements_output_excel/data.py:94-118`` produces. Source
  priority:

    1. ``finmo_json.quarter_rows[i]`` — CARRIES ``days_in_quarter``
    2. ``finmo_json.periods[i]``      — does NOT carry days_in_quarter
    3. ``model_input_json.periods[i]`` — does NOT carry days_in_quarter
    4. Generated stub at data.py:118 (21 blank entries)

  The contract types each field optionally because the four source
  paths emit different shapes. The v2 inventory B7 F2 / F3 residuals
  apply here; per spec §3.1 we type permissively and rely on the
  cross-field invariant at FinmoOutputContract.quarter_rows_carry_days_in_quarter
  to surface the DIV/0 risk on the quarter_rows path specifically.
  """

  slot_index: int = Field(ge=0, le=LIVE_QUARTER_COUNT)
  quarter: Optional[float] = None
  year: Optional[Any] = None
  date: Optional[Any] = None
  days_in_quarter: Optional[float] = None
  is_stub: bool = False

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# FinmoOutputContract  (for the finmo_json field)
# ---------------------------------------------------------------------------

class FinmoStatementRow(BaseModel):
  """One row in ``finmo_json.pl`` / ``balance_sheet`` / ``cash_flow``.
  Producer: ``build_python_finmo_json`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:619-892``."""

  label: str = Field(min_length=1)
  values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

  model_config = ConfigDict(extra="ignore")


class FinmoOutputContract(BaseModel):
  """The ``finmo_json`` payload at the workbook boundary.

  Producer: ``build_python_finmo_json`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:619-892``.
  Reader: ``source_audit_sheet`` (statement rows) +
  ``DraftWorkbookData.periods`` 1st-path fallback (quarter_rows).

  The workbook does NOT read ``accounting_check`` — treated as
  Optional opaque here (T9 Divergence #8).
  """

  contract_version: Literal["finmo_output_v1"]
  finmo_path: str = ""
  periods: List[WorkbookPeriod] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)
  pl: List[FinmoStatementRow] = Field(min_length=1)
  balance_sheet: List[FinmoStatementRow] = Field(min_length=1)
  cash_flow: List[FinmoStatementRow] = Field(min_length=1)

  #: Required when present per spec §4.4; if the workbook's
  #: ``data.periods`` 1st-path fallback walks this list, the
  #: invariant below guarantees each non-stub entry carries
  #: ``days_in_quarter > 0``. Optional at the field level because
  #: ``data.periods`` may legitimately fall back to
  #: ``finmo_json.periods`` (no quarter_rows).
  quarter_rows: Optional[List[Dict[str, Any]]] = None

  #: Written but never read by the workbook (T9 Divergence #8).
  #: Optional opaque.
  accounting_check: Optional[Dict[str, Any]] = None

  model_config = ConfigDict(extra="ignore")

  @model_validator(mode="after")
  def quarter_rows_length_matches_periods(self) -> "FinmoOutputContract":
    """Invariant §4.2. If ``quarter_rows`` is present, its length
    MUST equal ``periods`` length. Today both come from the same
    producer in lockstep; a downstream mutator could drift them."""
    if self.quarter_rows is not None and len(self.quarter_rows) != len(self.periods):
      raise ValueError(
        f"quarter_rows length {len(self.quarter_rows)} does not match "
        f"periods length {len(self.periods)}"
      )
    return self

  @model_validator(mode="after")
  def quarter_rows_carry_days_in_quarter(self) -> "FinmoOutputContract":
    """Invariant §4.4 (addresses v2 inventory B7 F2 residual).
    Every non-stub ``quarter_rows`` entry MUST have
    ``days_in_quarter`` set to a positive number. Without it the
    workbook's day-count formulas at finmo_sheet.py:162 fall back
    to 0 and silently emit DIV/0 errors in the rendered Excel.
    """
    if self.quarter_rows is None:
      return self
    for i, row in enumerate(self.quarter_rows):
      if not isinstance(row, dict):
        continue
      if i == 0:
        continue  # stub; days_in_quarter is allowed to be absent/0
      dq = row.get("days_in_quarter")
      try:
        dq_val = float(dq) if dq is not None else 0.0
      except (TypeError, ValueError):
        dq_val = 0.0
      if dq_val <= 0.0:
        raise ValueError(
          f"quarter_rows[{i}].days_in_quarter is missing or non-positive — "
          "would produce DIV/0 in workbook formulas at finmo_sheet.py:162"
        )
    return self


# ---------------------------------------------------------------------------
# PayrollHeadcountContract
# ---------------------------------------------------------------------------

class PayrollHeadcountRow(BaseModel):
  """One entry in ``payroll_headcount.rows``.

  Producer: ``python/client_intake_and_finmo/post_intake_headcount/schedule.py:1948-1958``
  builds each row via ``{**deepcopy(row), <computed fields>}``. The
  workbook (``build_payroll_schedule_sheet`` at
  ``client_statements_output_excel/schedule_sheets.py:310-326``)
  reads a subset; the per-row writer-added fields (average_fte,
  quarterly_wage_cost, quarterly_taxes_benefits,
  total_quarterly_payroll, etc.) fall under ``extra="ignore"``.

  The workbook treats ``position_title``/``person_name``,
  ``oews_occ_title``/``oews_matched_title``, ``wage_source``/
  ``wage_source_code`` as either-or pairs (uses the first
  non-empty). The contract enforces that each pair has at least
  one populated value.
  """

  quarter_index: int = Field(ge=1, le=LIVE_QUARTER_COUNT)
  staffing_class: Optional[str] = None

  position_title: Optional[str] = None
  person_name: Optional[str] = None
  staffing_class: Optional[str] = None
  oews_occ_title: Optional[str] = None
  oews_matched_title: Optional[str] = None
  starting_fte: float = Field(ge=0)
  hires: float
  annual_wage: float = Field(gt=0)
  payroll_taxes_benefits_percent: float = Field(ge=0, le=1)
  wage_source: Optional[str] = None
  wage_source_code: Optional[str] = None

  model_config = ConfigDict(extra="ignore")

  @model_validator(mode="after")
  def title_or_person_present(self) -> "PayrollHeadcountRow":
    if not (self.position_title or self.person_name):
      raise ValueError(
        "payroll row must have position_title or person_name"
      )
    return self

  @model_validator(mode="after")
  def oews_title_present(self) -> "PayrollHeadcountRow":
    # Key-person rows are identified by person_name (the owner / named
    # leadership), not an OEWS occupation title -- Python injects them from
    # intake and they legitimately carry no oews_occ_title. Supporting-staff
    # rows still REQUIRE an OEWS title (so a builder bug that dropped it on a
    # supporting row is NOT masked by this relaxation).
    is_key_person = (
      str(self.staffing_class or "").strip().lower() == "key_person"
      or (bool(self.person_name) and not (self.oews_occ_title or self.oews_matched_title)
          and not self.position_title)
    )
    if is_key_person:
      return self
    if not (self.oews_occ_title or self.oews_matched_title):
      raise ValueError(
        "payroll row must have oews_occ_title or oews_matched_title"
      )
    return self

  @model_validator(mode="after")
  def wage_source_present(self) -> "PayrollHeadcountRow":
    if not (self.wage_source or self.wage_source_code):
      raise ValueError(
        "payroll row must have wage_source or wage_source_code"
      )
    return self


class PayrollHeadcountContract(BaseModel):
  """The ``payroll_headcount`` payload at the workbook boundary.

  Producer: ``post_intake_headcount/schedule.py:1963``. The workbook
  reads the root fields above + ``rows[i]``. Writer-side fields not
  read by the workbook (T5 unread list:
  ``contract_version``, ``decision_source``, ``client_id``,
  ``policy_code``, ``source_table``, ``source_column``,
  ``schedule_horizon_quarters``, ``headcount_economic_basis``,
  ``quarter_totals``) fall under ``extra="ignore"``.
  """

  capacity_labor_model: str = Field(min_length=1)
  labor_intensity_class: str = Field(min_length=1)
  wage_positioning_tier: str = Field(min_length=1)
  wage_positioning_multiplier: float
  capacity_units_per_supporting_fte: float
  target_payroll_percent_of_revenue: float
  rows: List[PayrollHeadcountRow] = Field(min_length=1)

  model_config = ConfigDict(extra="ignore")

  @model_validator(mode="after")
  def rows_cover_all_horizon_quarters(self) -> "PayrollHeadcountContract":
    """Invariant §4.3. ``rows`` must include at least one entry per
    quarter 1..20. The workbook's payroll summary formulas iterate
    1..20 and silently render zeros for missing quarters; this
    invariant catches the case where the producer wrote fewer rows
    than the horizon."""
    quarters_in_rows = {int(r.quarter_index) for r in self.rows}
    missing = set(range(1, LIVE_QUARTER_COUNT + 1)) - quarters_in_rows
    if missing:
      raise ValueError(
        f"payroll_headcount.rows missing entries for quarters: {sorted(missing)}"
      )
    return self


# ---------------------------------------------------------------------------
# DebtScheduleContract  (per Flag 1 (a); fully typed)
# ---------------------------------------------------------------------------

class DebtScheduleRow(BaseModel):
  """One entry in ``debt_schedule.rows``.

  Producer: ``build_debt_schedule_snapshot`` at
  ``python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py:384-405``
  emits the 19 fields below per quarter. Some are aliases of others:

    - ``opening_principal_balance`` aliases ``opening_debt``
    - ``new_borrowing`` aliases ``actual_debt_issuance``
    - ``total_principal_payment`` aliases ``actual_debt_repayment``
    - ``closing_principal_balance`` aliases ``closing_debt``
    - ``annual_interest_rate`` aliases ``interest_rate``
    - ``available_principal_before_payment`` aliases
      ``available_debt_before_repayment``

  The contract validates each independently rather than treating
  aliases as derived — the writer emits them verbatim and a future
  consumer could legitimately read either name.

  Flag 1 (a) per the user: type as a strict contract (not Optional
  opaque) even though the workbook never reads this field. The
  field is consumed by non-workbook consumers (fail_fast,
  numeric_solver). Validation at the workbook boundary adds shape
  validation as a safety check without loosening anything.
  """

  quarter_index: int = Field(ge=1, le=LIVE_QUARTER_COUNT)
  date: Optional[Any] = None  # comes from finmo row; may be None
  # 1a-fix: numeric financial fields typed as float (not int).
  # Production writer may emit int, float, or Decimal depending on
  # the calculation path; float accepts all three via Pydantic v2
  # default coercion. int rejects fractional values, which would
  # surface false positives if a future writer path produces a
  # non-integer (rounding artifact, computed average, etc.).
  opening_debt: float
  opening_principal_balance: float
  requested_debt_issuance: float
  actual_debt_issuance: float
  new_borrowing: float
  requested_debt_repayment: float
  actual_debt_repayment: float
  total_principal_payment: float
  closing_debt: float
  closing_principal_balance: float
  interest_rate: float
  annual_interest_rate: float
  interest_expense: float
  available_debt_before_repayment: float
  available_principal_before_payment: float
  total_debt_service: float
  finmo_formula: str = Field(min_length=1)

  model_config = ConfigDict(extra="ignore")


class DebtScheduleContract(BaseModel):
  """The ``debt_schedule`` payload persisted to
  ``intake_consult_drafts.debt_schedule`` column.

  Canonical writer: ``build_debt_schedule_snapshot`` at
  ``python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py:407-417``.
  Orchestrator at
  ``python/client_intake_and_finmo/post_intake_solver/orchestrator.py:3098-3104``
  invokes the builder and post-stamps ``persisted_column`` before
  the SQL UPDATE.

  The workbook does NOT read this field (T6); validation here is
  purely a shape gate at the workbook boundary that catches drift
  before the field reaches other consumers downstream.
  """

  contract_version: Literal["post_intake_debt_amortization_schedule_v1"]
  schedule_role: Literal["persisted_final_debt_amortization_schedule"]
  source_of_truth: str = Field(min_length=1)
  lookup_function: str = Field(min_length=1)
  source_stage: str = ""  # often empty in production
  finmo_formula_unchanged: bool
  horizon_quarters: int = Field(ge=1)
  model_input_drivers: List[str] = Field(min_length=1)
  rows: List[DebtScheduleRow] = Field(min_length=1)

  #: Post-stamped by orchestrator.py:3104 just before the SQL
  #: UPDATE. Optional at the field level because the snapshot
  #: builder doesn't include it; the orchestrator adds it.
  persisted_column: Optional[str] = None

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# PlanningRunJsonForWorkbookContract  (thin; one nested path)
# ---------------------------------------------------------------------------

class StageRampQuarter(BaseModel):
  """One entry in ``stage_ramp_contract.quarter_ramp_grid``. The
  workbook reads exactly these 11 named fields per entry at
  ``client_statements_output_excel/schedule_sheets.py:209-221``.
  """

  q: Optional[int] = None
  rev_target: float
  rev_max: float
  rev_spike_max: float
  max_util: float
  cogs_target: float
  cogs_max: float
  marketing_max: float
  rd_max: float
  ga_max: float
  lease_max: float
  ni_floor: float

  model_config = ConfigDict(extra="ignore")


class StageRampContract(BaseModel):
  """Canonical stage-ramp contract written by
  ``orchestrator._build_minimal_convergence_context``
  (Contract 1 fix 5). Reader: ``DraftWorkbookData.stage_ramp_contract``
  property at ``client_statements_output_excel/data.py:151-193``.
  """

  stage_family: Optional[str] = None
  quarter_ramp_grid: List[StageRampQuarter] = Field(min_length=1)

  model_config = ConfigDict(extra="ignore")


class _PlanningRunBusinessWorldContract(BaseModel):
  """``planning_run_json.unified_convergence_context.business_world_contract``
  sub-envelope. Only stage_ramp_contract is workbook-reachable."""

  stage_ramp_contract: Optional[StageRampContract] = None

  model_config = ConfigDict(extra="ignore")


class _PlanningRunUnifiedConvergenceContext(BaseModel):
  """``planning_run_json.unified_convergence_context`` sub-envelope.
  Only business_world_contract.stage_ramp_contract is
  workbook-reachable."""

  business_world_contract: Optional[_PlanningRunBusinessWorldContract] = None

  model_config = ConfigDict(extra="ignore")


class PlanningRunJsonForWorkbookContract(BaseModel):
  """Workbook-relevant subset of ``planning_run_json``.

  The full ``planning_run_json`` has ~30 top-level keys (planning_mode,
  controller_resolution_state, unified_convergence_context, etc.). The
  workbook reads ONE nested path:
  ``unified_convergence_context.business_world_contract.stage_ramp_contract``.

  This contract is intentionally narrow — the full
  ``planning_run_json`` is a sprawling artifact consumed by many
  readers; constraining only the workbook-relevant path keeps this
  contract focused. The chain-raise invariant on
  ``WorkbookPayloadContract`` enforces that when this field is
  non-None, the full canonical path is reachable.
  """

  unified_convergence_context: Optional[_PlanningRunUnifiedConvergenceContext] = None

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# RunDiagnosticsContract  (Optional at top-level)
# ---------------------------------------------------------------------------

class RealismCheckEntry(BaseModel):
  """One entry in ``run_diagnostics.realism_checks``. Producer
  emits more fields per metric (T8 details) but the workbook reads
  only ``metric_key`` and ``passed``."""

  metric_key: str = Field(min_length=1)
  passed: bool

  model_config = ConfigDict(extra="ignore")


class RunDiagnosticsContract(BaseModel):
  """The ``run_diagnostics`` payload.

  Producer: ``build_run_diagnostics_payload`` at
  ``python/client_intake_and_finmo/post_intake_run_diagnostics.py:162``.
  Consumer: ``diagnostics_sheet.build_diagnostics_sheet``. The
  workbook's diagnostics sheet renders ~17 fields; the writer
  emits a couple extra (``workbook_path``, ``captured_at``) that
  are typed here for round-trip fidelity but unused at the
  workbook boundary.
  """

  draft_id: str
  planning_run_id: str
  business_name: str
  business_naics_6: Optional[str] = None
  business_stage: Optional[str] = None
  business_start_date: Optional[str] = None
  planning_mode: Optional[str] = None
  cash_strategy_name: Optional[str] = None
  acceptance_passed: Optional[bool] = None
  acceptance_score: Optional[float] = None
  realism_checks: List[RealismCheckEntry] = Field(default_factory=list)
  handler_fired: bool
  handler_status: Optional[str] = None
  handler_scope: Optional[str] = None
  tool_calls_used: Optional[int] = None
  budget_extension_triggered: Optional[bool] = None
  #: Written by the producer but not read by the workbook.
  workbook_path: Optional[str] = None
  captured_at: Optional[str] = None

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# WorkbookPayloadContract  (top-level; the gate's surface)
# ---------------------------------------------------------------------------

class WorkbookPayloadContract(BaseModel):
  """The 6-field payload at the workbook boundary, composing
  Contract 1 for ``model_input_json``.

  ``extra="forbid"`` ONLY at this level (per Flag 2 amended):
  the 6 fields are fully known here. Sub-contracts use
  ``extra="ignore"`` because their producers add writer-specific
  keys the workbook doesn't read.

  Validation surface for Commit 3:
  ``validate_workbook_payload_at_boundary(data: DraftWorkbookData)``
  at ``post_intake_contracts/enforcement.py`` (added in Commit 3).
  """

  model_input_json: FinmoModelInputContract
  finmo_json: FinmoOutputContract
  payroll_headcount: PayrollHeadcountContract
  debt_schedule: DebtScheduleContract  # required per Flag 1 (a)
  planning_run_json: Optional[PlanningRunJsonForWorkbookContract] = None
  run_diagnostics: Optional[RunDiagnosticsContract] = None

  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="after")
  def stage_ramp_reachable_when_planning_run_populated(
    self,
  ) -> "WorkbookPayloadContract":
    """Invariant §4.1 with chain-raise per Adjustment A.

    Mirrors the production semantic at
    ``client_statements_output_excel/data.py:185`` which raises
    RuntimeError whenever ``planning_run_json`` is populated but
    the full canonical path
    (``unified_convergence_context.business_world_contract.stage_ramp_contract``)
    isn't reachable. Each middle-node None raises with a specific
    message rather than short-circuiting; matches the
    fail-loud-at-the-boundary discipline.
    """
    if self.planning_run_json is None:
      return self
    ucc = self.planning_run_json.unified_convergence_context
    if ucc is None:
      raise ValueError(
        "planning_run_json populated but unified_convergence_context "
        "missing; see data.py:185 RuntimeError equivalent"
      )
    bwc = ucc.business_world_contract
    if bwc is None:
      raise ValueError(
        "planning_run_json populated but business_world_contract missing"
      )
    if bwc.stage_ramp_contract is None:
      raise ValueError(
        "planning_run_json populated but stage_ramp_contract missing "
        "at canonical path"
      )
    return self


# Re-export Contract 1's ContractViolation so workbook callers can
# raise it without importing from finmo_model_input_contract directly.
__all__ = [
  "WORKBOOK_STAGE_LABEL",
  "PERIOD_COUNT",
  "LIVE_QUARTER_COUNT",
  "WorkbookPeriod",
  "FinmoStatementRow",
  "FinmoOutputContract",
  "PayrollHeadcountRow",
  "PayrollHeadcountContract",
  "DebtScheduleRow",
  "DebtScheduleContract",
  "StageRampQuarter",
  "StageRampContract",
  "PlanningRunJsonForWorkbookContract",
  "RealismCheckEntry",
  "RunDiagnosticsContract",
  "WorkbookPayloadContract",
  "ContractViolation",
]
