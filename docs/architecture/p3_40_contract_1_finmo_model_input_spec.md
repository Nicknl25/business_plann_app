# P3.40 Contract 1 — FinmoModelInputContract (Spec)

**Status:** Specification only. No code lands until Nick reviews this doc.
After review, implementation follows the 5-commit sequence in §6 below.

**Boundary covered:** AMALGAMATED_SESSION → MODEL_INPUT (Boundary 4 in
[p3_40_pipeline_data_flow_inventory_v2.md](p3_40_pipeline_data_flow_inventory_v2.md)).

**Predecessor:** the original Contract 1 directive proposed a spec
built from the unused `FinancialModelInputs.to_model_input_json` shape
(`engine_contract_version: "financial_model_inputs_v1"`). Trace tasks
revealed that path is dead in production. The contract below targets
the production payload that FINMO actually consumes today, produced
by `build_python_model_input_json` and stamped further by
`apply_derived_driver_policies_to_model_input`.

---

## 1. Trace Task Findings (condensed)

The 6 pre-implementation trace tasks surfaced 7 substantive
divergences between the original directive's spec and production
code. The revised spec in §3 reflects all of them.

### T0 — Two unrelated `model_input_json` producers (undocumented in original directive)

The original directive's top-level shape (`engine_contract_version: "financial_model_inputs_v1"`)
matches [`FinancialModelInputs.to_model_input_json` at model_inputs.py:537-620](../../python/financial_model_engine/model_inputs.py#L537).
**That method is never called in production.** Grep confirms only
`FinancialModelInputs.from_model_input_json` (the inverse parser) has
production callers. The producer FINMO actually consumes is
[`build_python_model_input_json` at finmo_bridge.py:2927](../../python/client_intake_and_finmo/finmo_bridge.py#L2927),
which returns a different top-level shape with `contract_version: "finmo_model_input_v3"`.

The original spec was describing a dead path. The revised spec
targets the v3 production shape.

The dead `to_model_input_json` method stays in place (out of scope
for Contract 1) and is logged as a separate residual cleanup.

### T1 — No "company-total" revenue row exists

The original spec had a cross-section invariant requiring at least
one revenue row with a "company total" slot key. **Production has no
such row.** Revenue is structured as per-(lob, product, driver) rows
with slot keys following `lob_{N}_product_{M}` (1-indexed) per
[`_revenue_slot_key` at finmo_bridge.py:427](../../python/client_intake_and_finmo/finmo_bridge.py#L427).
Each (lob, product) slot has exactly 3 rows: Capacity, Unit Price,
Utilization (see [finmo_bridge.py:2766](../../python/client_intake_and_finmo/finmo_bridge.py#L2766)).

The replacement invariant in §4 below: every slot has exactly 3
rows with the canonical driver triple.

### T2 — `ScheduleSeed` wrapper doesn't exist in production

The original spec had a `ScheduleSeed(BaseModel)` with an
`opening_balance: float` field. **Production schedule seeds are 10
flat float fields directly on `sections.schedules`.** Producer:
[finmo_bridge.py:2910-2921](../../python/client_intake_and_finmo/finmo_bridge.py#L2910)
declares them at zero; [finmo_bridge.py:3602-3625](../../python/client_intake_and_finmo/finmo_bridge.py#L3602)
fills them from `financials_json`.

Field list (from production source):
- `debt_opening_balance_seed: float (>= 0)`
- `lease_opening_balance_seed: float (>= 0)`
- `ppe_opening_balance_seed: float (>= 0)`
- `forecast_ppe_opening_balance_seed: float (>= 0)`
- `accumulated_depreciation_opening_seed: float (<= 0)` — **SIGNED-NEGATIVE by production convention**, see [finmo_bridge.py:3623](../../python/client_intake_and_finmo/finmo_bridge.py#L3623) (`round(-abs(accum_dep_seed), 6)`)
- `cash_opening_balance_seed: float (>= 0)`
- `accounts_receivable_opening_balance_seed: float (>= 0)`
- `inventory_opening_balance_seed: float (>= 0)`
- `accounts_payable_opening_balance_seed: float (>= 0)`
- `short_term_debt_opening_balance_seed: float (>= 0)`
- `client_reported_ppe_stub: float` — no sign constraint observed
- `rows: List[ScheduleRow]`

The revised spec inlines these directly on `SchedulesSection`.

### T3 — Payroll row label is exactly `"Payroll"`

Confirmed verbatim at [finmo_bridge.py:2800](../../python/client_intake_and_finmo/finmo_bridge.py#L2800).
No change needed.

### T4 — `value_kind` and `input_semantics` enums in original spec are wrong

The original spec listed:
- ExpenseRow `value_kind`: `"percent_of_revenue", "absolute", "derived"`
- BalanceSheetRow `value_kind`: `"days", "absolute", "ratio", "derived"`
- ExpenseRow `input_semantics`: `"positive_is_cost", "positive_is_income"`
- BalanceSheetRow `input_semantics`: `"asset", "liability", "equity"`

**None of those values exist in production.** Per
[`_revenue_input_semantics` + `_simple_input_semantics` at finmo_bridge.py:256-320](../../python/client_intake_and_finmo/finmo_bridge.py#L256),
the actual vocabularies are:

**`value_kind` (single enum across all row types):**
- `"direct_number"` — most rows
- `"ratio"` — % of revenue, % of prior PPE, % of LTD, utilization
- `"day_count"` — AR/AP/Inventory days only

**`input_semantics` (row-type-specific):**

| Row type | Values | Source |
|---|---|---|
| Revenue | `quarter_capacity_units`, `currency_per_unit`, `utilization_ratio`, `direct_input` | [finmo_bridge.py:264-270](../../python/client_intake_and_finmo/finmo_bridge.py#L264) |
| Expenses | `percent_of_revenue`, `percent_of_prior_ppe`, `quarter_currency`, `direct_input` | [finmo_bridge.py:282-295, 319-320](../../python/client_intake_and_finmo/finmo_bridge.py#L282) |
| Balance sheet | `days`, `percent_of_revenue`, `percent_of_long_term_debt`, `quarter_currency`, `direct_input` | [finmo_bridge.py:296-307, 320](../../python/client_intake_and_finmo/finmo_bridge.py#L296) |
| Schedules | `debt_new_borrowing`, `debt_scheduled_repayment`, `capital_expenditures_cash`, `capital_lease_principal_repayments`, `capital_lease_additions_noncash`, `quarter_currency`, `direct_input` | [finmo_bridge.py:308-320](../../python/client_intake_and_finmo/finmo_bridge.py#L308) |

The percent-range validator (`[0,1]`) moves from `value_kind` to
`input_semantics`. It fires when `input_semantics` is in:
`{"percent_of_revenue", "percent_of_prior_ppe", "percent_of_long_term_debt", "utilization_ratio"}`.

### T5 — `controller_write` ↔ `derived_driver` relation is one-directional, not bi-conditional

The original directive proposed:
```
if controller_write and derived_driver is not None:    # A
    raise
if not controller_write and derived_driver is None:    # B
    raise
```

Trace finds **only direction (B) holds in production**. Direction
(A) is violated by 4 row patterns observed today:

| Row | `controller_write` | `derived_driver` | Set at |
|---|---|---|---|
| Payroll (expense) | `False` | `"headcount_schedule_derived"` (= `_PAYROLL_HEADCOUNT_SOURCE`) | [finmo_bridge.py:2817-2818](../../python/client_intake_and_finmo/finmo_bridge.py#L2817), [post_intake_headcount/schedule.py:2466-2467](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2466) |
| Capacity (revenue, when payroll-supported) | `False` | `"payroll_supported_capacity"` | [post_intake_headcount/schedule.py:2596-2597](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2596) |
| **Capex (schedule)** | **`True`** | `"structural_capacity_ppe_derived"` (= `_CAPEX_DEPRECIATION_SOURCE`) | [finmo_bridge.py:1979](../../python/client_intake_and_finmo/finmo_bridge.py#L1979) — does NOT change `controller_write` |
| **Depreciation (expense)** | **`True`** | `"structural_capacity_ppe_derived"` | [finmo_bridge.py:2002](../../python/client_intake_and_finmo/finmo_bridge.py#L2002) — does NOT change `controller_write` |
| **Balance-sheet contextual-seed rows** | **`True`** | `BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY` | [post_intake_balance_sheet/contextual_seed.py:252](../../python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L252) — does NOT change `controller_write` |

Reading from the writers: `derived_driver` actually has two semantic
flavors in production:
- **"Computed"** (`controller_write=False`): Python writes the values
  every pass; authoring tools must not touch.
- **"Seeded"** (`controller_write=True`): Python initialized the
  values from a policy; authoring tools may still override them.

The revised spec keeps only the one-direction constraint:

```
if not controller_write and derived_driver is None:
    raise  # a non-writable row must declare its compute source
# the converse is NOT enforced; derived_driver may be set on writable rows
```

**FLAG:** if this relaxed semantics is wrong (e.g., you'd rather lock
production to a stricter invariant where derived rows are always
non-writable, and the capex/depreciation/balance-sheet-seed cases
get migrated to `controller_write=False`), say so and I'll revise.
Today's production code is inconsistent and the spec just describes
that reality.

Also: balance-sheet rows can be derived too (the original directive
said "trace to confirm"). The revised spec adds `derived_driver` and
`capex_depreciation` (None) / `payroll_supported_capacity` (None) /
`balance_sheet_contextual_seed` (None) metadata fields to the
relevant rows.

### T6 — `named_range` is NOT unique; it's shared per section

Production assigns the same `named_range` to every row in a section:

| Section | `named_range` | Source |
|---|---|---|
| revenue | `"model_input_revenue"` | [finmo_bridge.py:2754](../../python/client_intake_and_finmo/finmo_bridge.py#L2754) |
| expenses | `"model_input_expenses"` | [finmo_bridge.py:2809](../../python/client_intake_and_finmo/finmo_bridge.py#L2809) |
| balance_sheet | `"model_input_balancehseet"` (production typo) | [finmo_bridge.py:2846](../../python/client_intake_and_finmo/finmo_bridge.py#L2846) |
| schedules | `"model_input_schedules"` | [finmo_bridge.py:2874](../../python/client_intake_and_finmo/finmo_bridge.py#L2874) |

The contract validates **per-section uniformity** (all rows in a
section share one named_range), not global uniqueness. The
production typo `"model_input_balancehseet"` is accepted as-is for
backward compat (the workbook reader keys off this string; renaming
requires migrating that reader, out of scope for Contract 1).

The typo is flagged as a residual cleanup in §7.

### T7 (new, surfaced during this re-spec) — bi-conditional constraint, see T5

T5 above. Listed separately because it's a constraint change rather
than an enum / shape divergence.

---

## 2. Top-level production payload

Per [finmo_bridge.py:2895-2924](../../python/client_intake_and_finmo/finmo_bridge.py#L2895),
the model_input_json the FINMO consumer reads carries these
top-level fields:

| Field | Type | Producer note |
|---|---|---|
| `contract_version` | `Literal["finmo_model_input_v3"]` | Required |
| `canonical_lever_vocabulary` | `Literal["model_inputs_controller_write_only"]` | Required |
| `finmo_path` | `str` | Required; often empty in production |
| `business_name` | `str` (non-empty) | Required |
| `start_date` | ISO date string | Required |
| `business_start_date` | ISO date string \| None | Optional |
| `periods` | `List[Period]` (21 entries: 1 stub + 20 live) | Required |
| `lever_catalog` | `Dict[str, Any]` (keyed by lever_id) | Required; opaque blob in Contract 1 |
| `controller_write_levers` | `List[Dict[str, Any]]` | Required; opaque blob in Contract 1 |
| `sections` | `ModelInputSections` | Required; fully typed |
| `derived_driver_policies` | `Optional[Dict[str, Any]]` | Stamped later by `apply_derived_driver_policies_to_model_input` ([finmo_bridge.py:1884](../../python/client_intake_and_finmo/finmo_bridge.py#L1884)); may be absent at producer-side validation, will be present at consumer-side |
| `derived_driver_runtime` | `Optional[Dict[str, Any]]` | Same as above |
| `seed_provenance_json` (per-row) | `Optional[Dict[str, Any]]` on individual rows | Stamped per-row by `_attach_seed_provenance` ([finmo_bridge.py:339-353](../../python/client_intake_and_finmo/finmo_bridge.py#L339)); optional on every row type |

`lever_catalog` and `controller_write_levers` are kept as
`Dict[str, Any]` / `List[Dict[str, Any]]` opaque blobs. Fully typing
them is a future contract tightening; the current contract focuses
on the section-level shape FINMO actually walks.

`derived_driver_policies` and `derived_driver_runtime` are
post-stamped. Producer-side validation may see them absent;
consumer-side validation may see them present. The contract marks
them Optional and does not enforce any internal shape (also a future
tightening).

---

## 3. Field-by-field contract spec

File: `python/client_intake_and_finmo/post_intake_contracts/finmo_model_input_contract.py`

Pydantic v2 BaseModel. `extra="forbid"` on every model. All
finite-value validators raise on NaN/Inf.

### 3.1 Module-level enums

```python
from typing import Literal

ContractVersion = Literal["finmo_model_input_v3"]
CanonicalLeverVocabulary = Literal["model_inputs_controller_write_only"]

ValueKind = Literal["direct_number", "ratio", "day_count"]

RevenueInputSemantics = Literal[
    "quarter_capacity_units",
    "currency_per_unit",
    "utilization_ratio",
    "direct_input",
]

ExpenseInputSemantics = Literal[
    "percent_of_revenue",
    "percent_of_prior_ppe",
    "quarter_currency",
    "direct_input",
]

BalanceSheetInputSemantics = Literal[
    "days",
    "percent_of_revenue",
    "percent_of_long_term_debt",
    "quarter_currency",
    "direct_input",
]

ScheduleInputSemantics = Literal[
    "debt_new_borrowing",
    "debt_scheduled_repayment",
    "capital_expenditures_cash",
    "capital_lease_principal_repayments",
    "capital_lease_additions_noncash",
    "quarter_currency",
    "direct_input",
]

# input_semantics values that bound row values to [0, 1].
_PERCENT_INPUT_SEMANTICS = frozenset({
    "percent_of_revenue",
    "percent_of_prior_ppe",
    "percent_of_long_term_debt",
    "utilization_ratio",
})

PERIOD_COUNT = 21  # 1 stub + 20 live quarters
```

### 3.2 Period

```python
class Period(BaseModel):
    slot_index: int = Field(ge=0, le=20)
    column_index: int = Field(ge=7)        # spreadsheet column index
    column_letter: str = Field(min_length=1)
    year: float                              # production carries year as float, not int
    quarter: float = Field(ge=0)            # 0 for stub, 1..20 for live
    date: str = Field(min_length=10)        # ISO date "YYYY-MM-DD"
    year_fraction: float                     # 0.0 for stub, 1.0 for live
    is_stub: bool

    model_config = ConfigDict(extra="forbid")
```

Periods come from [`_python_model_input_periods` at finmo_bridge.py:2659](../../python/client_intake_and_finmo/finmo_bridge.py#L2659).
Exactly 21 entries total: index 0 is the stub (`is_stub=True`,
`quarter=0.0`, `year_fraction=0.0`); indices 1..20 are live quarters.

### 3.3 RevenueRow

```python
class RevenueRow(BaseModel):
    """Per-(lob, product, driver) revenue row.

    Producer: `build_python_model_input_json` writes 3 rows per
    (lob, product) slot at finmo_bridge.py:2748-2776, one per
    driver in (Capacity, Unit Price, Utilization). Slot keys
    follow `lob_{N}_product_{M}` (1-indexed) per
    `_revenue_slot_key` at finmo_bridge.py:427.

    Lever id format: `revenue::{lob}::{product}::{driver}` per
    `_revenue_lever_id` at finmo_bridge.py:174.

    A row can be marked derived when payroll-supported capacity
    is active (Capacity row only, controller_write=False,
    derived_driver="payroll_supported_capacity"). See T5.
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

    # Optional metadata stamped by upstream
    derived_driver: Optional[str] = None
    payroll_supported_capacity: Optional[Dict[str, Any]] = None
    capacity_shaping: Optional[Dict[str, Any]] = None
    placeholder_lob: Optional[str] = None
    placeholder_product: Optional[str] = None
    lob_slot_index: Optional[int] = None
    product_slot_index: Optional[int] = None
    seed_provenance_json: Optional[Dict[str, Any]] = None
    # Cross-cutting period-scope fields stamped by template
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
            if any(x < 0 or x > 1 for x in self.values):
                raise ValueError(
                    f"values for input_semantics={self.input_semantics!r} "
                    "must be in [0, 1]"
                )
        return self

    @model_validator(mode="after")
    def derived_driver_required_when_not_writable(self) -> "RevenueRow":
        if not self.controller_write and self.derived_driver is None:
            raise ValueError(
                "derived_driver must be set when controller_write is False"
            )
        return self

    model_config = ConfigDict(extra="forbid")
```

### 3.4 ExpenseRow

```python
class ExpenseRow(BaseModel):
    """One expense lever row in `sections.expenses`.

    Producer: `_python_model_input_template` at
    finmo_bridge.py:2795-2830. Lever id format: `expenses::{label}`.

    Two derived rows by production design:
    - Payroll: controller_write=False, derived_driver=
      "headcount_schedule_derived" (set at template + stamped by
      post_intake_headcount/schedule.py:2466). Computed every pass.
    - Depreciation: controller_write=True (NOT False), derived_driver=
      "structural_capacity_ppe_derived" (stamped by
      finmo_bridge.py:2002). Seeded by policy; remains writable.
    """

    named_range: Literal["model_input_expenses"]
    controller_write: bool
    lever_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value_kind: ValueKind
    input_semantics: ExpenseInputSemantics
    values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

    # Optional metadata stamped by upstream
    derived_driver: Optional[str] = None
    capex_depreciation: Optional[Dict[str, Any]] = None  # only on Depreciation row
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
            if any(x < 0 or x > 1 for x in self.values):
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

    model_config = ConfigDict(extra="forbid")
```

### 3.5 BalanceSheetRow

```python
class BalanceSheetRow(BaseModel):
    """One balance-sheet lever row.

    Producer: `_python_model_input_template` at
    finmo_bridge.py:2832-2851. Lever id format: `balance_sheet::{label}`.

    The named_range is the production-literal string
    `"model_input_balancehseet"` (typo, sic). The contract accepts
    the typo for backward compatibility with the workbook reader.
    See `KNOWN_PRODUCTION_TYPO_BALANCE_SHEET_NAMED_RANGE` constant.

    Balance-sheet rows can be derived via the contextual-seed policy
    (post_intake_balance_sheet/contextual_seed.py:252 stamps
    derived_driver=BALANCE_SHEET_CONTEXTUAL_SEED_POLICY_KEY). The
    policy seeds the values but does NOT set controller_write=False;
    authoring tools may still override per T5.
    """

    named_range: Literal["model_input_balancehseet"]  # sic, see docstring
    controller_write: bool
    lever_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value_kind: ValueKind
    input_semantics: BalanceSheetInputSemantics
    values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

    # Optional metadata
    derived_driver: Optional[str] = None
    balance_sheet_contextual_seed: Optional[Dict[str, Any]] = None
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
            if any(x < 0 or x > 1 for x in self.values):
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

    model_config = ConfigDict(extra="forbid")
```

### 3.6 ScheduleRow

```python
class ScheduleRow(BaseModel):
    """One row in `sections.schedules.rows`.

    Producer: `_python_model_input_template` at
    finmo_bridge.py:2865-2880. Lever id format: `schedules::{label}`.

    The Capital Expenditures row is derived (derived_driver=
    "structural_capacity_ppe_derived") but retains controller_write=
    True per T5 (seeded by policy; remains writable).
    """

    named_range: Literal["model_input_schedules"]
    controller_write: bool
    lever_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value_kind: ValueKind
    input_semantics: ScheduleInputSemantics
    values: List[float] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)

    # Optional metadata
    derived_driver: Optional[str] = None
    capex_depreciation: Optional[Dict[str, Any]] = None  # only on Capital Expenditures row
    seed_provenance_json: Optional[Dict[str, Any]] = None

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

    model_config = ConfigDict(extra="forbid")
```

### 3.7 SchedulesSection

```python
class SchedulesSection(BaseModel):
    """Opening-balance seeds + schedule rows.

    All seeds are floats directly on this section (no nested
    ScheduleSeed wrapper — see T2). Sign conventions per
    production code:
    - All asset-side seeds (AR, inventory, cash, PPE) are non-negative.
    - `accumulated_depreciation_opening_seed` is non-positive
      (production stores it as -abs(value); finmo_bridge.py:3623).
    - `client_reported_ppe_stub` has no sign constraint per the
      trace; left unconstrained.
    """

    debt_opening_balance_seed: float = Field(ge=0)
    lease_opening_balance_seed: float = Field(ge=0)
    ppe_opening_balance_seed: float = Field(ge=0)
    forecast_ppe_opening_balance_seed: float = Field(ge=0)
    accumulated_depreciation_opening_seed: float = Field(le=0)
    cash_opening_balance_seed: float = Field(ge=0)
    accounts_receivable_opening_balance_seed: float = Field(ge=0)
    inventory_opening_balance_seed: float = Field(ge=0)
    accounts_payable_opening_balance_seed: float = Field(ge=0)
    short_term_debt_opening_balance_seed: float = Field(ge=0)
    client_reported_ppe_stub: float  # no sign constraint
    rows: List[ScheduleRow] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
```

### 3.8 ModelInputSections

```python
class ModelInputSections(BaseModel):
    revenue: List[RevenueRow] = Field(min_length=1)
    expenses: List[ExpenseRow] = Field(min_length=1)
    balance_sheet: List[BalanceSheetRow] = Field(min_length=1)
    schedules: SchedulesSection

    model_config = ConfigDict(extra="forbid")

    # Cross-section invariants — see §4
```

### 3.9 FinmoModelInputContract (top-level)

```python
class FinmoModelInputContract(BaseModel):
    """The model_input_json payload produced by
    `build_python_model_input_json` (finmo_bridge.py:2927) and read by
    FINMO build via `FinancialModelInputs.from_model_input_json`.

    Top-level shape per finmo_bridge.py:2895-2924. Optional fields
    are post-stamped by `apply_derived_driver_policies_to_model_input`
    and `_attach_seed_provenance`; they may be absent at producer-side
    validation and present at consumer-side validation.

    The dead `FinancialModelInputs.to_model_input_json` path
    (engine_contract_version: "financial_model_inputs_v1") is NOT
    covered by this contract. See P3.40 v2 inventory for context.
    """

    contract_version: ContractVersion
    canonical_lever_vocabulary: CanonicalLeverVocabulary
    finmo_path: str  # often empty
    business_name: str = Field(min_length=1)
    start_date: str = Field(min_length=10)
    business_start_date: Optional[str] = None
    periods: List[Period] = Field(min_length=PERIOD_COUNT, max_length=PERIOD_COUNT)
    lever_catalog: Dict[str, Any]
    controller_write_levers: List[Dict[str, Any]]
    sections: ModelInputSections

    # Post-stamped, optional at validation time
    derived_driver_policies: Optional[Dict[str, Any]] = None
    derived_driver_runtime: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def periods_stub_first_then_live(self) -> "FinmoModelInputContract":
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
```

### 3.10 ContractViolation

Unchanged from the original directive:

```python
class ContractViolation(Exception):
    def __init__(
        self,
        stage: str,
        field: str,
        expected: str,
        actual: str,
        source_payload: Optional[Dict] = None,
    ):
        self.stage = stage
        self.field = field
        self.expected = expected
        self.actual = actual
        self.source_payload = source_payload
        super().__init__(
            f"{stage}: field '{field}' expected {expected}, got {actual}"
        )
```

---

## 4. Cross-section invariants

Implemented as `@model_validator(mode="after")` on `ModelInputSections`.

### 4.1 All rows in each section share one named_range

Per T6. Per-section uniformity; not global uniqueness.

```python
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
```

The Literal types on each row's `named_range` field already enforce
the right value at row instantiation time; this cross-section
validator catches the case where someone constructs ModelInputSections
from heterogeneous rows (e.g., mixing test fixtures).

### 4.2 Revenue: every (lob, product) slot has exactly 3 rows with the canonical driver triple

Per T1.

```python
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
```

### 4.3 Working-capital days rows: complete-or-absent

If any of `{"Accounts Receivable Days", "Inventory Days", "Accounts Payable Days"}`
is present in `balance_sheet`, ALL three must be present. Production
puts all three in `_python_model_input_template`; a partial set
indicates a writer bug.

```python
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
```

### 4.4 Schedule capex+depreciation pairing

If `"Capital Expenditures"` is present in `schedules.rows`, then
`"Depreciation"` MUST be present in `expenses`, and vice versa.
Both are stamped by the same derived-driver policy
([finmo_bridge.py:1979-2003](../../python/client_intake_and_finmo/finmo_bridge.py#L1979));
having one without the other is a writer bug.

```python
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
```

---

## 5. What was dropped from the original directive

Each dropped item with its reason:

1. **`engine_contract_version: Literal["financial_model_inputs_v1"]`** —
   refers to dead path. See T0. Replaced by `contract_version: Literal["finmo_model_input_v3"]`.

2. **`ScheduleSeed` wrapper class** — doesn't exist in production. See T2.
   Replaced by 10 flat float fields directly on `SchedulesSection`.

3. **`ScheduleRow.schedule_type: Literal["debt", "lease", "ppe", "depreciation", "capex"]`** —
   production has no such field. The 5 production schedule labels are
   `"Debt Issuance (New Borrowing)"`, `"Debt Repayment (Scheduled)"`,
   `"Capital Expenditures"`, `"Less: Principal Repayments"`,
   `"Plus: Net Additions"` ([finmo_bridge.py:2865-2870](../../python/client_intake_and_finmo/finmo_bridge.py#L2865)).
   The contract uses `label` (matching production) instead of inventing
   a parallel `schedule_type` field. If a categorical schedule-type
   field is wanted later, it can be added as an `Optional` and back-filled.

4. **`ExpenseRow.value_kind: Literal["percent_of_revenue", "absolute", "derived"]`** —
   wrong vocabulary. See T4. Replaced by production `ValueKind`.

5. **`BalanceSheetRow.value_kind: Literal["days", "absolute", "ratio", "derived"]`** —
   wrong vocabulary. See T4. Replaced by production `ValueKind`.

6. **`ExpenseRow.input_semantics: Literal["positive_is_cost", "positive_is_income"]`** —
   wrong vocabulary. See T4. Replaced by production `ExpenseInputSemantics`.

7. **`BalanceSheetRow.input_semantics: Literal["asset", "liability", "equity"]`** —
   wrong vocabulary. See T4. Replaced by production `BalanceSheetInputSemantics`.

8. **Revenue "company-total row" invariant** — no such row in production.
   See T1. Replaced by "every slot has exactly 3 rows with the canonical driver triple."

9. **Bi-conditional `controller_write ↔ derived_driver` constraint** —
   only one direction holds in production. See T5. Replaced by single
   one-direction constraint (`controller_write=False → derived_driver is not None`).

10. **`named_range` global-uniqueness invariant** — production deliberately
    shares one named_range per section. See T6. Replaced by per-section
    uniformity validator (already implicit in `Literal`-typed
    `named_range` fields; the explicit validator catches construction-time
    drift).

---

## 6. Implementation sequence (5 commits, unchanged from the original directive)

After Nick green-lights this spec, implementation follows:

### Commit 1 — Contract file skeleton + tests

File: `python/client_intake_and_finmo/post_intake_contracts/finmo_model_input_contract.py`

- All classes per §3
- All cross-section validators per §4
- `ContractViolation` exception
- Module-level docstring explaining purpose + boundary + the dead
  `to_model_input_json` distinction (T0)
- Trace findings as docstring notes on affected fields

Tests in `tests/test_p3_40_contract_1_finmo_model_input_*.py`
covering:
- Each enum: valid + invalid string
- Each row type: valid payload, missing field, wrong type, NaN value,
  percent-range out-of-bounds, day_count negative, derived without
  controller_write=False, controller_write=False without derived
- SchedulesSection: each seed positive/negative constraint
- Period: stub-first invariant
- Cross-section: revenue slot triple, WC days complete-or-absent,
  capex+depreciation pairing, named_range uniformity
- Full FinmoModelInputContract: round-trip a real production payload
  captured from a test draft

Target: 40-50 tests.

### Commit 2 — Adapter on FinancialModelInputs

Add `FinancialModelInputs.to_contract()` and
`FinancialModelInputs.from_contract(...)`. These let legacy code
that uses the dataclass round-trip through the contract.

The existing `to_model_input_json` (the dead-path producer) is NOT
removed. The new `to_contract` is the production-aligned
alternative. Document the distinction in both methods' docstrings.

Tests: round-trip equivalence; production-payload round-trip via
`from_model_input_json → to_contract → from_contract → to_model_input_json`.

### Commit 3 — Producer-side enforcement

In `session_factory.py` (or wherever `build_python_finmo_json` is
called from the amalgamated session's plan_state flush), validate
the model_input_json against `FinmoModelInputContract` before
handing to FINMO build. On `ValidationError`, wrap in
`ContractViolation` with `stage="AMALGAMATED_SESSION→MODEL_INPUT"`
and propagate.

New EventCode: `MODEL_INPUT_CONTRACT_VALIDATED` in phase
`AMALGAMATED_SESSION_TERMINAL` (or the closest existing phase if
that one doesn't exist; check phase_codes.py).

Tests: each kind of failing payload raises ContractViolation with
correct stage/field/expected/actual; valid payload validates and
emits.

### Commit 4 — Consumer-side enforcement

In `build_python_finmo_json` entry point, validate the incoming
model_input_json against `FinmoModelInputContract`. Redundant with
Commit 3 by design — catches mutation between producer and consumer.

Emit `MODEL_INPUT_CONTRACT_VALIDATED` on consumer side too;
distinguish `producer` vs `consumer` in diagnostic_data.

Tests: same payload validates on both sides; mutate payload between
producer and consumer → consumer catches.

### Commit 5 — Migrate fallback reads in finmo_bridge.py

Convert `(row or {}).get(...)` patterns inside finmo_bridge.py to
typed contract attribute access. Section by section: revenue,
expenses, balance_sheet, schedules.

After this commit, finmo_bridge's consumption of model_input_json is
fully type-checked. Soft fallbacks for required fields are gone.
Soft fallbacks for Optional fields remain because the contract
permits them.

Tests: run the existing suite, no regressions. Add a regression
test: produce a model_input with a malformed sub-field, confirm
consumer-side ContractViolation fires before finmo_bridge attempts
to read it.

---

## 7. Open flags for Nick's review

These are decisions I'm asking you to confirm before code lands:

1. **T5 relaxed constraint.** Production has rows with
   `controller_write=True` + `derived_driver=<source>` (capex,
   depreciation, balance-sheet contextual-seed). The spec encodes
   only one direction (`controller_write=False → derived_driver is
   not None`). Confirm this matches your intent, or say you want the
   strict bi-conditional and we'll migrate the inconsistent rows in
   a follow-up commit before the contract lands.

2. **Production typo `model_input_balancehseet`.** Accepted as-is in
   the spec. The literal is in production today and the workbook
   reader keys off it. Confirm leaving it OR commit to fixing the
   typo + workbook reader in a separate commit before Contract 1.

3. **Optional `lever_catalog` / `controller_write_levers` / `derived_driver_policies` / `derived_driver_runtime` opacity.** All
   typed as `Dict[str, Any]` / `List[Dict[str, Any]]` in this
   contract. Fully typing them is a future contract tightening (not
   Contract 1). Confirm or push back.

4. **Period `quarter` as float.** Production stores `quarter` as a
   float (`0.0` for stub, `1.0`..`20.0` for live) at
   [finmo_bridge.py:2673, 2688](../../python/client_intake_and_finmo/finmo_bridge.py#L2673).
   The contract types it as `float` to match. If you want
   `int` in the contract (with auto-conversion), say so.

5. **Schedule rows: only 5 known production labels.** The 5 are
   `"Debt Issuance (New Borrowing)"`, `"Debt Repayment (Scheduled)"`,
   `"Capital Expenditures"`, `"Less: Principal Repayments"`,
   `"Plus: Net Additions"`. The contract does NOT enforce a closed
   label set on schedule rows (label is `str`, not Literal). If you
   want a Literal of the 5 known labels, say so.

---

## 8. Known residual cleanups (out of scope for Contract 1)

**P3.40 Contract Layer Cleanup Pass 6/6 final dispositions:**
- R1 → **ASSESSED + KEPT** in Cleanup 4/6 (test callers block removal per Cleanup 3 precedent).
- R2 → **DEFERRED**: "model_input_balancehseet" typo needs coordinated workbook-reader migration.
- R3 → **DEFERRED**: Sub-contract typing of opaque blob fields needs its own trace+spec+multi-commit series.
- R4 → **DEFERRED**: Pre-Contract-1 production cleanup; doesn't affect Contract 1 typing.
- R6 → **DEFERRED**: Deep finmo_bridge.py typed-access migration; multi-week scope.
- R7 → **DEFERRED**: Defensive .get() reads; depends on R3.
- R-pt-vocab (NEW, P3.41 NexGen E2E iter 2) → **DONE**. `ValueKind` + per-section `*InputSemantics` Literals were originally scoped to finmo_bridge's hardcoded fallback returns only, missing the producer's PASS-THROUGH path that returns the mapping table's (`_mapping_formula_contract_for_lever`) `value_kind` + `input_semantics` VERBATIM when a lever has a seeded mapping row. Surfaced by NexGen E2E iter 2: `AMALGAMATED_SESSION->MODEL_INPUT: field 'sections.revenue.0.value_kind' expected Input should be 'direct_number', 'ratio' or 'day_count' (and 37 more error(s)), got 'count'` — `'count'` is the seeded `value_kind` for `revenue::*::*::Capacity` (live `post_intak_mapping_lookup`), passed through verbatim by `_revenue_input_semantics`. Fix completed each pass-through Literal to seed ∪ fallback vocabulary; spec T4's framing ("Single enum across all row types — per spec T4, the original directive's separate per-row-type value_kind enums did not match production") was correct as far as it went but read only the fallback returns. NOT a §0 loosening: `value_kind` + `input_semantics` are controlled system-internal vocabularies that dictate lever math (rounding precision in `_default_precision_for_value_kind`, derivation path in `mapping_formula_defaults`); the Literal stays enforced, it was merely incompletely scoped. The §0 sub-contracts (5b/c/d) stay bare-str because their vocabularies are free-varying business content — this distinction is deliberate. Drift-proofed via the new seed-parity guard at [tests/test_p3_40_contract_1_seed_parity.py](../../tests/test_p3_40_contract_1_seed_parity.py): per-section live-DB query + finmo_bridge source-parse, asserting the seeded + fallback vocabularies remain subsets of each Literal. CI fails loudly with a clear message naming the missing value(s) when either source diverges.

- **R1.** ~~Dead `FinancialModelInputs.to_model_input_json` method at
  [model_inputs.py:537](../../python/financial_model_engine/model_inputs.py#L537).~~
  **ASSESSED in P3.40 Contract Layer Cleanup Commit 4/6;
  METHOD KEPT.** Reader/writer audit confirmed ZERO PRODUCTION
  callers but TWO test callers
  ([tests/test_financial_model_engine_model_inputs.py:145
  + :180](../../tests/test_financial_model_engine_model_inputs.py#L145))
  exercising the round-trip dataclass→JSON path. Per the Cleanup 3
  precedent (any reader including tests blocks removal): tests
  count as callers; the method is testably exercised even though
  production doesn't use it. The method serves as a documented
  round-trip utility and any future contract-aware producer would
  build on it. NOT REMOVED.

- **R2.** ~~Production typo `"model_input_balancehseet"` in
  [finmo_bridge.py:2846](../../python/client_intake_and_finmo/finmo_bridge.py#L2846).~~
  **DEFERRED beyond P3.40 Cleanup Pass.** Renaming requires a
  coordinated migration of the workbook reader (uses the typo as a
  named range identifier). The typo is structurally inert (just a
  string key), causing no runtime issue. Coordinated cleanup
  belongs in a workbook-builder follow-up commit, not the
  contract-layer cleanup pass.

- **R3.** ~~Top-level fields `lever_catalog`, `controller_write_levers`,
  `derived_driver_policies`, `derived_driver_runtime`, per-row
  `seed_provenance_json` / `capex_depreciation` /
  `payroll_supported_capacity` / `balance_sheet_contextual_seed` /
  `capacity_shaping` typed as opaque blobs.~~ **DEFERRED beyond
  P3.40 Cleanup Pass.** Each blob is a candidate for its own typed
  sub-contract retrofit (analog to the 5b/5c/5d Contract 5
  retrofit pattern). Each retrofit needs its own trace + spec doc
  + multi-commit implementation — multi-week work, separate from
  the cleanup pass. Speculative defense-in-depth without a
  documented downstream consumer warranting the typing investment.
  Re-open as a separate "Contract 1 sub-shape typing wave" project
  if/when a consumer needs structural typing of a specific blob.

  **P3.41 NexGen E2E iter 3 amendment:** the R3 first-cut typing was
  itself incomplete — 3 producer-stamped opaque blobs were missing
  from the row classes and tripped `extra="forbid"` at runtime:
  - `BalanceSheetRow.balance_sheet_stock_carryforward` —
    stamped by [finmo_bridge.py:544](../../python/client_intake_and_finmo/finmo_bridge.py#L544)
    on balance-sheet rows whose opening/contributed-equity stock-level
    carryforward adjustments fired (any business with such adjustments).
  - `BalanceSheetRow.mapping_table_presence_applicability` —
    stamped by [finmo_bridge.py:3644](../../python/client_intake_and_finmo/finmo_bridge.py#L3644)
    on the Deferred Revenue (% of Revenue) row (any business with that
    lever; the surfaced violation on NexGen E2E iter 3).
  - `ExpenseRow.payroll_headcount_schedule` —
    stamped by [post_intake_headcount/schedule.py:2488](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2488)
    on the Payroll expense row (universal — any business has Payroll).

  All three added as `Optional[Dict[str, Any]] = None` first-cut
  typing matching the pre-existing R3 disposition for the original 5
  blobs. R3's sub-contract typing wave (still deferred) now covers 8
  blobs instead of 5. Universal producer paths; not NexGen-specific.

  **P3.41 NexGen E2E iter 4 amendment:** `ScheduleRow` was missing the
  4 period-scope fields already declared on `RevenueRow` / `ExpenseRow`
  / `BalanceSheetRow`. The producer
  [`_full_quarter_scope`](../../python/client_intake_and_finmo/finmo_bridge.py#L244)
  stamps `valid_quarter_indices` / `valid_period_columns` /
  `total_period_count` / `writable_full_quarters_only` on every row
  template, including schedule rows (spread via
  [`_empty_controller_write_row`](../../python/client_intake_and_finmo/finmo_bridge.py#L2949)).
  Inventory oversight in the original Contract 1 — the 3 other row
  classes had these declared, `ScheduleRow` did not, and the
  `extra="forbid"` policy tripped on the producer-stamped values.
  All 4 added as `Optional[List[int]] / Optional[List[str]] /
  Optional[int] / Optional[bool]` first-cut typing matching the
  pre-existing declarations on the other row classes (no R3 sub-
  contract typing implied — these are scalars/flat lists). Universal
  across all businesses; not NexGen-specific.

  **P3.41 NexGen E2E iter 5 amendment:** the top-level
  `FinmoModelInputContract` was missing `solver_input`. Producer
  [finmo_bridge.py:3227-3230](../../python/client_intake_and_finmo/finmo_bridge.py#L3227)
  unconditionally stamps `solver_input` via
  `next_payload.setdefault("solver_input", {})` and then populates
  it with `DRIVER_MOVEMENT_ENVELOPE_KEY` + `FINMO_OUTPUT_TARGET_KEY`
  payloads from `assemble_driver_movement_envelope` /
  `assemble_finmo_output_targets`. Stamped for every business going
  through `build_python_model_input_json`; not NexGen-specific.
  Added as `Optional[Dict[str, Any]] = None` first-cut typing
  matching the pattern of the two pre-existing `derived_driver_*`
  fields. R3's sub-contract typing wave now covers 9 blobs (8 row-
  level + 1 top-level); structural typing of the
  driver_movement_envelope + finmo_output_target sub-shapes
  deferred to R3.

- **R4.** ~~Inconsistency: `apply_derived_driver_policies_to_model_input`
  stamps `derived_driver` on capex/depreciation/balance-sheet
  rows but does NOT set `controller_write=False`.~~ **DEFERRED
  beyond P3.40 Cleanup Pass.** This is a pre-Contract-1
  production cleanup, not contract-layer scope. The inconsistency
  doesn't affect Contract 1's typing (both shapes pass the
  contract). Address in a focused finmo_bridge.py harmonization
  commit when production behavior changes warrant it.

- **R6.** ~~Deep migration of finmo_bridge.py to typed contract
  attribute access.~~ **DEFERRED beyond P3.40 Cleanup Pass.**
  Multi-week work scoped to its own series. The remaining
  defensive `(row or {}).get(...)` patterns inside per-row
  helpers stay; each helper needs its own decision on
  validate-at-entry vs trust-caller. Cleanup pass intentionally
  doesn't touch this — too invasive to batch into a cleanup
  commit.

- **R7.** ~~finmo_bridge.py has 478 defensive `.get(...)` calls.~~
  **DEFERRED beyond P3.40 Cleanup Pass.** Depends on R3 (sub-
  contract typing wave) to make typed access possible for the
  Optional sub-field reads. R3 deferred → R7 deferred.

---

## 9. Workflow

This is a doc-only commit. After it lands and Nick signs off, the
5 implementation commits follow per §6. Each implementation commit
gets push + email per the standard workflow.

If during Commit 1 (the contract file itself) I find anything else
that diverges from production, I'll flag it the same way I did the
first round — no silent adjustment.
