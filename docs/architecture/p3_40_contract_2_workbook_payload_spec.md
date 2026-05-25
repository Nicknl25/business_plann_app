# P3.40 Contract 2 — WorkbookPayloadContract (Spec)

**Status:** Specification only. No code lands until Nick reviews this doc.
After review, implementation follows the commit sequence in §6 below.

**Boundary covered:** FINMO_BUILD → WORKBOOK (Boundary 7 in
[p3_40_pipeline_data_flow_inventory_v2.md](p3_40_pipeline_data_flow_inventory_v2.md)).

**Predecessor:** [Contract 1 — FinmoModelInputContract](p3_40_contract_1_finmo_model_input_spec.md)
(landed at SHA b7f3584). Contract 2 composes Contract 1 for the
`model_input_json` field so both gates speak the same shape; the
other 5 fields get NEW typed sub-contracts.

**Lessons applied from Contract 1:**
- Match production vocabulary verbatim. Don't invent semantic models.
- Document the actual call paths. The v2 inventory described Boundary 7
  in shape terms — this trace work documented the actual consumer
  call graph too.
- Flag spec/production divergences explicitly. One large divergence
  surfaced and one structural surprise are documented in §1.
- Conservative scope on cleanup commits is fine. The boundary
  guarantee is the primary value; deeper migrations are R-residuals.

---

## 1. Trace Task Findings

The 9 pre-implementation traces produced 4 substantive divergences
from the original boundary-7 reading and 1 outright structural surprise.
Each is documented with file:line citations and a proposed resolution
for §3 below.

### T1 — Entry point + validation surface

**Entry:** [`build_client_financial_model_workbook(data: DraftWorkbookData)` at workbook_builder.py:30](../../client_statements_output_excel/workbook_builder.py#L30).
Calls [`validate_draft_data(data)` at data.py:212](../../client_statements_output_excel/data.py#L212)
which requires `model_input_json`, `finmo_json`, `payroll_headcount`,
and `debt_schedule` to be non-empty.

`DraftWorkbookData` ([data.py:64-75](../../client_statements_output_excel/data.py#L64))
wraps:
- `draft_row: Dict[str, Any]` — source row dict (incl. business_name fallback)
- `model_input_json: Dict[str, Any]`
- `finmo_json: Dict[str, Any]`
- `payroll_headcount: Dict[str, Any]`
- `debt_schedule: Dict[str, Any]`
- `planning_run_json: Dict[str, Any]` (no presence validator)
- `run_diagnostics: Optional[Dict[str, Any]] = None`

Constructed via [`draft_data_from_row` at data.py:196](../../client_statements_output_excel/data.py#L196),
which uses `parse_json_object` (silent fallback to `{}` on
parse failure) for the 5 dict fields.

### T2 — `DraftWorkbookData` property shapes

11 derived properties; the workbook's actual consumption happens
through these. All shapes are dict-typed; the contract will tighten
each:

| Property | Source path | Shape today | Defensive behavior |
|---|---|---|---|
| `draft_id` | `draft_row.draft_id` or `model_input_json.draft_id` | `str` | empty string fallback |
| `client_id` | `draft_row.client_id` or `payroll_headcount.client_id` | `str` | empty string fallback |
| `business_name` | `draft_row.business_name` or `model_input_json.business_name` or `"Client"` | `str` | hardcoded `"Client"` fallback |
| `periods` | `finmo_json.quarter_rows` → `finmo_json.periods` → `model_input_json.periods` → generated stub | `List[Dict]` (21) | 3-path fallback + generated stub of 21 blank entries |
| `sections` | `model_input_json.sections` | `Dict` | `{}` fallback |
| `revenue_rows` | `sections.revenue` | `List[Dict]` | `[]` fallback |
| `expense_rows` | `sections.expenses` | `List[Dict]` | `[]` fallback |
| `balance_sheet_rows` | `sections.balance_sheet` | `List[Dict]` | `[]` fallback |
| `schedules` | `sections.schedules` | `Dict` | `{}` fallback |
| `schedule_rows` | `schedules.rows` | `List[Dict]` | `[]` fallback |
| `stage_ramp_contract` | `planning_run_json.unified_convergence_context.business_world_contract.stage_ramp_contract` | `Dict` | `{}` only when planning_run_json absent; **raises RuntimeError** if populated but path is missing (per Contract 1 fix 5) |

### T3 — Per-sheet field consumption (the consumer call graph)

Tracing each sheet builder revealed the actual reads:

| Sheet | Reads (from `data`) |
|---|---|
| `workbook_builder.py` | `data.business_name`, `data.run_diagnostics` (passes through) |
| `source_audit_sheet` | `data.periods`, `data.finmo_json["pl"|"balance_sheet"|"cash_flow"]` (each is `List[{label, values}]`) |
| `finmo_sheet` | `data.periods` only (uses `period.get("days_in_quarter")` — see T9 divergence #4); builds all formulas via `ctx` cross-references |
| `model_inputs_sheet` | `data.periods`, `data.revenue_rows`, `data.expense_rows` (via `row_by_label`) |
| `schedule_sheets.build_revenue_drivers` | `data.periods`, `data.revenue_rows`, `data.stage_ramp_contract.quarter_ramp_grid` (11 ramp fields per quarter) |
| `schedule_sheets.build_payroll_schedule` | `data.periods`, `data.payroll_headcount` (root fields + `.rows`) |
| `schedule_sheets.build_debt_schedule` | `data.periods`, `data.schedule_rows`, `data.expense_rows`, `data.schedules` (debt + lease seeds) |
| `schedule_sheets.build_capex_depreciation` | `data.periods`, `data.schedule_rows`, `data.expense_rows`, `data.schedules` (PPE seeds) |
| `schedule_sheets.build_working_capital` | `data.periods`, `data.balance_sheet_rows`, `data.schedules` (5 working-capital seed keys) |
| `schedule_sheets.build_cash_equity` | `data.periods`, `data.balance_sheet_rows`, `data.expense_rows` |
| `diagnostics_sheet` | `data.draft_id`, `data.run_diagnostics` payload (17 fields) |
| `checks_sheet` | **NOTHING from `data`** — `build_checks_sheet(wb, ctx)` only walks the `ctx` registry |

### T4 — `finmo_json` shape (writer side)

Producer: [`build_python_finmo_json` at finmo_bridge.py:619](../../python/client_intake_and_finmo/finmo_bridge.py#L619),
returns at [line 875-892](../../python/client_intake_and_finmo/finmo_bridge.py#L875):

```python
{
  "contract_version": "finmo_output_v1",
  "finmo_path": str,                  # often empty
  "periods": List[Dict],              # 21 entries (1 stub + 20 live)
  "accounting_check": {
    "rows": [
      {"label": "Check", "values": List[str]},          # "OK" / "FAIL"
      {"label": "Accounting Equation Check", "values": List[float]},
    ],
    "all_ok": bool,
    "status_values": List[str],
    "numeric_values": List[float],
  },
  "pl": List[{"label": str, "values": List[float]}],          # 13 income-statement lines
  "balance_sheet": List[{"label": str, "values": List[float]}],  # 23 BS lines
  "cash_flow": List[{"label": str, "values": List[float]}],   # 17 CF lines
  "quarter_rows": List[Dict],         # per-quarter aggregated values + aliases
}
```

`quarter_rows[i]` carries the full FINMO quarter dict (revenue,
cost_of_goods_sold, marketing, …, days_in_quarter, year, date,
quarter) plus aliases added by the bridge: `slot_index`,
`quarter_index`, `cogs`, `g_and_a`, sometimes `distributions`
(alias of `owner_distributions`) and `ending_cash` (alias of
`cash`).

The workbook reads only the `pl` / `balance_sheet` / `cash_flow`
statement rows (via `source_audit_sheet`) and the `quarter_rows`
or `periods` lists (via `data.periods` 3-path fallback). The
`accounting_check` block is written but **never read by the
workbook**.

### T5 — `payroll_headcount` shape (writer side)

Producer: [post_intake_headcount/schedule.py:1963+](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1963).
Returns:

```python
{
  "contract_version": "payroll_headcount_schedule_v1",
  "decision_source": str,
  "draft_id": str,
  "client_id": str,
  "policy_code": str,
  "source_table": "intake_consult_drafts",
  "source_column": str,
  "schedule_horizon_quarters": int,
  "headcount_economic_basis": str,
  "capacity_labor_model": str,
  "labor_intensity_class": str,
  "wage_positioning_tier": str,
  "wage_positioning_multiplier": float,
  "capacity_units_per_supporting_fte": float,
  "target_payroll_percent_of_revenue": float,
  "rows": List[Dict],            # one entry per (quarter, title)
  "quarter_totals": List[Dict],  # 20 entries: {quarter_index, ending_fte, payroll}
}
```

Each `rows[i]` carries (from a pass-through deepcopy + computed
fields):
- `quarter_index`, `staffing_class`, `position_title` OR
  `person_name`, `oews_occ_title` OR `oews_matched_title`,
  `starting_fte`, `hires`, `ending_fte`, `annual_wage`,
  `payroll_taxes_benefits_percent`, `wage_source` OR `wage_source_code`
- Computed by builder: `average_fte`, `quarterly_wage_cost`,
  `quarterly_taxes_benefits`, `total_quarterly_payroll`

The workbook reads:
- Root: `capacity_labor_model`, `labor_intensity_class`,
  `wage_positioning_tier`, `wage_positioning_multiplier`,
  `capacity_units_per_supporting_fte`,
  `target_payroll_percent_of_revenue`
- `rows[i]`: `quarter_index`, `staffing_class`,
  `position_title`/`person_name`, `oews_occ_title`/`oews_matched_title`,
  `starting_fte`, `hires`, `annual_wage`,
  `payroll_taxes_benefits_percent`, `wage_source`/`wage_source_code`

The workbook does NOT read: `quarter_totals`, `contract_version`,
`decision_source`, `client_id` (read only via `data.client_id`
property fallback), `policy_code`, `source_table`, `source_column`,
`schedule_horizon_quarters`, `headcount_economic_basis`,
`rows[i].average_fte`, `rows[i].quarterly_wage_cost`,
`rows[i].quarterly_taxes_benefits`, `rows[i].total_quarterly_payroll`.

### T6 — `debt_schedule` shape (writer side; **discovery: not read by workbook**)

Producer: [`build_short_term_debt_amortization_schedule` at post_intake_debt_schedule/schedule.py:407](../../python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L407).
Returns:

```python
{
  "contract_version": "post_intake_debt_amortization_schedule_v1",
  "schedule_role": "persisted_final_debt_amortization_schedule",
  "source_of_truth": str,
  "lookup_function": str,
  "source_stage": str,
  "finmo_formula_unchanged": bool,
  "horizon_quarters": int,
  "model_input_drivers": List[str],
  "rows": List[Dict],   # per-quarter {opening_debt, debt_issuance, …, total_debt_service, finmo_formula}
}
```

**Workbook consumption:** the workbook never reads `data.debt_schedule`.
Verified by grep across all sheet builders — only `validate_draft_data`
references it. The `build_debt_schedule_sheet` (named misleadingly)
reads from `data.schedule_rows` (i.e., `model_input_json.sections.schedules.rows`)
and `data.schedules` (the seed fields), not from `data.debt_schedule`.

So `data.debt_schedule` is a **REQUIRED-but-UNREAD** field at this
boundary. See §1 divergence #1 below for the contract decision.

### T7 — `planning_run_json` shape (workbook-relevant subset)

The full `planning_run_json` is large (built by
[post_intake_state/runner.py:195+](../../python/client_intake_and_finmo/post_intake_state/runner.py#L195))
with ~30 top-level keys (planning_mode, controller_resolution_state,
unified_convergence_context, etc.). The workbook reads only:

- `planning_run_json["unified_convergence_context"]["business_world_contract"]["stage_ramp_contract"]`
  — via `data.stage_ramp_contract` property (Contract 1 fix 5 collapsed
  the 4-path fallback to this canonical path)

The `stage_ramp_contract` payload itself ([orchestrator.py:436](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L436)
deepcopy from the stage_ramp_contract param) carries:
- `stage_family: str`
- `quarter_ramp_grid: List[Dict]` — 20 per-quarter entries with the
  11 ramp fields the workbook reads:
  - `rev_target`, `rev_max`, `rev_spike_max`
  - `max_util`
  - `cogs_target`, `cogs_max`
  - `marketing_max`, `rd_max`, `ga_max`, `lease_max`
  - `ni_floor`
- Plus other fields the workbook doesn't read.

### T8 — `run_diagnostics` shape (writer side)

Producer: [`build_run_diagnostics_payload` at post_intake_run_diagnostics.py:162](../../python/client_intake_and_finmo/post_intake_run_diagnostics.py#L162),
returns at [line 256](../../python/client_intake_and_finmo/post_intake_run_diagnostics.py#L256):

```python
{
  "draft_id": str,
  "planning_run_id": str,
  "business_name": str,
  "business_naics_6": Optional[str],
  "business_stage": Optional[str],
  "business_start_date": Optional[str],
  "planning_mode": Optional[str],
  "cash_strategy_name": Optional[str],
  "acceptance_passed": Optional[bool],
  "acceptance_score": Optional[float|int],
  "realism_checks": List[Dict],  # each: {metric_key, passed, ...}
  "handler_fired": bool,
  "handler_status": Optional[str],
  "handler_scope": Optional[str],
  "tool_calls_used": Optional[int],
  "budget_extension_triggered": Optional[bool],
  "workbook_path": str,        # written but NOT READ by workbook
  "captured_at": str,          # ISO datetime str; NOT READ by workbook
}
```

`realism_checks[i]` carries `{metric_key: str, passed: bool, …}`
plus other fields the workbook doesn't read.

### T9 — Divergences from the v2 inventory + new findings

**Divergence #1 (NEW — substantive).** v2 inventory listed
`data.debt_schedule` as a workbook input but didn't flag that the
workbook never reads it. Trace confirms: `validate_draft_data`
requires it non-empty (data.py:220), but **zero sheet builders read
it** (verified by grep). This is the inverse of Contract 1's
phantom-read pattern: a REQUIRED-but-UNREAD field. See §3.6 for
resolution.

**Divergence #2 (NEW — structural).** `checks_sheet` consumes
NOTHING from `data` — its signature is `build_checks_sheet(wb, ctx)`
without a `data` parameter. Sheet validations entirely walk the
`WorkbookBuildContext.{finmo_rows, schedule_rows, source_rows,
model_input_rows}` dict registries that other sheet builders
populate. This is consistent with the v2 inventory's note about
checks-sheet silent skip of unmapped rows (B7 F4 residual), but
worth flagging structurally: the contract does NOT need to
constrain anything for the checks sheet specifically — its
"validity" is entirely a function of which rows the other builders
registered.

**Divergence #3 (CONFIRMED).** v2 inventory B7 F1 — `stage_ramp_contract`
4-path silent fallback — was CLOSED by Contract 1 Commit 5
(`07938c8`). The property at [data.py:151-193](../../client_statements_output_excel/data.py#L151)
now reads only the canonical path and raises RuntimeError on
populated-but-missing. The contract reflects this.

**Divergence #4 (CONFIRMED RESIDUAL).** v2 inventory B7 F2 —
`days_in_quarter` defaults to 0 — still present. At
[finmo_sheet.py:162](../../client_statements_output_excel/finmo_sheet.py#L162),
`period.get("days_in_quarter") or 0`. The fallback fires when
`data.periods` is sourced from `finmo_json["periods"]` or
`model_input_json["periods"]` (neither carries `days_in_quarter`)
or from the generated stub. Only `finmo_json["quarter_rows"]` —
the first fallback path — carries `days_in_quarter`. The contract
will encode this: `Period.days_in_quarter` is Optional, but a
contract-level validator can ensure that if `data.periods` is
sourced from `quarter_rows` then the field is required (see §3.2
discussion).

**Divergence #5 (CONFIRMED RESIDUAL).** v2 inventory B7 F3 —
`periods` 3-path fallback creates 21 spurious blank periods — still
present at [data.py:118](../../client_statements_output_excel/data.py#L118).
The contract can encode "at least one of the three sources must
exist" but the generated-stub fallback would need explicit removal
(see §3.2 discussion).

**Divergence #6 (CONFIRMED RESIDUAL).** v2 inventory B7 F4 —
Checks sheet silently skips unmapped rows — still present at
[checks_sheet.py:727](../../client_statements_output_excel/checks_sheet.py#L727).
The contract has no direct hook here (the checks sheet doesn't
read from `data`). The fix is structural in `WorkbookBuildContext`,
out of scope for Contract 2.

**Divergence #7 (CONFIRMED RESIDUAL).** v2 inventory B7 F5 —
`run_diagnostics` load failure is silent at
[export_client_workbook.py:61-78](../../client_statements_output_excel/export_client_workbook.py#L61).
The contract will validate `run_diagnostics` if present but treats
absence as legitimate (matches today's behavior — diagnostics_sheet
falls back to placeholder rendering).

**Divergence #8 (NEW — minor).** `accounting_check` block on
`finmo_json` is written by `build_python_finmo_json` but never read
by the workbook. Similar to `quarter_totals` on `payroll_headcount`.
These are legitimate persistence artifacts consumed by other
systems (validation, fail-fast checks). The contract treats them
as Optional opaque blobs at the workbook boundary.

---

## 2. Top-level production payload

The workbook entry receives `DraftWorkbookData`, which carries 6
top-level dict fields (5 required by the existing validator + 1
optional). The contract validates each:

| Field | Required by existing `validate_draft_data` | Workbook actually reads | Contract type |
|---|---|---|---|
| `model_input_json` | Yes | Yes (extensively, via `sections`/`schedules` properties) | `FinmoModelInputContract` (Contract 1 composition) |
| `finmo_json` | Yes | Yes (statements + period source) | NEW `FinmoOutputContract` |
| `payroll_headcount` | Yes | Yes (root fields + rows) | NEW `PayrollHeadcountContract` |
| `debt_schedule` | Yes | **NO — verified phantom** (T6 + Divergence #1) | NEW `DebtScheduleContract` OR Optional opaque — decision needed (§3.6) |
| `planning_run_json` | No (no current validator) | Yes (only stage_ramp_contract path) | NEW thin `PlanningRunJsonForWorkbookContract` (one nested path) |
| `run_diagnostics` | No (Optional) | Yes (17 fields) when present | NEW `RunDiagnosticsContract` (Optional) |

The contract has TWO surfaces:
- **`WorkbookPayloadContract`**: validates the full 6-field payload at
  the boundary; composes the 5 sub-contracts.
- **Per-field sub-contracts**: each typed individually so other
  consumers (the API handler that emails the workbook, the diagnostics
  loader, etc.) can validate just one field without re-wiring.

---

## 3. Field-by-field contract spec

File: `python/client_intake_and_finmo/post_intake_contracts/workbook_payload_contract.py`

Pydantic v2 BaseModel. `extra="ignore"` on the top-level sub-contracts
(unlike Contract 1's `extra="forbid"`) — the v2 inventory documented
many "written but not read" fields, and forcing forbid would require
the contract to enumerate every writer's field down to opaque
diagnostic blobs. The workbook only needs READ-shape guarantees; we
forbid extra at the workbook-contract level only where the producer is
fully known to us.

Where `extra="forbid"` IS appropriate: nested entries the workbook
walks deterministically (e.g., individual rows in a list it iterates).
Where `extra="ignore"` is appropriate: top-level payloads where the
producer adds many keys we don't read.

### 3.1 Period (shared shape from `data.periods`)

```python
class WorkbookPeriod(BaseModel):
    """One entry in ``data.periods``. Shape after the 3-path fallback
    chain at data.py:94-118 — i.e., what the workbook actually sees.

    Source paths (in priority order):
      1. ``finmo_json.quarter_rows[i]`` — carries days_in_quarter
      2. ``finmo_json.periods[i]`` — does NOT carry days_in_quarter
      3. ``model_input_json.periods[i]`` — does NOT carry days_in_quarter
      4. Generated stub at data.py:118 (21 blank entries with empty year/date)
    """
    slot_index: int = Field(ge=0, le=20)
    quarter: Optional[float] = None      # 0 for stub; 1..20 for live; "" in fallback stub
    year: Optional[Any] = None           # float in production; "" in fallback stub
    date: Optional[Any] = None           # str in production; "" in fallback stub
    days_in_quarter: Optional[float] = None    # Only set when source is quarter_rows
    is_stub: bool = False
    model_config = ConfigDict(extra="ignore")  # quarter_rows carries many extra fields
```

### 3.2 FinmoOutputContract (NEW; for `finmo_json`)

```python
class FinmoStatementRow(BaseModel):
    """One row in ``pl`` / ``balance_sheet`` / ``cash_flow``."""
    label: str = Field(min_length=1)
    values: List[float] = Field(min_length=21, max_length=21)
    model_config = ConfigDict(extra="ignore")  # writer may add extras


class FinmoOutputContract(BaseModel):
    """The ``finmo_json`` payload written by
    ``build_python_finmo_json`` at finmo_bridge.py:619, read by the
    workbook via `data.finmo_json` + `data.periods` 1st-path
    fallback.

    The workbook reads ONLY the statement rows and the periods/
    quarter_rows. `accounting_check` is written by the producer but
    NEVER READ by the workbook (T9 Divergence #8) — treated as
    Optional opaque here.
    """
    contract_version: Literal["finmo_output_v1"]
    finmo_path: str = ""        # often empty in production
    periods: List[WorkbookPeriod] = Field(min_length=21, max_length=21)
    pl: List[FinmoStatementRow] = Field(min_length=1)
    balance_sheet: List[FinmoStatementRow] = Field(min_length=1)
    cash_flow: List[FinmoStatementRow] = Field(min_length=1)
    quarter_rows: Optional[List[Dict[str, Any]]] = None  # Optional; only the periods 1st-path consumes it
    accounting_check: Optional[Dict[str, Any]] = None    # written but not read by workbook
    model_config = ConfigDict(extra="ignore")
```

### 3.3 PayrollHeadcountContract (NEW)

```python
class PayrollHeadcountRow(BaseModel):
    """One row in `payroll_headcount.rows`. Many writer-side fields
    are not read by the workbook (T5 unread list); they fall under
    `extra="ignore"`. Only the workbook-consumed fields are typed.
    """
    quarter_index: int = Field(ge=1, le=20)
    staffing_class: Optional[str] = None
    # Workbook tries position_title OR person_name; one must be set
    position_title: Optional[str] = None
    person_name: Optional[str] = None
    # Workbook tries oews_occ_title OR oews_matched_title; one must be set
    oews_occ_title: Optional[str] = None
    oews_matched_title: Optional[str] = None
    starting_fte: float = Field(ge=0)
    hires: float                          # can be negative for terminations
    annual_wage: float = Field(gt=0)      # writer asserts > 0; contract mirrors
    payroll_taxes_benefits_percent: float = Field(ge=0, le=1)
    # Workbook tries wage_source OR wage_source_code; one must be set
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
    contract_version: Literal["payroll_headcount_schedule_v1"]
    capacity_labor_model: str = Field(min_length=1)
    labor_intensity_class: str = Field(min_length=1)
    wage_positioning_tier: str = Field(min_length=1)
    wage_positioning_multiplier: float
    capacity_units_per_supporting_fte: float
    target_payroll_percent_of_revenue: float
    rows: List[PayrollHeadcountRow] = Field(min_length=1)
    # Many other fields written by the producer (T5 unread list); ignored
    # by extra="ignore" since the workbook doesn't care about them.
    model_config = ConfigDict(extra="ignore")
```

### 3.4 PlanningRunJsonForWorkbookContract (NEW; thin)

The full `planning_run_json` has ~30 top-level keys. The workbook
reads ONE nested path. A thin contract validates just that path,
ignoring the rest:

```python
class StageRampQuarter(BaseModel):
    """One entry in `quarter_ramp_grid`. Per T3 the workbook
    references 11 named fields on each entry."""
    q: Optional[int] = None    # 1..20; producer-set
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
    """`planning_run_json.unified_convergence_context.business_world_contract.stage_ramp_contract`.
    Canonical writer: `orchestrator._build_minimal_convergence_context`
    (Contract 1 spec §6 covered the producer path). Reader is
    `DraftWorkbookData.stage_ramp_contract` property at data.py:151.
    """
    stage_family: Optional[str] = None
    quarter_ramp_grid: List[StageRampQuarter] = Field(min_length=1)
    model_config = ConfigDict(extra="ignore")


class _PlanningRunBusinessWorldContract(BaseModel):
    stage_ramp_contract: Optional[StageRampContract] = None
    model_config = ConfigDict(extra="ignore")


class _PlanningRunUnifiedConvergenceContext(BaseModel):
    business_world_contract: Optional[_PlanningRunBusinessWorldContract] = None
    model_config = ConfigDict(extra="ignore")


class PlanningRunJsonForWorkbookContract(BaseModel):
    """Workbook-relevant subset of `planning_run_json`. Only the
    stage_ramp_contract nested path is workbook-reachable today. The
    contract is intentionally narrow: the full `planning_run_json` is
    a sprawling artifact consumed by many readers; constraining only
    the workbook-relevant path keeps this contract focused.
    """
    unified_convergence_context: Optional[_PlanningRunUnifiedConvergenceContext] = None
    model_config = ConfigDict(extra="ignore")
```

### 3.5 RunDiagnosticsContract (NEW; Optional)

```python
class RealismCheckEntry(BaseModel):
    metric_key: str = Field(min_length=1)
    passed: bool
    model_config = ConfigDict(extra="ignore")


class RunDiagnosticsContract(BaseModel):
    """Producer: `build_run_diagnostics_payload` at
    post_intake_run_diagnostics.py:162. Consumer:
    `diagnostics_sheet.build_diagnostics_sheet`. The contract types
    all the fields the diagnostics sheet renders.
    `workbook_path` and `captured_at` are written but never read by
    the workbook — typed as Optional opaque (T8 unread list).
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
    # Not read by workbook; kept for round-trip fidelity:
    workbook_path: Optional[str] = None
    captured_at: Optional[str] = None
    model_config = ConfigDict(extra="ignore")
```

### 3.6 DebtScheduleContract — DECISION FLAG (see §7)

`data.debt_schedule` is required by `validate_draft_data` but
**never read** by any sheet builder (T6 + T9 Divergence #1). Two
resolutions:

(a) **Type it as a real contract** for the persisted-debt-schedule
    payload shape — informs consumers other than the workbook (the
    field is read by `fail_fast`, `numeric_solver`, etc.). The
    workbook-side validation gate would still validate it even
    though the workbook itself doesn't read it.

(b) **Type it as `Optional[Dict[str, Any]]` + drop the
    `validate_draft_data` requirement** — acknowledge that the
    workbook doesn't need this field at all. The non-workbook
    consumers continue to validate it via their own contracts (or
    not, if no such contract exists yet).

Spec recommends (b) for Contract 2's narrow scope (workbook
boundary). The debt_schedule contract for non-workbook readers is
its own contract — listed as R8 follow-up.

### 3.7 WorkbookPayloadContract (top-level)

```python
class WorkbookPayloadContract(BaseModel):
    """The 6-field payload at the workbook boundary. Composes
    Contract 1 (FinmoModelInputContract) for model_input_json so
    both gates speak the same shape.
    """
    model_input_json: FinmoModelInputContract  # from Contract 1
    finmo_json: FinmoOutputContract
    payroll_headcount: PayrollHeadcountContract
    debt_schedule: Optional[Dict[str, Any]] = None   # T6 / §3.6 (b)
    planning_run_json: Optional[PlanningRunJsonForWorkbookContract] = None
    run_diagnostics: Optional[RunDiagnosticsContract] = None

    model_config = ConfigDict(extra="forbid")  # 6 fields, fully known
```

### 3.8 ContractViolation reuse

Contract 1 already defined `ContractViolation` at
`post_intake_contracts/finmo_model_input_contract.py`. Contract 2
reuses it — same stage label format (e.g., `"FINMO_BUILD→WORKBOOK"`),
same producer/consumer side semantics.

---

## 4. Cross-field invariants

Implemented as `@model_validator(mode="after")` on
`WorkbookPayloadContract` or on the relevant sub-contract.

### 4.1 If `planning_run_json` is populated, `stage_ramp_contract` MUST be reachable

Mirrors the production behavior of `DraftWorkbookData.stage_ramp_contract`
(data.py:175+ raises RuntimeError when planning_run_json is populated
but canonical path is missing). Contract 2 surfaces this earlier:

```python
@model_validator(mode="after")
def stage_ramp_reachable_when_planning_run_populated(self) -> "WorkbookPayloadContract":
    if self.planning_run_json is not None:
        # If the wrapping payload is non-empty, the canonical path
        # must terminate at a valid StageRampContract.
        ucc = self.planning_run_json.unified_convergence_context
        if ucc is not None and ucc.business_world_contract is not None:
            stage_ramp = ucc.business_world_contract.stage_ramp_contract
            if stage_ramp is None:
                raise ValueError(
                    "stage_ramp_contract missing at canonical path; "
                    "see data.py:185 RuntimeError equivalent"
                )
    return self
```

### 4.2 Periods length matches the standard 21 across `finmo_json.periods` and `finmo_json.quarter_rows`

If `quarter_rows` is present, it must be exactly 21 entries to match
`periods`. Currently both come from the same source (`build_python_finmo_json`
emits them in lockstep) but a downstream mutator could drift them.

```python
@model_validator(mode="after")
def quarter_rows_length_matches_periods(self) -> "FinmoOutputContract":
    if self.quarter_rows is not None and len(self.quarter_rows) != len(self.periods):
        raise ValueError(
            f"quarter_rows length {len(self.quarter_rows)} does not match "
            f"periods length {len(self.periods)}"
        )
    return self
```

### 4.3 `payroll_headcount.rows` has at least one entry per live quarter

The workbook's payroll summary formulas reference per-quarter ranges;
an empty rows list silently renders zeros. Per T3 the workbook's
Per-Quarter Payroll formula iterates 1..20; a contract-level invariant
catches the case where the producer wrote fewer rows than horizon
quarters.

```python
@model_validator(mode="after")
def rows_cover_all_horizon_quarters(self) -> "PayrollHeadcountContract":
    quarters_in_rows = {int(r.quarter_index) for r in self.rows}
    missing = set(range(1, 21)) - quarters_in_rows
    if missing:
        raise ValueError(
            f"payroll_headcount.rows missing entries for quarters: {sorted(missing)}"
        )
    return self
```

### 4.4 If `data.periods` is going to be sourced from `finmo_json.quarter_rows`, each entry MUST have `days_in_quarter`

Without this, the `days_in_quarter or 0` fallback at
finmo_sheet.py:162 silently produces DIV/0 errors. Per the contract
spec, `quarter_rows` rows are typed as Dict[str, Any], so we'll have
to make `quarter_rows` typed more strongly OR add a validator that
walks the rows. Spec recommends the lighter-touch validator (simpler):

```python
@model_validator(mode="after")
def quarter_rows_carry_days_in_quarter(self) -> "FinmoOutputContract":
    if self.quarter_rows is None:
        return self
    for i, row in enumerate(self.quarter_rows):
        if not isinstance(row, dict):
            continue  # shape captured elsewhere
        if i == 0:
            continue  # stub; days_in_quarter is allowed to be absent/0
        if row.get("days_in_quarter") in (None, 0, 0.0):
            raise ValueError(
                f"quarter_rows[{i}].days_in_quarter is missing or zero — "
                "would produce DIV/0 in workbook formulas"
            )
    return self
```

This addresses the v2 inventory B7 F2 residual.

---

## 5. Boundary enforcement

Same producer-side / consumer-side pattern as Contract 1:

- **Producer side:** there is NO single producer of the
  `DraftWorkbookData` bundle. Each JSON field has a different
  writer. Producer-side validation would need 5 separate gates at
  each writer's persistence point. This is out of scope for Contract
  2's narrow workbook-boundary focus. Producer-side gates per field
  are R8/R9 follow-ups.

- **Consumer side:** validate `WorkbookPayloadContract.from_data(data)`
  inside `build_client_financial_model_workbook` BEFORE any sheet
  builder runs. Raises `ContractViolation` with
  `stage="FINMO_BUILD→WORKBOOK"`, `side="consumer"`.
  Emits `WORKBOOK_PAYLOAD_CONTRACT_VALIDATED` / `WORKBOOK_PAYLOAD_CONTRACT_VIOLATION`
  diagnostic event.

The `validate_draft_data` function at data.py:212 is **replaced**
by the consumer-side gate. `validate_draft_data` enforced 4 required
fields with no shape checks; the contract enforces shape + the same
4 (plus the new debt_schedule decision per §3.6).

### Per-call helper

```python
# enforcement.py extension
def validate_workbook_payload_at_boundary(
    data: DraftWorkbookData,
    *,
    side: str = SIDE_CONSUMER,
    stage: str = WORKBOOK_STAGE_LABEL,
    emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> WorkbookPayloadContract:
    """Bundle the 6 dict fields off DraftWorkbookData and validate
    them as WorkbookPayloadContract. Returns the validated contract
    on success; raises ContractViolation on failure with the same
    stage-tag conventions as Contract 1."""
    payload = {
        "model_input_json": data.model_input_json,
        "finmo_json": data.finmo_json,
        "payroll_headcount": data.payroll_headcount,
        "debt_schedule": data.debt_schedule or None,
        "planning_run_json": data.planning_run_json or None,
        "run_diagnostics": data.run_diagnostics,
    }
    try:
        return WorkbookPayloadContract.model_validate(payload)
    except ValidationError as exc:
        # Same field-path / first-error extraction pattern as
        # Contract 1's validate_model_input_at_boundary.
        ...
```

---

## 6. Implementation sequence

After Nick green-lights this spec, implementation follows:

### Commit 1a — Contract file (sub-contracts + top-level)

File: `python/client_intake_and_finmo/post_intake_contracts/workbook_payload_contract.py`

- All sub-contracts per §3
- `WorkbookPayloadContract` top-level
- 4 cross-field invariants per §4
- Module docstring covering boundary purpose + decisions

Expected LOC: 500-700 (mostly docstrings). Single file artifact.

### Commit 1b — Fixtures + sub-contract tests

`tests/_p3_40_contract_2_fixtures.py` + `tests/test_p3_40_contract_2_subcontracts.py`

Tests per sub-contract:
- FinmoOutputContract: valid, missing periods, statement-row count
  mismatch, etc.
- PayrollHeadcountContract: valid, missing title/person, missing
  oews_title, missing wage_source, horizon coverage invariant
- PlanningRunJsonForWorkbookContract: valid, missing stage_ramp,
  empty quarter_ramp_grid
- RunDiagnosticsContract: valid, optional fields absent, realism
  checks pass-through

Target: 40-50 tests.

### Commit 1c — Top-level + cross-field tests

`tests/test_p3_40_contract_2_workbook_payload.py`

- WorkbookPayloadContract valid round-trip with Contract 1 composed
- stage_ramp_reachable_when_planning_run_populated invariant
- quarter_rows_length_matches_periods invariant
- payroll_headcount horizon coverage invariant
- quarter_rows_carry_days_in_quarter invariant (catches B7 F2)

Target: 20-25 tests.

### Commit 2 — Adapter on `DraftWorkbookData`

Add `DraftWorkbookData.to_contract()` and `from_contract(contract)`
classmethod for round-trip and test fixtures. Mirrors Contract 1
Commit 2 pattern.

### Commit 3 — Consumer-side enforcement at `build_client_financial_model_workbook`

Replace `validate_draft_data(data)` call with
`validate_workbook_payload_at_boundary(data, ...)`. Old
`validate_draft_data` function stays in place (deprecated) for
backward-compat with any external callers; deletion in a follow-up.

New PhaseCode: `WORKBOOK_PAYLOAD_CONTRACT`.
New EventCodes: `WORKBOOK_PAYLOAD_CONTRACT_VALIDATED`,
`WORKBOOK_PAYLOAD_CONTRACT_VIOLATION`.
New FailFastCode: `FAIL_WORKBOOK_PAYLOAD_CONTRACT_VIOLATION`.

Note: per Contract 1's lesson, adding new phase/event/fail-fast
codes touches several lock-count tests
(test_phase_9_p3_33_phase3_step9a_phase_codes.py etc.). Update
those in lockstep.

### Commit 4 (optional) — Migrate `data.py` defensive patterns to typed access

Capture the validated contract in the workbook builder. Remove the
most-egregious defensive patterns in `DraftWorkbookData` properties
where the contract guarantees the value:

- `periods` 3-path fallback → single canonical read
- `business_name` 3-path fallback → single canonical read
- `draft_id` 2-path fallback → single canonical read

Conservative scope. The deeper helper migrations (replacing every
`row_by_label(...)` defensive pattern) are R-residuals.

---

## 7. Open flags for Nick's review

5 decisions needed before code lands:

### Flag 1 — debt_schedule resolution

`data.debt_schedule` is required by `validate_draft_data` but
**verified-unread** at the workbook boundary. Two options per §3.6:

(a) Keep required, type as DebtScheduleContract (real validation,
    same shape as other Contract 2 sub-contracts).

(b) **(Recommended)** Make Optional + remove the
    `validate_draft_data` requirement. The field is still persisted
    on the draft row for non-workbook consumers; their validation
    is out of Contract 2's scope (R8 follow-up).

### Flag 2 — `extra="ignore"` vs `extra="forbid"`

Contract 1 used `extra="forbid"` everywhere. Contract 2's
producers add many fields the workbook doesn't read (the T5/T6/T7/T8
"NOT READ by workbook" lists). Three approaches:

(a) `extra="forbid"` everywhere → contract enumerates every writer
    field down to opaque diagnostic blobs (high maintenance).

(b) `extra="ignore"` everywhere → contract validates only what the
    workbook reads (low maintenance, but a new writer field of the
    same name as an existing one would not surface as a violation).

(c) **(Recommended)** Mixed: `extra="forbid"` on the top-level
    `WorkbookPayloadContract` (we know the 6 fields exhaustively)
    and on nested entries the workbook walks deterministically (e.g.,
    `FinmoStatementRow`, `PayrollHeadcountRow`); `extra="ignore"`
    on the sub-contract envelopes where producers add many writer-
    specific keys.

### Flag 3 — `quarter_rows_carry_days_in_quarter` invariant

§4.4 proposes a contract-level validator that requires every
non-stub `quarter_rows` entry to carry `days_in_quarter > 0`. This
addresses B7 F2 residual. But it changes behavior: today the
fallback silently produces DIV/0 errors; with this invariant, the
workbook would refuse to render any payload that omits
`days_in_quarter` from quarter_rows. Confirm:

(a) Yes, add the invariant — fail-loud on a real upstream bug that
    currently silently produces wrong Excel output.

(b) No, leave as v2 residual — handle separately if/when the
    workbook reader is migrated to fail-loud on missing
    days_in_quarter.

Spec recommends (a) per Contract 1's "structural rigor over silent
failure" principle.

### Flag 4 — `payroll_headcount` horizon-coverage invariant

§4.3 proposes that `payroll_headcount.rows` must have at least one
entry per quarter 1..20. Producer's existing validators ensure this
in normal runs. Confirm:

(a) Yes, encode in contract — catches drift.

(b) No, trust producer-side validation.

Spec recommends (a).

### Flag 5 — Producer-side gates per JSON field

Contract 2's consumer-side gate validates the 6 fields together at
the workbook entry. But each field has a different producer
(orchestrator for model_input_json + finmo_json + planning_run_json;
post_intake_headcount for payroll_headcount;
post_intake_debt_schedule for debt_schedule;
post_intake_run_diagnostics for run_diagnostics). Producer-side
gates would land at each writer's persistence call.

(a) Skip producer-side gates for Contract 2 (consumer-side only).
    The 5 producers vary too much to gate uniformly here.
    Per-producer contracts are future R-residuals.

(b) Add producer-side gates per JSON field as a separate
    Contract 2b series.

Spec recommends (a). Producer-side gates per field are R8/R9
follow-ups.

---

## 8. Known residual cleanups (out of scope for Contract 2)

- **R8.** Producer-side validation gates for each of the 5 JSON
  fields (model_input_json, finmo_json, payroll_headcount,
  debt_schedule, planning_run_json, run_diagnostics) at their
  respective writer call sites. Each has different producer
  characteristics (single writer vs many, idempotent vs additive,
  etc.); each needs its own commit.

- **R9.** `validate_draft_data` deletion. Once Contract 2 lands,
  the old function is dead. Delete in a follow-up commit (split
  from Contract 2's commit 3 so the deletion is reviewable
  independently from the gate-wiring).

- **R10.** `WorkbookBuildContext.{finmo_rows, schedule_rows,
  source_rows, model_input_rows}` registry: typed contract for
  the registry shape so the checks-sheet silent-skip residual
  (B7 F4) can be addressed. Out of scope here.

- **R11.** Deep migration of `data.py` defensive patterns to typed
  contract attribute access (Contract 2 Commit 4 above does the
  top-level; helpers like `row_by_label`, the per-row `.get`
  patterns, etc. are R11).

- **R12.** Reconcile `debt_schedule` writer shape vs current
  workbook-blind requirement (per Flag 1). If Flag 1 (b) is
  picked, `debt_schedule` becomes a non-workbook artifact
  needing its own typed contract elsewhere.

---

## 9. Workflow

Same as Contract 1: doc-only commit first, hold for Nick review.
After approval, the 5 implementation commits follow per §6 with
push + email per commit.

If during Commit 1a (the contract file itself) I find anything
else that diverges from production, I'll flag back the same way
I did the Contract 1 first-round trace work — no silent
adjustment.
