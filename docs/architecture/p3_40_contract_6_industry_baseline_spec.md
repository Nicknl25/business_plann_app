# P3.40 Contract 6 — IndustryBaselineResolvedContract (Spec)

**Status:** Specification only. No code lands until Nick reviews this doc.
After review, implementation follows the commit sequence in §6 below.

**Boundary covered:** POST_INTAKE_INPUT → INDUSTRY_BASELINE
(Boundary 2 in
[p3_40_pipeline_data_flow_inventory_v2.md](p3_40_pipeline_data_flow_inventory_v2.md)).
First MULTI-SHAPE boundary in the P3.40 series — 4 distinct
payload shapes spanning a NAICS cascade resolver, cohort SQL
persistence, an in-memory view, and a population summary.

**Predecessors:**
- [Contract 5 — IntakeDraftContract](p3_40_contract_5_intake_draft_spec.md)
  (landed at 2f2d46f → end-to-end at 20c6159). Contract 6 takes
  a 4-field `business_profile` EXTRACTED from Contract 5 intake
  fields; does NOT compose Contract 5 (per F1).
- Contracts 1-4 are downstream and don't compose Contract 6.

**Companion trace doc:** [p3_40_contract_6_industry_baseline_trace.md](p3_40_contract_6_industry_baseline_trace.md)
(landed at a03e098, 882 LOC, 18 flags surfaced). All file:line
citations and divergence findings below trace back to that doc.

**Lessons applied from Contracts 1-5:**
- Trace before spec. The trace surfaced 4 distinct shapes
  (multi-shape boundary), 3 NEW STRUCTURAL drifts from v1, and
  11 CONFIRMED RESIDUAL flags — all would have been costly
  assumption errors otherwise.
- Match production vocabulary verbatim. 13 cascade fields + 17
  cohort SQL cols + 11 in-memory band fields + 6 trust_flag
  values + 4 confidence_tier values + 6 NAICS levels lifted
  from source.
- Constraints from production reality. `float` for benchmarks
  (decimal-coerced); `Optional[float]` for `robust_min`/`max`
  per cohort-only writes.
- Don't loosen safety checks. F10 (FAIL_COHORT_BANDS precondition)
  + F11 (NAICS length) tighten defensively.
- `extra="forbid"` only on top-level; `extra="ignore"` on
  sub-contracts.
- Compose only where a real shape relationship exists. F1: NO
  composition with Contract 5 per trace T4 — confirmed by
  source.
- Adjustment B is recurring. F17 re-uses Contracts 3-5 pattern.
- Diagnostic-emission invariant matters. F16.
- Multi-shape contracts get multi-shape sub-contracts inside a
  single module (F0). Don't fragment across modules; do type
  each shape distinctly.
- Surface silent-drop asymmetries as contract-level facts (F5,
  F7) rather than papering over them. The fix is R-residual; the
  contract documents the current state honestly.
- Per-shape consumer gates (F15) instead of one mega-gate. Each
  consumer entry gets its own validate call.

---

## 1. Trace Task Findings

The 8 pre-implementation traces (T1-T8) produced findings folded
directly into this spec's structure. The full enumeration is in
the trace doc; this section consolidates the ones that change
contract design.

### 1.1 Multi-shape boundary surface (trace headline #1)

Per trace T1: this boundary spans **4 distinct payload shapes**:

| Shape | Source | Producer | Consumer |
|---|---|---|---|
| A — `CascadeResolverPayloadContract` | NAICS cascade resolver per metric | `_payload_from_row` at [lookup.py:237-256](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L237) | `_attach_seed_provenance` (finmo_bridge.py:339); `driver_movement_assembler._resolve_naics_band` (driver_movement_assembler.py:97) |
| B — `CohortSqlRowContract` | Cohort populator SQL row | `populate_cohort_bands_for_run` INSERT at [cohort_bands_table.py:209-244](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L209) | persisted to `post_intake_cohort_bands` table; in-memory consumers go through Shape C |
| C — `GetBandsViewContract` | In-memory nested view of SQL rows | `get_bands` at [cohort_bands_table.py:344-392](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L344) | every amalgamated tool's `_echo_*_bands` helper + `mirror.build_mirror` (mirror.py:140-160) + `evaluate_plan._margin_distance_from_bands` (evaluate_plan.py:189-220) |
| D — `PopulationSummaryContract` | `populate_cohort_bands_for_run` return value | same function — return at [cohort_bands_table.py:255-262](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L255) | logged into `sequence_trace["cohort_bands_populated"]` at runner.py:582 (no structural downstream) |

Per F0 (a): SINGLE Contract 6 module with 4 typed sub-contracts
inside. Don't fragment across modules; do type each shape
distinctly.

### 1.2 ZERO composition with Contract 5 (trace T4)

Per trace T4.1: Contract 6 takes a 4-field `business_profile`
EXTRACTED from Contract 5's `operating_model_json` +
`financials_year1_json`, not wrapping the intake. Stands alone.

### 1.3 NEW STRUCTURAL findings vs v1 inventory

Per trace §T8:
- **Div-1**: cascade resolver has 13 fields (v1 listed 10 — missed
  `source_year`, `sample_size`, `raw_confidence_tier`).
- **Div-2**: v1's get_bands shape enumeration partial; trace finds
  11 fields per band.
- **Div-3**: `get_bands` drops 6 SQL columns silently
  (`naics_prefix_used`, `data_source` are the substantive drops;
  3 PK fields are hoisted to top-level; `resolved_at` is dropped).

Per F7 (a): Shape B (`CohortSqlRowContract`, 17 cols) and Shape C
(`GetBandsViewContract`, 11 fields per band) ship as SEPARATE
sub-contracts so the silent-drop asymmetry surfaces at type level
rather than at a runtime data bug.

### 1.4 16 trace divergences (folded into Flag dispositions)

All 16 Div items from trace §T8 fold into the F0-F18 flag set
below. See §7.

---

## 2. Top-level production payload — 4-shape roster

### 2.1 Shape A — `CascadeResolverPayloadContract` (13 fields)

Per trace T1.3 (verbatim from lookup.py:237-256):

| # | Field | Type | Required? | Tier |
|---|---|---|---|---|
| 1 | `metric_key` | `str` | required | A |
| 2 | `benchmark_min` | `Optional[float]` | required (None possible if SQL NULL) | A |
| 3 | `benchmark_target` | `Optional[float]` | required | A |
| 4 | `benchmark_max` | `Optional[float]` | required | A |
| 5 | `naics_code_used` | `str` | required | A |
| 6 | `naics_level_used` | `Literal[0, 2, 3, 4, 5, 6]` | required (F13) | A |
| 7 | `data_source` | `str` | required | A |
| 8 | `source_year` | `Optional[int]` | Optional (None when SQL NULL) | A |
| 9 | `sample_size` | `Optional[int]` | Optional | A |
| 10 | `confidence_tier` | `Literal["high", "medium", "low", "generic_default"]` | required (F8) | A |
| 11 | `raw_confidence_tier` | `str` | required | A |
| 12 | `trust_flag` | `Literal["naics_6_direct", "naics_5_fallback", "naics_4_fallback", "naics_3_fallback", "naics_2_fallback", "no_coverage"]` | required (F13) | A |
| 13 | `fallback_chain_attempted` | `List[str]` | Optional (diagnostic-only per F4) | C diagnostic |

**13 fields total**, matching `_payload_from_row` at
[lookup.py:240-256](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L240)
verbatim. `cohort_query` is intentionally NOT on Shape A per the
amended F5 disposition (see §7) — it's an internal field on the
cohort-side `CohortBandResult` dataclass, never reaches any of
the 4 boundary shapes.

### 2.2 Shape B — `CohortSqlRowContract` (17 cols + auto-stamp)

Per trace T2.2 (verbatim from cohort_bands_table.py SQL schema):

| # | Field | Type | Required? |
|---|---|---|---|
| 1 | `draft_id` | `str = Field(min_length=1, max_length=64)` | required (PK) |
| 2 | `planning_run_id` | `str = Field(min_length=1, max_length=64)` | required (PK) |
| 3 | `section` | `Literal["drivers", "balance_sheet", "stage_ramp", "capex_rd", "payroll"]` | required (PK; F3) |
| 4 | `lever_id` | `str = Field(min_length=1, max_length=128)` | required (PK) |
| 5 | `metric_key` | `str = Field(min_length=1, max_length=128)` | required (PK) |
| 6 | `metric_column` | `Optional[str]` | Optional |
| 7 | `benchmark_min` | `Optional[float]` | Optional |
| 8 | `benchmark_target` | `Optional[float]` | Optional |
| 9 | `benchmark_max` | `Optional[float]` | Optional |
| 10 | `robust_min` | `Optional[float]` | Optional (cohort-only per F9) |
| 11 | `robust_max` | `Optional[float]` | Optional |
| 12 | `naics_level_used` | `Optional[Literal[0, 2, 3, 4, 5, 6]]` | Optional |
| 13 | `naics_prefix_used` | `Optional[str]` | Optional |
| 14 | `cohort_size` | `Optional[int]` | Optional |
| 15 | `firm_count` | `Optional[int]` | Optional |
| 16 | `confidence_tier` | `Optional[Literal["high", "medium", "low", "generic_default"]]` | Optional |
| 17 | `cohort_table` | `Optional[Literal["edgar", "alpha"]]` | Optional |
| 18 | `data_source` | `Optional[str]` | Optional |
| 19 | `resolved_at` | `Optional[datetime]` | Optional (auto server-stamped; round-trip-only) |

Per amended F5 (α — see §7): `cohort_query` is NOT on Shape B
AND is NOT on Shape A. It exists only on the cohort-side
`CohortBandResult` intermediate dataclass at
[cohort_band_resolver.py:163](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L163);
the SQL INSERT silently drops it at materialization. The contract
documents the asymmetry as an R10 R-residual upstream-producer
fix; cohort_query crosses no boundary surface today and is
intentionally excluded from all 4 typed shapes.

### 2.3 Shape C — `GetBandsViewContract` (envelope + nested bands)

Per trace T1.5:

```python
class GetBandsViewContract(BaseModel):
  section: Literal["drivers", "balance_sheet", "stage_ramp", "capex_rd", "payroll"]
  draft_id: str = Field(min_length=1)
  planning_run_id: str = Field(min_length=1)
  count: int = Field(ge=0)
  bands: Dict[str, GetBandsViewBandContract]  # keyed by lever_id

class GetBandsViewBandContract(BaseModel):
  metric_key: Optional[str] = None
  metric_column: Optional[str] = None
  benchmark_min: Optional[float] = None
  benchmark_target: Optional[float] = None
  benchmark_max: Optional[float] = None
  robust_min: Optional[float] = None
  robust_max: Optional[float] = None
  confidence_tier: Optional[Literal["high", "medium", "low", "generic_default"]] = None
  cohort_size: Optional[int] = None
  firm_count: Optional[int] = None
  naics_level_used: Optional[Literal[0, 2, 3, 4, 5, 6]] = None
  cohort_table: Optional[Literal["edgar", "alpha"]] = None
```

11 fields per band — `naics_prefix_used` + `data_source` dropped
per the silent-drop asymmetry (F7); 3 PK fields hoisted to
top-level; `resolved_at` dropped.

### 2.4 Shape D — `PopulationSummaryContract`

```python
class PopulationSummaryContract(BaseModel):
  drivers: Optional[PopulationSummarySectionContract] = None
  balance_sheet: Optional[PopulationSummarySectionContract] = None
  stage_ramp: Optional[PopulationSummarySectionContract] = None
  capex_rd: Optional[PopulationSummarySectionContract] = None  # F3
  payroll: Optional[PopulationSummarySectionContract] = None   # F3

class PopulationSummarySectionContract(BaseModel):
  resolved: int = Field(ge=0)
  skipped: int = Field(ge=0)
```

5 named sections per F3 (a). All Optional because populator may
skip sections; cross-field invariant (F10) requires total
resolved ≥ 1.

### 2.5 Top-level `IndustryBaselineResolvedContract`

Per F0 (a):

```python
class IndustryBaselineResolvedContract(BaseModel):
  """Top-level wrapper for the 4-shape industry-baseline
  boundary. Each shape is independently typed and validated;
  this top-level exists for one-stop import + diagnostic-emission
  attribution.

  In production, the 4 shapes are validated INDEPENDENTLY at
  their respective producer/consumer sites (per F15); this
  top-level is the SINGLE shape that would be used if a future
  end-to-end orchestration test wants to validate a complete
  baseline-resolution outcome (typical case: tests that round-trip
  the populator + cascade together).
  """

  cascade_payloads: Dict[str, CascadeResolverPayloadContract] = Field(default_factory=dict)  # keyed by metric_key
  cohort_rows: List[CohortSqlRowContract] = Field(default_factory=list)
  get_bands_views: Dict[str, GetBandsViewContract] = Field(default_factory=dict)  # keyed by section
  population_summary: Optional[PopulationSummaryContract] = None
  business_profile: BusinessProfileInputContract

  model_config = ConfigDict(extra="forbid")  # F18
```

### 2.6 `BusinessProfileInputContract` — Boundary INPUT shape

Per trace T1.2 (the 4-field input dict at runner.py:573-579):

```python
class BusinessProfileInputContract(BaseModel):
  naics_6: Optional[str] = Field(default=None, pattern=r"^[0-9]{6}$")  # F11
  target_annual_revenue: Optional[float] = None
  stage: Optional[str] = None
  business_model: Literal[None] = None  # F2 (a) -- always None per production

  model_config = ConfigDict(extra="ignore")
```

`business_model` pinned to `Literal[None]` per F2 (a) — matches
trace finding that production always writes `None` at
runner.py:577. A future code change setting `business_model = "saas"`
surfaces as ContractViolation, forcing contract update alongside
code.

---

## 3. Field-by-field contract spec

### 3.1 4 sub-contracts (per §2.1-2.4)

Already enumerated in §2. Spec module exports:

```python
__all__ = [
  "INDUSTRY_BASELINE_STAGE_LABEL",
  "IndustryBaselineResolvedContract",
  "BusinessProfileInputContract",
  "CascadeResolverPayloadContract",
  "CohortSqlRowContract",
  "GetBandsViewContract",
  "GetBandsViewBandContract",
  "PopulationSummaryContract",
  "PopulationSummarySectionContract",
  "ContractViolation",  # re-export
]
```

### 3.2 ZERO re-imports from Contract 5

Per F1 (a) — confirmed by trace T4. Only `ContractViolation`
re-exported (via finmo_model_input_contract).

### 3.3 Constants

```python
INDUSTRY_BASELINE_STAGE_LABEL = "POST_INTAKE_INPUT->INDUSTRY_BASELINE"

# Supported NAICS resolution levels per cascade walk
# (per trace T5.3 -- 6/5/4/3/2/0 is non-contiguous; no level 1).
SUPPORTED_NAICS_LEVELS = (6, 5, 4, 3, 2, 0)

# Confidence tier vocabulary -- shared across cascade and cohort
# (per trace T5.4 / F8 / v1 §E "same vocabulary, different
# meaning"). The contract pins the vocabulary; producer-side
# semantics are out of scope.
SUPPORTED_CONFIDENCE_TIERS = ("high", "medium", "low", "generic_default")

# Trust flag values per cascade walk (per F13 / trace T5.2).
SUPPORTED_TRUST_FLAGS = (
  "naics_6_direct",
  "naics_5_fallback",
  "naics_4_fallback",
  "naics_3_fallback",
  "naics_2_fallback",
  "no_coverage",
)

# Cohort section names per F3 / _SECTION_LEVERS in
# cohort_bands_table.py. capex_rd and payroll are
# defined-but-not-yet-populated per v1 §D-2; the contract permits
# both as valid section names so future populator extensions
# don't require contract amendment.
SUPPORTED_SECTIONS = (
  "drivers",
  "balance_sheet",
  "stage_ramp",
  "capex_rd",
  "payroll",
)
```

---

## 4. Cross-field invariants

### 4.1 F10 — Population summary requires ≥1 resolved band total

```python
class PopulationSummaryContract(BaseModel):
  ...
  @model_validator(mode="after")
  def at_least_one_section_has_resolved_bands(self) -> "PopulationSummaryContract":
    """Per F10 + v1 inventory section F-2 known precondition.
    FAIL_COHORT_BANDS_MISSING is the runtime fail-fast inside the
    populator at cohort_bands_table.py:265 -- currently swallowed
    by the soft try/except at runner.py:556-583. The contract
    encodes the precondition: a successful population result must
    have resolved at least 1 band across all sections combined.
    Zero-resolved populations were previously silent skips;
    contract-level enforcement surfaces them as ContractViolation."""
    total_resolved = sum(
      section.resolved
      for section in (
        self.drivers, self.balance_sheet, self.stage_ramp,
        self.capex_rd, self.payroll,
      )
      if section is not None
    )
    if total_resolved == 0:
      raise ValueError(
        "population_summary has zero resolved bands across all 5 sections "
        "(FAIL_COHORT_BANDS_MISSING precondition); at least 1 resolved "
        "band is required for downstream mirror_build to succeed"
      )
    return self
```

### 4.2 F12 — Benchmark monotonicity on Shape B + Shape C bands

```python
class CohortSqlRowContract(BaseModel):
  ...
  @model_validator(mode="after")
  def benchmark_monotonicity(self) -> "CohortSqlRowContract":
    """Per F12 + v1 inventory section F-5. Cohort percentile
    interpolation guarantees monotonicity today, but no defensive
    assertion existed. The contract enforces
    benchmark_min <= benchmark_target <= benchmark_max when all
    3 are non-None.

    Skipped when any of the 3 is None (Optional per the SQL
    NULL columns -- partial population is a valid state per
    F9 / v1 inventory).
    """
    if (
      self.benchmark_min is not None
      and self.benchmark_target is not None
      and self.benchmark_max is not None
    ):
      if not (self.benchmark_min <= self.benchmark_target <= self.benchmark_max):
        raise ValueError(
          f"benchmark monotonicity violated: min={self.benchmark_min!r} "
          f"target={self.benchmark_target!r} max={self.benchmark_max!r}; "
          f"required min <= target <= max"
        )
    return self


class GetBandsViewBandContract(BaseModel):
  ...
  @model_validator(mode="after")
  def benchmark_monotonicity(self) -> "GetBandsViewBandContract":
    """Same invariant as CohortSqlRowContract -- the in-memory
    view is derived from the SQL row, so monotonicity carries
    through. Re-checked here so a future direct-instantiation
    path that bypasses Shape B can't silently produce
    non-monotonic bands."""
    if (
      self.benchmark_min is not None
      and self.benchmark_target is not None
      and self.benchmark_max is not None
    ):
      if not (self.benchmark_min <= self.benchmark_target <= self.benchmark_max):
        raise ValueError(
          f"GetBandsViewBand benchmark monotonicity violated: "
          f"min={self.benchmark_min!r} target={self.benchmark_target!r} "
          f"max={self.benchmark_max!r}"
        )
    return self
```

### 4.3 Other invariant candidates DEFERRED

- **`get_bands_views[section].count == len(bands)`** — the
  envelope `count` field MUST equal the length of the `bands`
  dict. Cheap; surfaces population miscounts. Deferred to R-residual
  cleanup; the producer (`get_bands`) computes both from the same
  source so drift is unlikely today.
- **`cascade_payloads[metric_key].metric_key == metric_key`** —
  the dict key must equal the inner field value. Same deferral
  reasoning.

Both candidates ship as R-residual cleanups (R8 below) — not
blocking Commit 1a.

---

## 5. Boundary enforcement

### 5.1 Producer-side gate (F14 — split disposition)

**SHIP cohort producer-side gate (Shape D + Shape B precondition).**
Located immediately after `populate_cohort_bands_for_run` returns
at [runner.py:580](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L580):

```python
# runner.py:580+ (after _bands_summary = populate_cohort_bands_for_run(...))
from client_intake_and_finmo.post_intake_contracts.enforcement import (
  SIDE_PRODUCER as _IBR_SIDE_PRODUCER,
  validate_industry_baseline_population_summary_at_boundary,
)
validate_industry_baseline_population_summary_at_boundary(
  _bands_summary, side=_IBR_SIDE_PRODUCER,
)
```

This validates Shape D (population summary) including the F10
≥1-resolved-band invariant. Catches FAIL_COHORT_BANDS_MISSING
regressions that today are swallowed by the soft try/except.

**SKIP cascade producer-side gate.** The cascade resolver
`_payload_from_row` is invoked from multiple consumer-side
call sites (`_attach_seed_provenance`, `_resolve_naics_band`);
producer-side gates would need to land inside the resolver
itself OR at each public caller (Contract 2 R8 pattern).
Consumer-side gates per F15 cover this surface.

### 5.2 Consumer-side gates (F15 — per-shape placement)

**4 distinct consumer-side gate sites:**

#### 5.2.1 Shape A consumer gate #1 — `_attach_seed_provenance`

```python
# finmo_bridge.py:339+ (entry of _attach_seed_provenance)
def _attach_seed_provenance(row: Dict[str, Any], payload: Dict[str, Any]) -> None:
  # P3.40 Contract 6 Commit 3 -- Shape A consumer-side gate.
  # Validates the cascade resolver payload before stamping
  # model_input row.seed_provenance_json. Skipped when payload
  # has no trust_flag (no-op early return below).
  if not isinstance(payload, dict) or not payload.get("trust_flag"):
    return
  from client_intake_and_finmo.post_intake_contracts.enforcement import (
    SIDE_CONSUMER as _IBR_SIDE_CONSUMER,
    validate_industry_baseline_cascade_payload_at_boundary,
  )
  validate_industry_baseline_cascade_payload_at_boundary(
    payload, side=_IBR_SIDE_CONSUMER,
  )
  # (existing body continues)
```

#### 5.2.2 Shape A consumer gate #2 — `_resolve_naics_band`

```python
# driver_movement_assembler.py:97+
def _resolve_naics_band(...) -> ...:
  # ... cascade lookup returns `payload`
  from client_intake_and_finmo.post_intake_contracts.enforcement import (
    SIDE_CONSUMER as _IBR_SIDE_CONSUMER,
    validate_industry_baseline_cascade_payload_at_boundary,
  )
  validate_industry_baseline_cascade_payload_at_boundary(
    payload, side=_IBR_SIDE_CONSUMER,
  )
  # (existing body continues)
```

#### 5.2.3 Shape C consumer gate — `get_bands` return

```python
# cohort_bands_table.py:344+ (immediately before return)
def get_bands(conn, *, draft_id, planning_run_id, section) -> Dict[str, Any]:
  # ... build `bands` + envelope dict
  result = {
    "section": section,
    ...
    "bands": bands,
  }
  # P3.40 Contract 6 Commit 3 -- Shape C consumer-side gate.
  # Validates the in-memory get_bands view before handing to
  # amalgamated tools / mirror.build_mirror /
  # evaluate_plan._margin_distance_from_bands.
  from client_intake_and_finmo.post_intake_contracts.enforcement import (
    SIDE_CONSUMER as _IBR_SIDE_CONSUMER,
    validate_industry_baseline_get_bands_view_at_boundary,
  )
  validate_industry_baseline_get_bands_view_at_boundary(
    result, side=_IBR_SIDE_CONSUMER,
  )
  return result
```

#### 5.2.4 Shape B per-row validation — DEFERRED to R-residual

Shape B's SQL row shape is enforced upstream at producer-side
through the CohortBandResult dataclass + INSERT column list. No
in-process consumer reads SQL rows directly (consumers go
through Shape C via `get_bands`). Per-row Shape B contract
validation INSIDE the populator loop is cheap but redundant
with the producer-side dataclass. Deferred to R-residual cleanup.

### 5.3 Enforcement helpers

Per F15 the spec ships **4 distinct enforcement helpers** (one
per shape) for clarity:

```python
# enforcement.py additions
INDUSTRY_BASELINE_STAGE_LABEL = "POST_INTAKE_INPUT->INDUSTRY_BASELINE"

def validate_industry_baseline_cascade_payload_at_boundary(
  payload: Dict[str, Any], *, side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> CascadeResolverPayloadContract:
  """Shape A validation. Wraps CascadeResolverPayloadContract.model_validate."""
  ...

def validate_industry_baseline_cohort_sql_row_at_boundary(
  payload: Dict[str, Any], *, side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> CohortSqlRowContract:
  """Shape B validation. Wraps CohortSqlRowContract.model_validate."""
  ...

def validate_industry_baseline_get_bands_view_at_boundary(
  payload: Dict[str, Any], *, side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> GetBandsViewContract:
  """Shape C validation. Wraps GetBandsViewContract.model_validate."""
  ...

def validate_industry_baseline_population_summary_at_boundary(
  payload: Dict[str, Any], *, side: str,
  stage: str = INDUSTRY_BASELINE_STAGE_LABEL,
  emit_diagnostic_fn: Optional[Callable[..., Any]] = None,
) -> PopulationSummaryContract:
  """Shape D validation. Wraps PopulationSummaryContract.model_validate
  (includes the F10 at-least-one-resolved invariant)."""
  ...
```

All 4 helpers share the same `INDUSTRY_BASELINE_STAGE_LABEL` and
emit under the same `PhaseCode.INDUSTRY_BASELINE_CONTRACT` per
F16 (one boundary, one phase). `diagnostic_data` includes a
`"shape"` field distinguishing A/B/C/D for queryability.

### 5.4 Adjustment B verification (F17 — confirmed)

Same intake_consult.py:7377 generic `except Exception as exc:`
catch handles ContractViolation per Contracts 3-5 pattern. All
4 gates (producer + 3 consumer) raise ContractViolation that
propagates through the `prepare_initial_grid_for_draft` →
`_run_planning_system_for_draft_unified` →
`_run_planning_system_for_draft` chain into the line-7377
generic catch as structured 500 with `detail=str(exc)`.

### 5.5 PhaseCode / EventCode / FailFastCode additions (F16)

**One PhaseCode for Contract 6** (one boundary, one phase per
F16 recommendation):

- `PhaseCode.INDUSTRY_BASELINE_CONTRACT`
- `EventCode.INDUSTRY_BASELINE_CONTRACT_VALIDATED`
- `EventCode.INDUSTRY_BASELINE_CONTRACT_VIOLATION`
- `FailFastCode.FAIL_INDUSTRY_BASELINE_CONTRACT_VIOLATION = "fail_industry_baseline_contract_violation"`

Lockstep test updates:
- `test_phase_9_p3_33_phase3_step9a_phase_codes.py`: rename
  `test_phase_code_has_eighteen_phases` → `_nineteen_phases`;
  count 18 → 19; comment lists all 6 contract phases.

### 5.6 Diagnostic-emission invariant test (F16)

- `ContractSixEmitsIndustryBaselinePhaseCodeTest` (1 new test
  in `tests/test_p3_40_diagnostic_emission_invariant.py`): feed
  deliberate Contract 6 violation through any of the 4 helpers
  with capturing emitter; assert captured event carries
  `PhaseCode.INDUSTRY_BASELINE_CONTRACT`.
- `PhaseCodesDoNotCrossContaminateTest` extension: 1 new test
  confirming Contract 6 violations route to
  `INDUSTRY_BASELINE_CONTRACT` exclusively, NOT under
  `MODEL_INPUT` / `WORKBOOK_PAYLOAD` / `SOLVER_INPUT` /
  `SOLVER_OUTPUT` / `INTAKE_DRAFT` phase codes.

Invariant-file count: 9 → 11.

---

## 6. Implementation sequence

After Nick green-lights this spec, implementation follows.

### Commit 1a — Contract module

File: `python/client_intake_and_finmo/post_intake_contracts/industry_baseline_resolved_contract.py`

- 6 sub-contracts per §2 + §3:
  - `BusinessProfileInputContract` (4 fields, F2 + F11 baked in)
  - `CascadeResolverPayloadContract` (13 fields, F8 + F13 Literals baked in; F5-α DROP cohort_query)
  - `CohortSqlRowContract` (17 cols + resolved_at, F12 invariant)
  - `GetBandsViewBandContract` (11 fields, F12 invariant)
  - `GetBandsViewContract` (envelope + nested bands)
  - `PopulationSummarySectionContract` + `PopulationSummaryContract` (5 sections, F10 invariant)
- 1 top-level: `IndustryBaselineResolvedContract` (per F0 (a) wrapper)
- 4 module constants (`INDUSTRY_BASELINE_STAGE_LABEL`,
  `SUPPORTED_NAICS_LEVELS`, `SUPPORTED_CONFIDENCE_TIERS`,
  `SUPPORTED_TRUST_FLAGS`, `SUPPORTED_SECTIONS`)
- 2 cross-field invariants per §4 (F10 + F12 × 2 = 3 validators)
- `extra="forbid"` top-level (F18); `extra="ignore"` on all
  sub-contracts
- ZERO re-imports from prior contracts (F1)
- Module docstring covers:
  - 4-shape boundary surface rationale (F0)
  - F5 + F7 silent-drop asymmetry documentation
  - 18 R-residuals (R8-R25)

Expected LOC: 600-800 — largest contract module yet. Likely
to push or exceed the 700-LOC cap; spec accepts this per prior
1a precedent (Contract 1 1a at 749 LOC, Contract 2 1b at 847
LOC both shipped single-artifact with notes).

### Commit 1b — Fixtures + sub-contract tests

`tests/_p3_40_contract_6_fixtures.py` +
`tests/test_p3_40_contract_6_subcontracts.py`

Fixtures:
- `valid_business_profile_dict()` — 4 fields
- `valid_cascade_resolver_payload_dict(metric_key=...)` — 13 fields (F5-α: no cohort_query)
- `valid_cohort_sql_row_dict(section=..., lever_id=..., metric_key=...)` — 18 cols + auto-stamp
- `valid_get_bands_view_band_dict(metric_key=...)` — 11 fields
- `valid_get_bands_view_dict(section=...)` — envelope + N bands
- `valid_population_summary_section_dict(resolved=5, skipped=0)`
- `valid_population_summary_dict()` — 5 sections (or subset)
- `valid_industry_baseline_resolved_dict()` — top-level wrapper

Test classes (6-8 per spec target):
- `BusinessProfileInputContractTest` (~4): F11 NAICS-6 pattern
  validation (valid 6-digit accepted; 5-digit rejected;
  alpha-contaminated rejected; None accepted); F2 business_model
  Literal[None] (None accepted; string rejected).
- `CascadeResolverPayloadContractTest` (~5): valid 13-field
  payload; missing required fields; F8 confidence_tier Literal
  (4 accepted + typo rejected); F13 trust_flag Literal (6
  accepted + typo rejected); F13 naics_level_used Literal
  (6 accepted: 6/5/4/3/2/0; level-1 rejected). F5-α: no
  cohort_query test needed (field never present in the
  contract; extra="ignore" silently drops it if a future
  caller adds it speculatively).
- `CohortSqlRowContractTest` (~7): valid 18-field row; missing
  PK fields; F3 section Literal (5 accepted + invalid rejected);
  cohort_table Literal (edgar/alpha accepted + invalid rejected);
  F12 benchmark monotonicity (min<target<max accepted;
  min>target rejected); F9 robust_min/max Optional absent.
  F5-α: cohort_query intentionally not declared on this contract;
  extra='ignore' would silently drop it if a future caller
  added it speculatively.
- `GetBandsViewBandContractTest` (~4): valid 11-field band;
  F12 benchmark monotonicity carried through; F9 robust_min/max
  Optional absent.
- `GetBandsViewContractTest` (~3): valid envelope + nested
  bands dict; section Literal; bands dict empty allowed.
- `PopulationSummaryContractTest` (~5): valid 5-section payload;
  F10 zero-resolved-total rejected; F10 ≥1-resolved-total
  accepted; subset of sections accepted (Optional); F3
  capex_rd + payroll sections allowed.

Expected total: 30-40 tests.

### Commit 1c — Top-level + cross-field + Adjustment B tests

`tests/test_p3_40_contract_6_industry_baseline_resolved.py`

5 test classes:
- `IndustryBaselineResolvedContractTopLevelTest` (~6): valid
  full payload; extra='forbid' on top-level; required field
  rejections for the 5 top-level fields.
- `CompositionInternalTest` (~5): top-level wraps 4 sub-contracts
  correctly; each sub-contract's invariant violation propagates
  through the top-level validator; cascade_payloads dict typing
  enforced.
- `CrossFieldInvariantTest` (~4): F10 + F12 both halves of each
  pair (already covered in 1b; carry one end-to-end pair here
  for top-level visibility).
- `BusinessProfileInputContractInputSurfaceTest` (~3): the
  business_profile is the BOUNDARY INPUT shape; validate it
  separately from the OUTPUT shapes (cascade/cohort/views/summary).
- `ApiBoundaryContractViolationTest` (~4): Adjustment B per
  Contracts 3-5 pattern. ContractViolation message uses
  `INDUSTRY_BASELINE_STAGE_LABEL`; structured attrs accessible;
  survives intake_consult.py:7377 generic Exception catch;
  source_payload not dumped into str.

Expected total: 20-25 tests.

### Commit 2 — SKIP per Contract 4+5 precedent

No adapter. Each shape is already a dict; `model_validate` +
the enforcement helpers bridge directly. No dataclass to
bridge to/from.

Implementation sequence: **1a → 1b → 1c → 3** (4 commits).

### Commit 3 — Gate wirings + helpers + diagnostic codes + observability invariant test

ONE commit covering all gates per F14/F15 + helpers + codes.

Files modified:
- `python/client_intake_and_finmo/post_intake_diagnostics/phase_codes.py`
  (add `PhaseCode.INDUSTRY_BASELINE_CONTRACT` +
  `EventCode.INDUSTRY_BASELINE_CONTRACT_VALIDATED` +
  `EventCode.INDUSTRY_BASELINE_CONTRACT_VIOLATION` + partition
  entry)
- `python/client_intake_and_finmo/post_intake_diagnostics/fail_fast_codes.py`
  (add `FailFastCode.FAIL_INDUSTRY_BASELINE_CONTRACT_VIOLATION`
  + partition entry + raise_fail_fast failed_event mapping)
- `tests/test_phase_9_p3_33_phase3_step9a_phase_codes.py`
  (rename `_eighteen_phases` → `_nineteen_phases`; count
  18 → 19)
- `python/client_intake_and_finmo/post_intake_contracts/enforcement.py`
  (add 4 helpers: `validate_industry_baseline_cascade_payload_at_boundary`,
  `validate_industry_baseline_cohort_sql_row_at_boundary`,
  `validate_industry_baseline_get_bands_view_at_boundary`,
  `validate_industry_baseline_population_summary_at_boundary`;
  re-export INDUSTRY_BASELINE_STAGE_LABEL; `__all__` updated)
- `python/client_intake_and_finmo/post_intake_initial_grid/runner.py`
  (cohort producer-side gate at runner.py:580+ for Shape D)
- `python/client_intake_and_finmo/finmo_bridge.py`
  (Shape A consumer-side gate inside `_attach_seed_provenance`
  at finmo_bridge.py:339+)
- `python/client_intake_and_finmo/post_intake_solver/driver_movement_assembler.py`
  (Shape A consumer-side gate inside `_resolve_naics_band` at
  driver_movement_assembler.py:97+)
- `python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py`
  (Shape C consumer-side gate inside `get_bands` immediately
  before return at cohort_bands_table.py:386+)
- `tests/test_p3_40_diagnostic_emission_invariant.py`
  (ContractSixEmitsIndustryBaselinePhaseCodeTest +
  PhaseCodesDoNotCrossContaminateTest extension)
- `tests/test_p3_40_contract_6_consumer_gate.py` (NEW)

Tests in `tests/test_p3_40_contract_6_consumer_gate.py`:
- `CohortProducerGateTest` (~3): valid Shape D bundle through
  producer gate; F10 zero-resolved rejected; passes side='producer'.
- `Shape{A,C}ConsumerGateTest` (~6 total): valid payloads through
  each gate; bad sub-payloads rejected with field path; per-gate
  ContractViolation stage label.
- `CrossShapeNoLeakageTest` (~2): a Shape A payload rejected
  by Shape C helper (and vice-versa); each shape validates only
  itself.
- `ApiCatchPatternEndToEndTest` (~3): Adjustment B per Contracts
  3-5 pattern.
- `DiagnosticEmitBestEffortTest` (~2): valid AND violation paths
  both succeed when emit_diagnostic_fn raises.

Expected total: 16-18 tests in consumer_gate file + 2 in
invariant file = ~20 new tests.

---

## 7. Open flags for Nick's review

18 numbered flags with spec recommendations matching the PSL
pre-stated leans. **Multi-residual flag count matches handoff
doc framing.**

### F0 — Single contract vs split into 4

**(Recommended) (a) Single Contract 6 module with 4 typed
sub-contracts inside.** One boundary, one Contract 6 file.
Mirrors Contract 2's pattern (one workbook payload contract,
multiple sub-shapes). Total LOC ~600-800 — pushes the 700-LOC
cap but acceptable per prior 1a precedent.

**(b) Four separate contracts (Contract 6a/6b/6c/6d).** Each
gets its own focused trace + spec + implementation. Higher
overhead; longer timeline; fragments the boundary across
modules. Recommend against.

### F1 — Composition with Contract 5

**(Recommended) (a) NO composition.** Per trace T4. Contract 6
takes a 4-field `business_profile` EXTRACTED from Contract 5's
intake fields; doesn't wrap IntakeDraftContract. The
`BusinessProfileInputContract` types the input shape standalone.

### F2 — `business_profile.business_model` typing

**(Recommended) (a) `Literal[None]`.** Pins the always-None
state explicitly per trace T1.2 verification at runner.py:577.
A future code change setting `business_model = "saas"` surfaces
as ContractViolation, forcing contract update alongside code.

**(b) `Optional[str] = None`.** Permits future enabling without
contract amendment. Trade-off: loses the explicit always-None
documentation. Recommend (a) per "match production reality
verbatim" principle.

### F3 — Cohort sections inclusion

**(Recommended) (a) Include all 5 sections** (drivers,
balance_sheet, stage_ramp, capex_rd, payroll) in the
`SUPPORTED_SECTIONS` Literal. capex_rd + payroll are
defined-but-not-populated today per v1 §D-2 — the contract
permits them as valid section names so future populator
extensions don't require contract amendment.

### F4 — `fallback_chain_attempted` inclusion

**(Recommended) (a) Include on Shape A as
`List[str]`.** Matches T1.1 field count of 13; documents the
diagnostic-only purpose in the field's docstring.

**(b) Exclude (diagnostic R-residual).** Trims the contract by
1 field. Recommend against — production writes it; contract
should match.

### F5 — `cohort_query` field inclusion — AMENDED to Option α (DROP entirely from Shape A); Shape B silent-drop RESOLVED per Cleanup Commit 1

**Pre-1a re-verification finding:** Original F5 disposition put
`cohort_query` on Shape A, but trace re-verification of
`_payload_from_row` at lookup.py:240-256 confirms the cascade
resolver returns **13 fields, NO `cohort_query`**. The field
exists only on the cohort-side `CohortBandResult` intermediate
dataclass at
[cohort_band_resolver.py:163](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L163),
which is internal to the cohort resolver and NOT one of the 4
boundary shapes (A/B/C/D). The SQL INSERT at
[cohort_bands_table.py:209-244](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L209)
silently drops it at materialization (v1 §F-1 known bug; R10
covers the producer-side fix). So cohort_query crosses no
boundary surface today; it doesn't belong in Contract 6.

**(Recommended and adopted) (α) DROP entirely from Contract 6.**
The contract types only what crosses the boundary surface;
internal intermediates are out of scope. When R10 lands and
`cohort_query` reaches Shape B's SQL row, the contract gets
amended at that time.

**(β) Add `CohortBandResolverResultContract` as a 7th sub-contract
to type the intermediate.** Considered and rejected: contracts
are boundary gates, not internal-data type-coverage tools.
Pydantic-typing an internal dataclass adds no enforcement value
today.

**(γ) Add `cohort_query` to Shape A speculatively.** Considered
and rejected: Shape A genuinely doesn't carry the field;
speculative inclusion would fail validation on every real
production payload.

### F6 — NAICS field name variation pinning

**(Recommended) (a) Pin canonical to `naics_6` in
BusinessProfileInputContract.** Aliases (`business_naics_6`,
`naics_code`, `business_naics`) live at upstream producer
sites; Contract 5b sub-contracts would normalize there.

### F7 — Shape B vs Shape C separate sub-contracts — asymmetry RESOLVED per Cleanup Commit 1

**(Recommended) (a) SEPARATE sub-contracts.** Shape B has 17
SQL cols (now 18 post-Cleanup-Commit-1 cohort_query addition);
Shape C had 11 in-memory fields (now 14 post-Cleanup-Commit-1
naics_prefix_used + data_source addition).

**Post-Cleanup-Commit-1 status:** the structural drop of
`naics_prefix_used` + `data_source` at SQL → in-memory
translation is RESOLVED. R11 closure landed in Cleanup Commit 1
— both fields now flow through `get_bands()` symmetrically.
Sub-contracts remain SEPARATE because they still differ
structurally (Shape B has PK fields + resolved_at + cohort_query
that Shape C doesn't surface); the F7 separation is now a clean
structural distinction, not an asymmetry workaround. Original F7
asymmetry rationale preserved here for historical context.

### F8 — `confidence_tier` Literal pinning

**(Recommended) (a) `Literal["high", "medium", "low",
"generic_default"]`.** Shared vocabulary across cascade and
cohort per v1 §E. Producer-side semantics (cascade uses
NAICS-level logic, cohort uses firm-count logic) are out of
scope — the contract types the vocabulary.

### F9 — `robust_min`/`robust_max` Optional handling

**(Recommended) (a) `Optional[float] = None` on Shape B + Shape C.**
Cohort writes them; future cascade fallback wouldn't.
Production reality.

### F10 — FAIL_COHORT_BANDS_MISSING precondition

**(Recommended) (a) Add `@model_validator` on Shape D requiring
total_resolved ≥ 1 across all 5 sections.** Surfaces the v1
§F-2 precondition that today is swallowed by the soft try/except
at runner.py:556-583.

**(b) Skip — leave as runtime fail-fast inside the populator.**
Loses contract-level enforcement; preserves the silent-skip
behavior. Recommend against.

### F11 — NAICS-6 length validation — AMENDED per Cleanup Commit 2 (pattern DROPPED)

**Original disposition (a) `Field(default=None, pattern=r"^[0-9]{6}$")`**
on `BusinessProfileInputContract.naics_6` shipped in Contract 6
Commit 1a.

**Post-Cleanup-Commit-2 amendment:** R16 inverse-retrofit
assessment found the pattern constraint DIVERGENT from 5b/5d's
bare `Optional[str] = None` typing per §0 value-constraint
policy. Pattern DROPPED in Cleanup Commit 2; field now bare
`Optional[str] = None`.

Rationale per PSL2 production-reality-wins: runner.py:562 strips
non-digit characters upstream
(`"".join(ch for ch in str(ops_json.get("business_naics_6") or "") if ch.isdigit())`)
before passing the value, so payloads reaching this contract
are already digit-only or empty. The pattern caught only
hypothetical legacy non-digit inputs the upstream strip
already handles. Net behavior change: zero (production payloads
already satisfied the pattern post-strip; downstream NAICS
resolution at runner.py:283-287 handles empty-string-as-
no-coverage gracefully). §0 alignment is the win.

R17 (NAICS normalizer length-validation cleanup) re-scoped
post-Cleanup-Commit-2: with the contract no longer enforcing
the pattern, R17 is about adding the strip to ALL callers of
`_naics_6_from_ops` (currently only one caller — runner.py:562
— strips). Tracked separately.

### F12 — Benchmark monotonicity invariant

**(Recommended) (a) `@model_validator(mode="after")` on
`CohortSqlRowContract` + `GetBandsViewBandContract` requiring
`benchmark_min <= benchmark_target <= benchmark_max` when all 3
non-None.** Closes v1 §F-5 defensively. Production today
guarantees this via percentile interpolation; the contract pins
it so future data-source changes can't silently violate.

### F13 — `trust_flag` + `naics_level_used` Literal pinning

**(Recommended) (a) Pin both via Literal[...].**
- `trust_flag`: 6 values (`"naics_6_direct"`, ...,
  `"no_coverage"`).
- `naics_level_used`: `Literal[0, 2, 3, 4, 5, 6]` (non-contiguous;
  no level 1 per trace T5.3).

### F14 — Producer-side gate (split disposition)

**(Recommended) (a) SHIP cohort producer-side gate at
runner.py:580 (single producer)** for Shape D + Shape B
precondition. **SKIP cascade producer-side** (multiple
consumer-driven call sites; Contract 2 R8 pattern).

### F15 — Consumer-side gate placement (per-shape)

**(Recommended) (a) Per-shape consumer-side gates** at:
- Shape A: `_attach_seed_provenance` (finmo_bridge.py:339);
  `_resolve_naics_band` (driver_movement_assembler.py:97).
- Shape C: inside `get_bands` immediately before return
  (cohort_bands_table.py:386+).
- Shape B: SKIP per-row validation (no in-process consumer reads
  SQL rows directly; consumers go through Shape C via `get_bands`).
  R-residual cleanup.

### F16 — Diagnostic-emission invariant test + PhaseCode

**(Recommended) (a) SINGLE PhaseCode for Contract 6** covering
all 4 shapes. One boundary, one phase. `diagnostic_data["shape"]`
field distinguishes A/B/C/D for queryability.
`ContractSixEmits*` + cross-contamination check per Contracts
2-5 pattern. Lockstep PhaseCode count 18 → 19.

### F17 — Adjustment B carry-over

**(Recommended) (a) Re-use Contracts 3-5 pattern verbatim.**
intake_consult.py:7377 generic Exception catch propagates
ContractViolation as structured 500 with str(exc) carrying
`INDUSTRY_BASELINE_STAGE_LABEL`. Test class mirrors Contracts
3-5 `ApiCatchPatternEndToEndTest`.

### F18 — extra policy

**(Recommended) (a) `extra="forbid"` on top-level
IndustryBaselineResolvedContract.** All sub-contracts use
`extra="ignore"` per the established Contracts 1-5 convention.

---

## 8. Known residual cleanups (out of scope for Contract 6)

**P3.40 Contract Layer Cleanup Pass 6/6 final dispositions:**
- R8 → **DONE** in Cleanup 5/6 (count invariant added).
- R9 → **DONE** in Cleanup 5/6 (cascade_payloads + get_bands_views key/value consistency invariants added).
- R10 → **DONE** in Cleanup 1/6 (cohort_query SQL persistence + Shape B contract amendment; DB migration note in commit summary).
- R11 → **DONE** in Cleanup 1/6 (naics_prefix_used + data_source surfaced in get_bands; Shape C contract amended; F7 asymmetry resolved).
- R12 → **DEFERRED**: `business_model` typing upgrade pending future use case.
- R13 → **DEFERRED**: Per-row contract validation inside populator loop; defense-in-depth without driving need.
- R14 → **DEFERRED**: Producer-side cascade resolver gate at multiple sites; Contract 2 R8 pattern follow-up.
- R15 → **DEFERRED**: Confidence-tier semantic split pending vocabulary ambiguity.
- R16 → **DONE** in Cleanup 2/6 (per-field assessment; naics_6 pattern dropped for §0 alignment; stage already consistent; target_annual_revenue+business_model UNIQUE).
- R17 → **DONE** in Cleanup 5/6 (NAICS normalizer length-warning at _naics_6_from_ops upstream).
- R18 → **DEFERRED**: Cohort row cache silent-None is internal to resolver; out of boundary scope.
- R19 → **DEFERRED**: Confidence-tier dual-meaning documentation; cosmetic.
- R20 → **DEFERRED**: Cohort section coverage rules; semantic policy not contract scope.
- R21 → **DEFERRED**: Section-level resolved-count thresholds; F10 (a) baseline kept.
- R22 → **DEFERRED**: cohort_table Literal enforcement at upstream; contract layer covers downstream.
- R23 → **DEFERRED**: End-to-end IndustryBaselineResolvedContract round-trip test; integration scope.
- R24 → **DONE** via Cleanup 2/6 naics_6 pattern drop (digit-length validation re-located to upstream R17).
- R25 → **DEFERRED**: cohort_table value harmonization with resolver vocabulary; semantic alignment.

- **R8.** ~~`get_bands_views[section].count == len(bands)`
  cross-field invariant. Cheap; deferred to keep §4 lean.~~
  **RESOLVED in P3.40 Contract Layer Cleanup Commit 5/6.**
  Added `@model_validator(mode="after")` on
  `GetBandsViewContract` enforcing `count == len(bands)`.
  STRUCTURAL consistency check, not value-level — §0-compatible.
  Catches producer drift where the envelope reports a count
  that doesn't match the actual bands map size.
- **R9.** ~~`cascade_payloads[metric_key].metric_key == metric_key`
  cross-field invariant.~~ **RESOLVED in P3.40 Contract Layer
  Cleanup Commit 5/6.** Added `@model_validator(mode="after")`
  on `IndustryBaselineResolvedContract` enforcing key/value
  metric_key consistency for `cascade_payloads` AND a mirror
  invariant enforcing key/value section consistency for
  `get_bands_views`. Both STRUCTURAL key/value identity
  checks — §0-compatible.
- **R10.** ~~Extend Shape B (SQL INSERT) to include `cohort_query`
  column. Closes the v1 §F-1 audit-trail gap.~~ **RESOLVED in
  P3.40 Contract Layer Cleanup Commit 1.** The SQL DDL +
  INSERT + ON DUPLICATE KEY UPDATE at
  cohort_bands_table.py:32-58 + :206-260 now persist
  `cohort_query` as a JSON column. `CohortSqlRowContract`
  (Shape B) amended to type the field as
  `Optional[Dict[str, Any]] = None` (Optional for legacy rows
  pre-dating Cleanup Commit 1 which carry NULL). Shape A
  disposition (F5-α DROP) unchanged — cohort_query crosses
  no Shape A boundary surface. **DB migration note:** existing
  production tables need a separate `ALTER TABLE
  post_intake_cohort_bands ADD COLUMN cohort_query JSON NULL`
  migration; the inline `CREATE TABLE IF NOT EXISTS` only
  helps fresh deployments.
- **R11.** ~~Extend `get_bands` to return `naics_prefix_used` +
  `data_source` (close the silent-drop asymmetry per F7).~~
  **RESOLVED in P3.40 Contract Layer Cleanup Commit 1.** The
  SQL → in-memory translation at cohort_bands_table.py:347-396
  now surfaces both fields to in-memory consumers
  (mirror.build_mirror, evaluate_plan).
  `GetBandsViewBandContract` (Shape C nested) amended to type
  them as `Optional[str] = None` (Optional for legacy
  in-memory views, if any cached, that pre-date the cleanup).
  Field count per band: 12 → 14. Shape B / Shape C
  asymmetry per F7 RESOLVED.
- **R12.** Type-tighten `business_profile.business_model` to
  reflect a future-enabled value once a producer writes
  non-None. Currently `Literal[None]` per F2 (a); upgrade when
  use cases land.
- **R13.** Shape B per-row contract validation inside the
  populator loop. Currently skipped per F15 (a). Add as
  defense-in-depth if future direct-SQL consumers emerge.
- **R14.** Producer-side cascade resolver gate. Currently SKIP
  per F14; producer-side gates at the cascade resolver's
  multiple call sites would be per-site Contract 2 R8 follow-ups.
- **R15.** Confidence-tier semantic split — type cascade-side
  and cohort-side confidence_tier as distinct fields if the
  shared vocabulary becomes ambiguous. Currently F8 (a) types
  them as a shared Literal.
- **R16.** ~~Inverse retrofit: Contract 5b/c/d sub-contracts for
  intake-side `business_naics_6` / `business_stage` /
  `company_revenue_total_year1` would let `BusinessProfileInputContract`
  compose those instead of accepting opaque types.~~
  **RESOLVED in P3.40 Contract Layer Cleanup Commit 2 (per-field
  composition assessment).** Per-field findings:
  - `naics_6` was DIVERGENT (Contract 6 had
    `Field(pattern=r'^[0-9]{6}$')` per F11; 5b/5d are bare
    `Optional[str] = None` per §0). Pattern DROPPED in
    Cleanup Commit 2 to align with §0. PSL2 production-
    reality-wins: runner.py:562 strips non-digit chars
    upstream so the pattern caught only hypothetical legacy
    non-digit inputs the upstream strip already handles.
    Field count + structure unchanged; only the pattern
    constraint removed. F11 disposition amended.
  - `stage` was SHARED and ALREADY CONSISTENT with 5b's
    `business_stage` (both bare `Optional[str] = None`). No
    code change; consistency documented in the contract
    module docstring.
  - `target_annual_revenue` is UNIQUE in the 5b/c/d wave
    (sourced from `financials_year1_json.
    company_revenue_total_year1`, which is the python-
    aggregated Contract 5e/h R-residual track). No
    composition opportunity until 5e/h lands. R-residual
    re-opened as R16-bis pending 5e/h.
  - `business_model` is UNIQUE. `Literal[None]` per F2/R12
    preserved — STRUCTURAL value-pin (not enum-vocabulary
    narrowing); §0's Literal ban targets enum narrowings.
    R12 covers the upgrade.

  Composition opportunity assessed as 1 alignment (naics_6
  pattern drop) + 1 already-consistent (stage) + 2 unique
  (target_annual_revenue, business_model). No sub-contract
  IMPORT performed -- the directive's "only ACTUAL
  composition if a 5b/c/d nested-object shape is structurally
  consumed" gate filtered out scalar field overlaps. R16
  status: structurally aligned per §0 where applicable.
- **R17.** ~~NAICS normalizer length-validation cleanup.~~
  **RESOLVED in P3.40 Contract Layer Cleanup Commit 5/6.**
  Added defense-in-depth length-check + warning log at
  `_naics_6_from_ops` (finmo_bridge.py:332-360) so non-6-digit
  NAICS codes log a warning at the source. PSL2 production-
  reality-wins: log-only (does NOT reject) -- downstream
  NAICS resolution at runner.py:283-287 handles partial /
  empty values via fallback chain. Complements F11 (DROPPED
  in Cleanup Commit 2) by surfacing the malformed-NAICS
  signal at the producer instead of the gate.
- **R18.** Cohort row cache silent-None per v1 §F-4. Internal
  to resolver; not directly boundary scope.
- **R19.** Confidence-tier dual-meaning documentation in the
  contract module docstring.
- **R20.** Cohort section coverage rules — when capex_rd +
  payroll start populating, add per-section invariants. F3 (a)
  permits empty sections; tightening is R-residual.
- **R21.** Section-level resolved-count thresholds — F10 (a)
  requires total ≥ 1; per-section minimums (e.g., drivers ≥ 1
  always) would be R-residual.
- **R22.** Cohort_table Literal enforcement at upstream
  resolver. Contract types `Literal["edgar", "alpha"]`;
  producer could regress to other values without the gate
  catching at production-time.
- **R23.** End-to-end IndustryBaselineResolvedContract
  round-trip test — exercises all 4 shapes together; useful for
  full-pipeline regression detection.
- **R24.** Shape A `naics_code_used` digit-length validation —
  similar to F11 but on the OUTPUT field rather than input.
- **R25.** `cohort_table` value harmonization with the resolver's
  source-table naming (currently `"edgar"` / `"alpha"` per
  resolver; SQL stores up to 16 chars). Confirm no third value
  exists in production.

---

## 9. Workflow

Same as Contracts 1, 2, 3, 4, 5: trace doc + spec doc each ship
as single commits, held for Nick review. After spec approval,
the 4-commit implementation series (1a → 1b → 1c → 3) lands per
§6 with push + email per commit.

Per-commit LOC cap: 700. Commit 1a is expected to push or exceed
the cap given the 6 sub-contracts + invariants + 5 module
constants. Single-artifact ship is acceptable per prior 1a
precedent (Contract 1 1a at 749 LOC, Contract 2 1b at 847 LOC).

If during Commit 1a (the contract module) I find anything else
that diverges from production, I'll flag back the same way
Contracts 1-5 did — no silent adjustment.

After Commit 3 lands and the full P3.40 contracts suite goes
green, Contract 6 is end-to-end. Boundary 2 (POST_INTAKE_INPUT →
INDUSTRY_BASELINE) is contract-typed with:
- Cohort producer-side gate at runner.py:580 (Shape D + F10
  precondition).
- 3 consumer-side gates per F15 (Shape A × 2, Shape C × 1).
- 4 enforcement helpers (one per shape) sharing a single
  PhaseCode (F16).
- 4 Literal-pinned vocabularies (sections, NAICS levels,
  confidence tiers, trust flags).
- 2 cross-field invariants (F10 zero-resolved precondition +
  F12 benchmark monotonicity × 2 sub-contracts = 3 validators).
- 1 input pattern validation (F11 NAICS-6 length).

Expected full-suite total after Contract 6 Commit 3:
407 (today) + ~30 (1b) + ~22 (1c) + ~20 (3) = ~480 passed.

The next direction (Contract 7 — AmalgamatedSessionContract /
the final P3.40 contract, or R-residual sub-contract typing
waves like Contract 5b/c/d) comes from Nick.
