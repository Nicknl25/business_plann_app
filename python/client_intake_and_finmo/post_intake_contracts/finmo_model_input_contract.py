"""FinmoModelInputContract — typed contract for the model_input_json
payload at the AMALGAMATED_SESSION → MODEL_INPUT boundary.

This is the first of seven typed inter-stage contracts being added
to the post-intake pipeline. Spec:
``docs/architecture/p3_40_contract_1_finmo_model_input_spec.md``.

Boundary: AMALGAMATED_SESSION → MODEL_INPUT (Boundary 4 in
``docs/architecture/p3_40_pipeline_data_flow_inventory_v2.md``).

Producer (production): ``build_python_model_input_json`` at
``python/client_intake_and_finmo/finmo_bridge.py:2927`` and the
later stamping by ``apply_derived_driver_policies_to_model_input``
at ``python/client_intake_and_finmo/finmo_bridge.py:1859``.

Consumer (production): ``build_python_finmo_json`` at
``python/client_intake_and_finmo/finmo_bridge.py:619`` (via
``FinancialModelInputs.from_model_input_json`` at
``python/financial_model_engine/model_inputs.py:305``).

This contract describes the production ``finmo_model_input_v3``
shape. The unused
``FinancialModelInputs.to_model_input_json`` path (which produces
``engine_contract_version: "financial_model_inputs_v1"``) is NOT
covered. See spec §1 trace finding T0.

Residual cleanups deliberately deferred (spec §8):

- **R1.** Dead ``FinancialModelInputs.to_model_input_json`` method
  at ``python/financial_model_engine/model_inputs.py:537``. Only
  ``from_model_input_json`` is called in production. Delete or
  repurpose in a follow-up commit.

- **R2.** Production typo ``"model_input_balancehseet"`` in
  ``python/client_intake_and_finmo/finmo_bridge.py:2846``. The
  contract's ``BalanceSheetRow.named_range`` Literal accepts the
  typo for backward compat with the workbook reader. A coordinated
  producer + workbook-reader rename is a future cleanup.

- **R3.** Top-level ``lever_catalog``, ``controller_write_levers``,
  ``derived_driver_policies``, ``derived_driver_runtime`` and the
  per-row metadata sub-dicts (``seed_provenance_json``,
  ``capex_depreciation``, ``payroll_supported_capacity``,
  ``balance_sheet_contextual_seed``, ``capacity_shaping``) are all
  typed as opaque ``Dict[str, Any]`` blobs. Each is a candidate for
  its own typed sub-contract in a future commit.

- **R4.** Inconsistency in production:
  ``apply_derived_driver_policies_to_model_input`` stamps
  ``derived_driver`` on capex / depreciation / balance-sheet rows
  but does NOT set ``controller_write=False`` on them (unlike the
  payroll row which gets both). The contract encodes only the one
  direction that holds today
  (``controller_write=False → derived_driver is not None``) — the
  bi-conditional would require migrating the inconsistent rows.
  Spec §7 flag 1 left this as documented ambiguity for separate
  investigation: when ``derived_driver`` is set on a row with
  ``controller_write=True``, is that intentional "seeded but
  writable" or a stamp-but-forgot-to-flip oversight?

- **R5.** Period.quarter is a ``float`` to match production storage
  but constrained to integral values via a field validator (so
  ``0.0``, ``1.0``..``20.0`` are accepted; ``1.5`` is not).
  Migrating production to ``int`` is a future cleanup.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  field_validator,
  model_validator,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Total period count in every row's ``values`` array: 1 stub + 20 live quarters.
#: Comes from ``_python_model_input_periods`` at
#: ``python/client_intake_and_finmo/finmo_bridge.py:2659``.
PERIOD_COUNT = 21

#: ``input_semantics`` values that bound row values to ``[0, 1]``. Per spec T4,
#: the percent-range validator switches on ``input_semantics``, not
#: ``value_kind`` (the original directive conflated them). These values mean
#: "the cell stores a fraction; if a writer ever stores a > 1 here it's a bug
#: even if the value would round-trip back as a percent in some display
#: context."
_PERCENT_INPUT_SEMANTICS = frozenset({
  "percent_of_revenue",
  "percent_of_prior_ppe",
  "percent_of_long_term_debt",
  "utilization_ratio",
})

# CW-017 E9 (engine fragility ledger): float-noise epsilon on the
# percent bounds - a quotient landing at 1.0000000000000002 is
# arithmetic, not an out-of-range ratio. NOT a semantic loosening:
# 1e-9 admits float representation error only.
_PERCENT_FLOAT_EPSILON = 1e-9


# ---------------------------------------------------------------------------
# Enums (Literals)
# ---------------------------------------------------------------------------

#: Top-level ``contract_version`` produced by
#: ``build_python_model_input_json``. The dead
#: ``FinancialModelInputs.to_model_input_json`` produces a DIFFERENT
#: ``engine_contract_version: "financial_model_inputs_v1"`` field, which is
#: deliberately NOT covered by this contract (see R1).
ContractVersion = Literal["finmo_model_input_v3"]

#: Constant declared at ``python/client_intake_and_finmo/finmo_bridge.py:2897``.
CanonicalLeverVocabulary = Literal["model_inputs_controller_write_only"]

#: Production ``value_kind`` enum.
#:
#: PASS-THROUGH SOURCE -- ``_revenue_input_semantics`` and ``_simple_input_semantics`` at
#: ``python/client_intake_and_finmo/finmo_bridge.py:256-320`` have a pass-through path at
#: the top: if the mapping table (``_mapping_formula_contract_for_lever``) specifies
#: ``value_kind`` + ``input_semantics`` for a lever, they are returned VERBATIM. The
#: hardcoded ``direct_number`` / ``ratio`` / ``day_count`` returns are FALLBACK only,
#: fired when no mapping row exists for the lever.
#:
#: The authoritative producer vocabulary is therefore the UNION of:
#:   (a) the code-seeded mapping table (``post_intak_mapping_lookup``), the rows of
#:       which are seeded externally and read at runtime via
#:       ``post_intake_driver_formula_contract`` -- per the P3.41 NexGen E2E iter 2
#:       extraction, distinct active values are: ``count``, ``currency``, ``day_count``,
#:       ``quarter_currency``, ``ratio``;
#:   (b) the finmo_bridge fallback returns at lines 265-320:
#:       ``direct_number``, ``ratio``, ``day_count``.
#:
#: The seed-parity guard at
#: ``tests/test_p3_40_contract_1_seed_parity.py`` asserts this UNION at test time so
#: that future divergence (seed gains a new value_kind / fallback gains a new branch)
#: fails CI loudly with a clear message instead of silently breaking a future E2E run.
#:
#: Original Contract 1 trace (spec T4) read only the fallback returns and missed the
#: pass-through path -- surfaced by NexGen E2E iter 2 where the contract fired on
#: ``value_kind='count'`` (a seed value, not a fallback value). NOT a §0 loosening:
#: ``value_kind`` is a controlled system-internal vocabulary that dictates lever math
#: (rounding, deterministic handling); the Literal stays enforced, it was merely
#: incompletely scoped.
ValueKind = Literal[
  # Seed vocabulary (live post_intak_mapping_lookup, active rows):
  "count",
  "currency",
  "day_count",
  "quarter_currency",
  "ratio",
  # finmo_bridge fallback returns (lines 265-320) when no mapping row exists:
  "direct_number",
]

#: Revenue row ``input_semantics``.
#:
#: Pass-through source per the ``ValueKind`` docstring above. Per-section seed
#: vocabulary extracted from ``post_intak_mapping_lookup`` active rows whose
#: ``lever_id`` starts with ``revenue::``. Note: the seed and fallback DIVERGE here
#: -- the seed uses shorter names (``capacity_units`` / ``unit_price`` / ``ratio``)
#: while the fallback uses descriptive names (``quarter_capacity_units`` /
#: ``currency_per_unit`` / ``utilization_ratio``). The Literal carries both so
#: either path is accepted.
RevenueInputSemantics = Literal[
  # Seed vocabulary (revenue:: rows in post_intak_mapping_lookup):
  "capacity_units",
  "ratio",
  "unit_price",
  # finmo_bridge fallback returns at lines 265-270:
  "quarter_capacity_units",
  "currency_per_unit",
  "utilization_ratio",
  "direct_input",
]

#: Expense row ``input_semantics``. Pass-through source per the ``ValueKind``
#: docstring above; per-section seed extracted from ``expenses::`` rows.
ExpenseInputSemantics = Literal[
  # Seed vocabulary (expenses:: rows):
  "interest_rate",
  "percent_of_pre_tax_income",
  "percent_of_prior_ppe",
  "percent_of_revenue",
  "quarter_currency",
  # finmo_bridge fallback returns at lines 282-295, 319-320:
  "direct_input",
]

#: Balance-sheet row ``input_semantics``. Pass-through source per the ``ValueKind``
#: docstring above; per-section seed extracted from ``balance_sheet::`` rows.
BalanceSheetInputSemantics = Literal[
  # Seed vocabulary (balance_sheet:: rows):
  "days",
  "percent_of_long_term_debt",
  "percent_of_revenue",
  "quarter_currency",
  # finmo_bridge fallback returns at lines 296-307, 320:
  "direct_input",
]

#: Schedule row ``input_semantics``. Pass-through source per the ``ValueKind``
#: docstring above; per-section seed extracted from ``schedules::`` rows.
ScheduleInputSemantics = Literal[
  # Seed vocabulary (schedules:: rows):
  "capital_expenditures_cash",
  "capital_lease_additions_noncash",
  "capital_lease_principal_repayments",
  "debt_new_borrowing",
  "debt_scheduled_repayment",
  # finmo_bridge fallback returns at lines 308-320:
  "quarter_currency",
  "direct_input",
]


# ---------------------------------------------------------------------------
# Period (1 entry per row in ``periods``)
# ---------------------------------------------------------------------------

class Period(BaseModel):
  """One entry in ``periods``. Producer:
  ``_python_model_input_periods`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:2659``. Exactly
  21 entries total: index 0 is the stub (``is_stub=True``,
  ``quarter=0.0``, ``year_fraction=0.0``); indices 1..20 are live
  quarters.
  """

  slot_index: int = Field(ge=0, le=20)
  column_index: int = Field(ge=7)
  column_letter: str = Field(min_length=1)
  year: float
  quarter: float = Field(ge=0)
  date: str = Field(min_length=10)
  year_fraction: float
  is_stub: bool

  @field_validator("quarter")
  @classmethod
  def quarter_must_be_integral(cls, v: float) -> float:
    """Per spec §7 flag 4: ``quarter`` is stored as ``float`` in
    production (``finmo_bridge.py:2673, 2688``) but the values are
    always integral (``0.0`` stub; ``1.0``..``20.0`` live).
    Reject ``1.5`` etc.
    """
    if v != int(v):
      raise ValueError(f"quarter must be a whole number, got {v}")
    return v

  model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Row classes
# ---------------------------------------------------------------------------

class RevenueRow(BaseModel):
  """Per-(lob, product, driver) revenue row.

  Producer: ``build_python_model_input_json`` writes 3 rows per
  (lob, product) slot at
  ``python/client_intake_and_finmo/finmo_bridge.py:2748-2776``, one
  per driver in ``(Capacity, Unit Price, Utilization)``. Slot keys
  follow ``lob_{N}_product_{M}`` (1-indexed) per
  ``_revenue_slot_key`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:427``.

  Lever id format: ``revenue::{lob}::{product}::{driver}`` per
  ``_revenue_lever_id`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:174``.

  A row CAN be marked derived: when payroll-supported capacity is
  active, the Capacity row gets ``controller_write=False`` and
  ``derived_driver="payroll_supported_capacity"`` (set by
  ``post_intake_headcount/schedule.py:2596-2597``).
  """

  named_range: Literal["model_input_revenue"]
  controller_write: bool
  lever_id: str = Field(min_length=1)
  lob: str = Field(min_length=1)
  product: str = Field(min_length=1)
  driver: Literal["Capacity", "Unit Price", "Utilization"]
  revenue_slot_key: str = Field(min_length=1, pattern=r"^lob_\d+_product_\d+$")
  value_kind: ValueKind
  input_semantics: RevenueInputSemantics
  values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

  # Optional metadata stamped by upstream. Each blob is a candidate
  # for its own typed sub-contract in a future commit (R3).
  derived_driver: Optional[str] = None
  payroll_supported_capacity: Optional[Dict[str, Any]] = None
  capacity_shaping: Optional[Dict[str, Any]] = None
  placeholder_lob: Optional[str] = None
  placeholder_product: Optional[str] = None
  lob_slot_index: Optional[int] = None
  product_slot_index: Optional[int] = None
  seed_provenance_json: Optional[Dict[str, Any]] = None
  # Per-quarter provenance stamped by the target solver / exhaustion handler
  # when it applies an exact value to this lever row (target_solver.py:547,
  # handler.py:509): {q: {target_metric, applied_value, tier_used}}.
  applied_by_target_solver_quarters: Optional[Dict[str, Any]] = None
  # Period-scope fields stamped on every row by the template
  # (``_full_quarter_scope`` at finmo_bridge.py:244).
  valid_quarter_indices: Optional[List[int]] = None
  valid_period_columns: Optional[List[str]] = None
  total_period_count: Optional[int] = None
  writable_full_quarters_only: Optional[bool] = None

  @field_validator("values")
  @classmethod
  def values_finite(cls, v: List[float]) -> List[float]:
    if any(math.isnan(x) or math.isinf(x) for x in v):
      raise ValueError("revenue values must be finite (no NaN/inf)")
    return v

  @model_validator(mode="after")
  def percent_range(self) -> "RevenueRow":
    if self.input_semantics in _PERCENT_INPUT_SEMANTICS:
      if any(x < -_PERCENT_FLOAT_EPSILON or x > 1 + _PERCENT_FLOAT_EPSILON for x in self.values):
        raise ValueError(
          f"values for input_semantics={self.input_semantics!r} "
          "must be in [0, 1]"
        )
    return self

  @model_validator(mode="after")
  def derived_driver_required_when_not_writable(self) -> "RevenueRow":
    """One-direction constraint per spec T5: a non-writable row MUST
    declare its compute source. The converse is NOT enforced —
    production has writable rows with derived_driver set (R4)."""
    if not self.controller_write and self.derived_driver is None:
      raise ValueError(
        "derived_driver must be set when controller_write is False"
      )
    return self

  model_config = ConfigDict(extra="forbid")


class ExpenseRow(BaseModel):
  """One expense lever row in ``sections.expenses``.

  Producer: ``_python_model_input_template`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:2795-2830``.
  Lever id format: ``expenses::{label}``.

  Two derived rows by production design:

  - **Payroll**: ``controller_write=False``,
    ``derived_driver="headcount_schedule_derived"``. Set at the
    template (``finmo_bridge.py:2817``) and re-stamped by
    ``post_intake_headcount/schedule.py:2466``. Computed every
    pass; authoring tools must not touch.

  - **Depreciation**: ``controller_write=True`` (NOT False),
    ``derived_driver="structural_capacity_ppe_derived"`` (stamped
    by ``finmo_bridge.py:2002``). Seeded by policy; remains
    writable. The bi-conditional constraint is NOT enforced (R4).
  """

  named_range: Literal["model_input_expenses"]
  controller_write: bool
  lever_id: str = Field(min_length=1)
  label: str = Field(min_length=1)
  value_kind: ValueKind
  input_semantics: ExpenseInputSemantics
  values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

  derived_driver: Optional[str] = None
  capex_depreciation: Optional[Dict[str, Any]] = None  # only on Depreciation row
  #: Stamped by ``post_intake_headcount/schedule.py:2488`` on the Payroll
  #: expense row only (derived row carrying the headcount-schedule
  #: provenance blob). Opaque first-cut typing per R3 (sub-contract
  #: typing deferred).
  payroll_headcount_schedule: Optional[Dict[str, Any]] = None
  seed_provenance_json: Optional[Dict[str, Any]] = None
  valid_quarter_indices: Optional[List[int]] = None
  valid_period_columns: Optional[List[str]] = None
  total_period_count: Optional[int] = None
  writable_full_quarters_only: Optional[bool] = None

  @field_validator("values")
  @classmethod
  def values_finite(cls, v: List[float]) -> List[float]:
    if any(math.isnan(x) or math.isinf(x) for x in v):
      raise ValueError("expense values must be finite (no NaN/inf)")
    return v

  @model_validator(mode="after")
  def percent_range(self) -> "ExpenseRow":
    if self.input_semantics in _PERCENT_INPUT_SEMANTICS:
      if any(x < -_PERCENT_FLOAT_EPSILON or x > 1 + _PERCENT_FLOAT_EPSILON for x in self.values):
        raise ValueError(
          f"values for input_semantics={self.input_semantics!r} "
          "must be in [0, 1]"
        )
    return self

  @model_validator(mode="after")
  def derived_driver_required_when_not_writable(self) -> "ExpenseRow":
    if not self.controller_write and self.derived_driver is None:
      raise ValueError(
        "derived_driver must be set when controller_write is False"
      )
    return self

  # Per-quarter provenance stamped by the target solver / exhaustion handler.
  applied_by_target_solver_quarters: Optional[Dict[str, Any]] = None

  model_config = ConfigDict(extra="forbid")


class BalanceSheetRow(BaseModel):
  """One balance-sheet lever row in ``sections.balance_sheet``.

  Producer: ``_python_model_input_template`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:2832-2851``.
  Lever id format: ``balance_sheet::{label}``.

  ``named_range`` is the production-literal string
  ``"model_input_balancehseet"`` (typo, sic). Accepted as-is per
  spec §7 flag 2; the workbook reader keys off this string and
  renaming requires migrating the reader (R2).

  Balance-sheet rows CAN be derived via the contextual-seed policy
  (``post_intake_balance_sheet/contextual_seed.py:252`` stamps
  ``derived_driver=BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY``).
  The policy seeds values but does NOT set
  ``controller_write=False``; authoring tools may override (R4).
  """

  named_range: Literal["model_input_balancehseet"]  # sic — see R2
  controller_write: bool
  lever_id: str = Field(min_length=1)
  label: str = Field(min_length=1)
  value_kind: ValueKind
  input_semantics: BalanceSheetInputSemantics
  values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

  derived_driver: Optional[str] = None
  balance_sheet_contextual_seed: Optional[Dict[str, Any]] = None
  #: Stamped by ``finmo_bridge.py:544`` on balance-sheet rows where
  #: opening/contributed-equity stock-level carryforward adjustments
  #: fired (any business with such adjustments). Opaque first-cut
  #: typing per R3.
  balance_sheet_stock_carryforward: Optional[Dict[str, Any]] = None
  #: Stamped by ``finmo_bridge.py:3644`` on the Deferred Revenue
  #: (% of Revenue) row (any business with that lever). Captures
  #: source_table + business_applicability_key + applicable flag.
  #: Opaque first-cut typing per R3.
  mapping_table_presence_applicability: Optional[Dict[str, Any]] = None
  seed_provenance_json: Optional[Dict[str, Any]] = None
  valid_quarter_indices: Optional[List[int]] = None
  valid_period_columns: Optional[List[str]] = None
  total_period_count: Optional[int] = None
  writable_full_quarters_only: Optional[bool] = None

  @field_validator("values")
  @classmethod
  def values_finite(cls, v: List[float]) -> List[float]:
    if any(math.isnan(x) or math.isinf(x) for x in v):
      raise ValueError("balance_sheet values must be finite (no NaN/inf)")
    return v

  @model_validator(mode="after")
  def percent_range(self) -> "BalanceSheetRow":
    if self.input_semantics in _PERCENT_INPUT_SEMANTICS:
      if any(x < -_PERCENT_FLOAT_EPSILON or x > 1 + _PERCENT_FLOAT_EPSILON for x in self.values):
        raise ValueError(
          f"values for input_semantics={self.input_semantics!r} "
          "must be in [0, 1]"
        )
    return self

  @model_validator(mode="after")
  def days_nonneg(self) -> "BalanceSheetRow":
    if self.value_kind == "day_count":
      if any(x < 0 for x in self.values):
        raise ValueError("day_count values must be non-negative")
    return self

  @model_validator(mode="after")
  def derived_driver_required_when_not_writable(self) -> "BalanceSheetRow":
    if not self.controller_write and self.derived_driver is None:
      raise ValueError(
        "derived_driver must be set when controller_write is False"
      )
    return self

  # Per-quarter provenance stamped by the target solver / exhaustion handler.
  applied_by_target_solver_quarters: Optional[Dict[str, Any]] = None

  model_config = ConfigDict(extra="forbid")


class ScheduleRow(BaseModel):
  """One row in ``sections.schedules.rows``.

  Producer: ``_python_model_input_template`` at
  ``python/client_intake_and_finmo/finmo_bridge.py:2865-2880``.
  Lever id format: ``schedules::{label}``.

  The five production labels today are
  ``"Debt Issuance (New Borrowing)"``,
  ``"Debt Repayment (Scheduled)"``, ``"Capital Expenditures"``,
  ``"Less: Principal Repayments"``, ``"Plus: Net Additions"``.
  ``label`` is typed as open ``str`` for consistency with the
  other row types (spec §7 flag 5).

  Capital Expenditures is derived (``derived_driver=
  "structural_capacity_ppe_derived"``, stamped by
  ``finmo_bridge.py:1979``) but retains ``controller_write=True``
  per the production seed-not-compute pattern (R4).
  """

  named_range: Literal["model_input_schedules"]
  controller_write: bool
  lever_id: str = Field(min_length=1)
  label: str = Field(min_length=1)
  value_kind: ValueKind
  input_semantics: ScheduleInputSemantics
  values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

  derived_driver: Optional[str] = None
  capex_depreciation: Optional[Dict[str, Any]] = None  # only on Capital Expenditures
  seed_provenance_json: Optional[Dict[str, Any]] = None
  # Period-scope fields stamped on every row by the template
  # (``_full_quarter_scope`` at finmo_bridge.py:244, spread into
  # schedule rows via ``_empty_controller_write_row`` at
  # finmo_bridge.py:2949-2956). Universal across all businesses;
  # mirrors the same 4 fields already declared on Revenue/Expense/
  # BalanceSheet rows. Inventory oversight surfaced by NexGen E2E
  # iter 4 -- the producer is universal, the contract row class
  # was the holdout.
  valid_quarter_indices: Optional[List[int]] = None
  valid_period_columns: Optional[List[str]] = None
  total_period_count: Optional[int] = None
  writable_full_quarters_only: Optional[bool] = None

  @field_validator("values")
  @classmethod
  def values_finite(cls, v: List[float]) -> List[float]:
    if any(math.isnan(x) or math.isinf(x) for x in v):
      raise ValueError("schedule values must be finite (no NaN/inf)")
    return v

  @model_validator(mode="after")
  def derived_driver_required_when_not_writable(self) -> "ScheduleRow":
    if not self.controller_write and self.derived_driver is None:
      raise ValueError(
        "derived_driver must be set when controller_write is False"
      )
    return self

  # Per-quarter provenance stamped by the target solver / exhaustion handler.
  applied_by_target_solver_quarters: Optional[Dict[str, Any]] = None

  model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# SchedulesSection — opening-balance seeds + schedule rows
# ---------------------------------------------------------------------------

class SchedulesSection(BaseModel):
  """Opening-balance seeds plus schedule rows. All seeds are floats
  directly on this section — no nested ``ScheduleSeed`` wrapper
  (spec T2).

  Sign conventions are taken verbatim from production:

  - All asset-side seeds (AR, inventory, cash, PPE, lease, debt,
    AP, STD) are non-negative.
  - ``accumulated_depreciation_opening_seed`` is non-positive:
    production stores it as ``-abs(value)`` at
    ``python/client_intake_and_finmo/finmo_bridge.py:3623``.
  - ``client_reported_ppe_stub`` has no sign constraint per the
    trace; left unconstrained.
  """

  debt_opening_balance_seed: float = Field(ge=0)
  lease_opening_balance_seed: float = Field(ge=0)
  ppe_opening_balance_seed: float = Field(ge=0)
  forecast_ppe_opening_balance_seed: float = Field(ge=0)
  #: Stored as ``-abs(value)`` by ``finmo_bridge.py:3623``.
  accumulated_depreciation_opening_seed: float = Field(le=0)
  cash_opening_balance_seed: float = Field(ge=0)
  accounts_receivable_opening_balance_seed: float = Field(ge=0)
  inventory_opening_balance_seed: float = Field(ge=0)
  accounts_payable_opening_balance_seed: float = Field(ge=0)
  short_term_debt_opening_balance_seed: float = Field(ge=0)
  #: No sign constraint per the trace.
  client_reported_ppe_stub: float
  rows: List[ScheduleRow] = Field(default_factory=list)

  model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# ModelInputSections — cross-section invariants live here
# ---------------------------------------------------------------------------

class ModelInputSections(BaseModel):
  """The four-section payload under ``model_input_json.sections``.

  Cross-section invariants (validators below):

  1. Every section's rows share the same ``named_range`` (per-section
     uniformity per spec T6; the per-row Literal already enforces
     the right string, this validator catches construction-time
     drift when callers mix heterogeneous fixtures).
  2. Every (lob, product) revenue slot has exactly 3 rows with the
     canonical driver triple ``{Capacity, Unit Price, Utilization}``
     (per spec T1; the original directive's company-total invariant
     was wrong).
  3. Working-capital days rows are complete-or-absent: if any of
     ``{"Accounts Receivable Days", "Inventory Days",
     "Accounts Payable Days"}`` is present, all three must be.
  4. ``Capital Expenditures`` (in ``schedules``) and ``Depreciation``
     (in ``expenses``) must both be present or both absent — they
     are stamped by the same derived-driver policy at
     ``finmo_bridge.py:1979-2003`` and having one without the other
     is a writer bug.
  """

  revenue: List[RevenueRow] = Field(min_length=1)
  expenses: List[ExpenseRow] = Field(min_length=1)
  balance_sheet: List[BalanceSheetRow] = Field(min_length=1)
  schedules: SchedulesSection

  @model_validator(mode="after")
  def all_rows_in_section_share_named_range(self) -> "ModelInputSections":
    expected_per_section = [
      ("revenue", self.revenue, "model_input_revenue"),
      ("expenses", self.expenses, "model_input_expenses"),
      ("balance_sheet", self.balance_sheet, "model_input_balancehseet"),  # sic
    ]
    for name, rows, expected in expected_per_section:
      for i, r in enumerate(rows):
        if r.named_range != expected:
          raise ValueError(
            f"section {name}: row {i} has named_range "
            f"{r.named_range!r}, expected {expected!r}"
          )
    for i, r in enumerate(self.schedules.rows):
      if r.named_range != "model_input_schedules":
        raise ValueError(
          f"schedules.rows[{i}].named_range must be "
          f"'model_input_schedules'; got {r.named_range!r}"
        )
    return self

  @model_validator(mode="after")
  def revenue_slots_complete_triple(self) -> "ModelInputSections":
    by_slot: Dict[str, List[RevenueRow]] = {}
    for r in self.revenue:
      by_slot.setdefault(r.revenue_slot_key, []).append(r)
    expected_drivers = {"Capacity", "Unit Price", "Utilization"}
    for slot_key, rows in by_slot.items():
      drivers = {r.driver for r in rows}
      if drivers != expected_drivers:
        missing = expected_drivers - drivers
        extra = drivers - expected_drivers
        raise ValueError(
          f"revenue slot {slot_key!r} must have exactly "
          f"{{Capacity, Unit Price, Utilization}}; "
          f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
      if len(rows) != 3:
        raise ValueError(
          f"revenue slot {slot_key!r} has {len(rows)} rows; "
          "expected exactly 3 (one per canonical driver)"
        )
    return self

  @model_validator(mode="after")
  def working_capital_days_complete_or_absent(self) -> "ModelInputSections":
    wc_labels = {
      "Accounts Receivable Days",
      "Accounts Payable Days",
      "Inventory Days",
    }
    present = {r.label for r in self.balance_sheet if r.label in wc_labels}
    if present and present != wc_labels:
      missing = wc_labels - present
      raise ValueError(
        f"working capital days rows incomplete: missing {sorted(missing)}"
      )
    return self

  @model_validator(mode="after")
  def capex_depreciation_pairing(self) -> "ModelInputSections":
    schedule_labels = {r.label for r in self.schedules.rows}
    expense_labels = {r.label for r in self.expenses}
    has_capex = "Capital Expenditures" in schedule_labels
    has_depreciation = "Depreciation" in expense_labels
    if has_capex != has_depreciation:
      raise ValueError(
        "Capital Expenditures (schedules) and Depreciation (expenses) "
        "must both be present or both absent; got "
        f"capex={has_capex}, depreciation={has_depreciation}"
      )
    return self

  model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Top-level contract
# ---------------------------------------------------------------------------

class FinmoModelInputContract(BaseModel):
  """The ``model_input_json`` payload produced by
  ``build_python_model_input_json``
  (``python/client_intake_and_finmo/finmo_bridge.py:2927``) and
  read by FINMO build via
  ``FinancialModelInputs.from_model_input_json``
  (``python/financial_model_engine/model_inputs.py:305``).

  Top-level shape per
  ``python/client_intake_and_finmo/finmo_bridge.py:2895-2924``.
  The optional fields ``derived_driver_policies`` and
  ``derived_driver_runtime`` are post-stamped by
  ``apply_derived_driver_policies_to_model_input``
  (``finmo_bridge.py:1859``) and may be absent at producer-side
  validation but present at consumer-side validation.

  The dead ``FinancialModelInputs.to_model_input_json`` path
  (``engine_contract_version: "financial_model_inputs_v1"``) is
  NOT covered by this contract (R1).
  """

  contract_version: ContractVersion
  canonical_lever_vocabulary: CanonicalLeverVocabulary
  finmo_path: str  # often empty in production
  business_name: str = Field(min_length=1)
  start_date: str = Field(min_length=10)
  business_start_date: Optional[str] = None
  periods: List[Period] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

  #: Candidate for future tightening — currently opaque. The catalog
  #: is keyed by ``lever_id`` and carries the per-lever metadata the
  #: solver / cascade consume.
  lever_catalog: Dict[str, Any]

  #: Candidate for future tightening — currently opaque. The list
  #: of controller-writable lever metadata rows.
  controller_write_levers: List[Dict[str, Any]]

  sections: ModelInputSections

  #: Candidate for future tightening — currently opaque. Stamped by
  #: ``apply_derived_driver_policies_to_model_input``; may be absent
  #: at producer-side validation.
  derived_driver_policies: Optional[Dict[str, Any]] = None

  #: Candidate for future tightening — currently opaque. Stamped by
  #: the same function as above.
  derived_driver_runtime: Optional[Dict[str, Any]] = None

  #: Stamped unconditionally by ``finmo_bridge.py:3227-3230`` for every
  #: business -- ``next_payload.setdefault("solver_input", {})`` followed
  #: by population with ``DRIVER_MOVEMENT_ENVELOPE_KEY`` and
  #: ``FINMO_OUTPUT_TARGET_KEY`` payloads from
  #: ``assemble_driver_movement_envelope`` /
  #: ``assemble_finmo_output_targets`` at the same site. Universal
  #: across all businesses; inventory oversight in the original
  #: Contract 1 (surfaced by NexGen E2E iter 5). Opaque first-cut
  #: typing matching the pattern of the two derived_driver_* fields
  #: above; sub-contract structural typing deferred to R3's wave.
  solver_input: Optional[Dict[str, Any]] = None

  @model_validator(mode="after")
  def periods_stub_first_then_live(self) -> "FinmoModelInputContract":
    """``periods[0]`` is the stub (quarter=0); ``periods[1..20]`` are
    live quarters with monotonically-increasing ``quarter`` values
    1..20 per ``_python_model_input_periods``
    (``finmo_bridge.py:2659``)."""
    if not self.periods:
      return self
    if not self.periods[0].is_stub:
      raise ValueError("periods[0] must be the stub (is_stub=True)")
    for i, p in enumerate(self.periods[1:], start=1):
      if p.is_stub:
        raise ValueError(f"periods[{i}] must be a live quarter, not a stub")
      if p.quarter != float(i):
        raise ValueError(
          f"periods[{i}].quarter must equal {i}; got {p.quarter}"
        )
    return self

  model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# ContractViolation — wrap pydantic.ValidationError at the boundary
# ---------------------------------------------------------------------------

class ContractViolation(Exception):
  """Raised when a stage boundary receives or emits data that fails
  contract validation.

  The intended use is to wrap pydantic ``ValidationError`` at the
  boundary site so downstream sees a structured failure with the
  stage name, the offending field, and the expected vs actual
  shape — not a generic ``ValidationError`` traceback 200 lines
  removed from the boundary.

  Producer-side enforcement (spec §6 Commit 3) and consumer-side
  enforcement (spec §6 Commit 4) both raise this. The floor's
  terminal trace path should treat ``ContractViolation`` as a
  structural failure rather than a generic exception.
  """

  def __init__(
    self,
    stage: str,
    field: str,
    expected: str,
    actual: str,
    source_payload: Optional[Dict[str, Any]] = None,
  ) -> None:
    self.stage = stage
    self.field = field
    self.expected = expected
    self.actual = actual
    self.source_payload = source_payload
    super().__init__(
      f"{stage}: field '{field}' expected {expected}, got {actual}"
    )


__all__ = [
  "PERIOD_COUNT",
  "ContractVersion",
  "CanonicalLeverVocabulary",
  "ValueKind",
  "RevenueInputSemantics",
  "ExpenseInputSemantics",
  "BalanceSheetInputSemantics",
  "ScheduleInputSemantics",
  "Period",
  "RevenueRow",
  "ExpenseRow",
  "BalanceSheetRow",
  "ScheduleRow",
  "SchedulesSection",
  "ModelInputSections",
  "FinmoModelInputContract",
  "ContractViolation",
]
