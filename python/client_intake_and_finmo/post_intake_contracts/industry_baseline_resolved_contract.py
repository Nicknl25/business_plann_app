"""IndustryBaselineResolvedContract -- typed contract for the
4-shape boundary at POST_INTAKE_INPUT -> INDUSTRY_BASELINE
(Boundary 2).

Sixth of seven typed inter-stage contracts. Spec:
``docs/architecture/p3_40_contract_6_industry_baseline_spec.md``
(commit cbfa162 + F5 amendment a6fc352). Trace:
``docs/architecture/p3_40_contract_6_industry_baseline_trace.md``
(commit a03e098).

First MULTI-SHAPE boundary in the P3.40 series. Unlike Contracts
1-5 (each typed ONE dict at ONE handoff point), Contract 6 spans
4 distinct payload shapes inside a single module per F0 (a):

  Shape A -- ``CascadeResolverPayloadContract`` (13 fields per
    metric). Producer: ``_payload_from_row`` at
    lookup.py:240-256. Consumers: ``_attach_seed_provenance``
    (finmo_bridge.py:339); ``driver_movement_assembler._resolve_naics_band``
    (driver_movement_assembler.py:97).
  Shape B -- ``CohortSqlRowContract`` (17 cols + auto-stamp).
    Producer: ``populate_cohort_bands_for_run`` INSERT at
    cohort_bands_table.py:209-244. Consumer: persisted to
    ``post_intake_cohort_bands`` SQL table; in-process consumers
    go through Shape C.
  Shape C -- ``GetBandsViewContract`` (envelope + nested
    ``GetBandsViewBandContract`` per lever_id; 11 fields per
    band). Producer: ``get_bands`` at cohort_bands_table.py:344-392.
    Consumers: every amalgamated tool's _echo_*_bands helper +
    ``mirror.build_mirror`` + ``evaluate_plan._margin_distance_from_bands``.
  Shape D -- ``PopulationSummaryContract`` ({drivers, balance_sheet,
    stage_ramp, capex_rd, payroll} each with resolved/skipped
    counts). Producer: ``populate_cohort_bands_for_run`` return
    value. Consumer: logged into
    ``sequence_trace['cohort_bands_populated']`` at runner.py:582.

Plus the boundary INPUT shape:

  ``BusinessProfileInputContract`` (4 fields). Built at
  runner.py:573-579, extracted from Contract 5 intake fields
  (ops_json.business_naics_6, ops_json.business_stage,
  financials_year1_json.company_revenue_total_year1).

Plus the top-level wrapper:

  ``IndustryBaselineResolvedContract`` -- bundles all 4 output
  shapes + the input shape for one-stop import + diagnostic
  attribution. In production the 4 shapes validate INDEPENDENTLY
  at their respective producer/consumer sites per F15; the
  top-level exists for end-to-end test round-trips.

Composition policy (per F1):
- ZERO composition with prior contracts. Contract 6 is upstream
  of nothing and downstream of nothing in the contract graph;
  it shares no typed sub-shapes with Contracts 1-5.
- ContractViolation is re-exported (via finmo_model_input_contract)
  so gate callers import from one place.

extra-key policy (per F18):
- ``extra="forbid"`` on top-level IndustryBaselineResolvedContract.
- ``extra="ignore"`` on all 6 sub-contracts. Per F7 the
  GetBandsView silently drops 2 SQL columns (naics_prefix_used,
  data_source) at SQL -> in-memory translation -- the
  extra="ignore" preserves that asymmetry without requiring the
  producer to stop emitting them.

F5-α (amended at a6fc352): cohort_query is DROPPED from Contract 6
entirely. Cascade resolver doesn't emit it (verified at
lookup.py:240-256: 13 fields, no cohort_query). The field exists
only on the cohort-side CohortBandResult intermediate dataclass at
cohort_band_resolver.py:163 -- internal to the cohort resolver,
not a boundary surface. SQL INSERT at cohort_bands_table.py:209-244
silently drops it at materialization (v1 §F-1 known bug). R10
covers the upstream fix; once cohort_query reaches Shape B's SQL
row, this contract gets amended.

F7: Shape B (CohortSqlRowContract, 17 cols) and Shape C
(GetBandsViewBandContract, 11 fields per band) ship as SEPARATE
sub-contracts. The structural drop of ``naics_prefix_used`` +
``data_source`` at SQL -> in-memory translation is a CONTRACT-
LEVEL FACT, not a runtime bug. Consumers know they're working
with a stripped view; R11 covers the upstream fix.

Cross-field invariants (per Section 4):
- F10: PopulationSummaryContract @model_validator requires
  total resolved >= 1 across all 5 sections (closes v1 §F-2
  FAIL_COHORT_BANDS_MISSING precondition that today is swallowed
  by the soft try/except at runner.py:556-583).
- F12 (a): CohortSqlRowContract @model_validator requires
  benchmark_min <= benchmark_target <= benchmark_max when all 3
  non-None.
- F12 (b): GetBandsViewBandContract @model_validator -- same
  monotonicity invariant (carried through SQL -> in-memory).

Literal pinning (per F2 / F3 / F8 / F13):
- business_model: Literal[None] (always-None per F2 -- pins
  production reality; future enable forces contract amendment).
- section: Literal of 5 values (drivers, balance_sheet,
  stage_ramp, capex_rd, payroll). capex_rd + payroll are
  defined-but-not-populated today per v1 §D-2; the Literal
  permits them as valid names so future populator extensions
  don't require contract amendment.
- confidence_tier: Literal of 4 values (high, medium, low,
  generic_default) -- shared vocabulary across cascade and
  cohort per v1 §E.
- trust_flag: Literal of 6 values (naics_6_direct,
  naics_5_fallback, naics_4_fallback, naics_3_fallback,
  naics_2_fallback, no_coverage).
- naics_level_used: Literal[0, 2, 3, 4, 5, 6] -- non-contiguous;
  no level 1 per trace T5.3.
- cohort_table: Literal["edgar", "alpha"].

NAICS-6 pattern validation (per F11): business_profile.naics_6
and Shape A naics_code_used both type as
Optional[str] = Field(default=None, pattern=r"^[0-9]{6}$").
Surfaces v1 §F-3 garbage inputs at the contract gate.

Residual cleanups deliberately deferred (spec §8):

  - R8.  ``get_bands_views[section].count == len(bands)``
         cross-field invariant.
  - R9.  ``cascade_payloads[metric_key].metric_key == metric_key``
         cross-field invariant.
  - R10. Extend Shape B SQL INSERT to include cohort_query;
         then amend Contract 6 to add it.
  - R11. Extend get_bands to return naics_prefix_used +
         data_source (close F7 silent-drop asymmetry).
  - R12. Type-tighten business_model when use cases land.
  - R13. Shape B per-row contract validation inside populator
         loop.
  - R14. Producer-side cascade resolver gate.
  - R15. Confidence-tier semantic split if shared vocabulary
         becomes ambiguous.
  - R16. Inverse retrofit when Contract 5b/c/d sub-contracts
         land.
  - R17. NAICS normalizer length-validation cleanup at
         upstream _naics_6_from_ops.
  - R18-R25. Misc upstream cleanups + future-extension hooks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  model_validator,
)

# Only re-export ContractViolation -- Contract 6 has ZERO
# composition with prior contracts (F1).
from client_intake_and_finmo.post_intake_contracts.finmo_model_input_contract import (
  ContractViolation,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Stage label for the boundary gates. Used in ContractViolation.stage
#: and diagnostic_data.stage. Names the actual producer -> consumer
#: direction at this boundary surface.
INDUSTRY_BASELINE_STAGE_LABEL = "POST_INTAKE_INPUT->INDUSTRY_BASELINE"

#: NAICS resolution levels per cascade walk (per trace T5.3). The
#: cascade walks 6 -> 5 -> 4 -> 3 -> 2 -> 0 (generic_default).
#: Non-contiguous -- there's no level 1 in the cascade.
SUPPORTED_NAICS_LEVELS = (6, 5, 4, 3, 2, 0)

#: Confidence tier vocabulary -- shared across cascade and cohort
#: (per trace T5.4 / v1 §E "same vocabulary, different meaning").
#: The contract types the vocabulary; producer-side computation
#: semantics are out of scope.
SUPPORTED_CONFIDENCE_TIERS = ("high", "medium", "low", "generic_default")

#: Trust flag values per cascade walk (per F13 / trace T5.2).
SUPPORTED_TRUST_FLAGS = (
  "naics_6_direct",
  "naics_5_fallback",
  "naics_4_fallback",
  "naics_3_fallback",
  "naics_2_fallback",
  "no_coverage",
)

#: Cohort section names per F3. capex_rd + payroll are
#: defined-but-not-yet-populated today per v1 §D-2; the Literal
#: permits them as valid section names so future populator
#: extensions don't require contract amendment.
SUPPORTED_SECTIONS = (
  "drivers",
  "balance_sheet",
  "stage_ramp",
  "capex_rd",
  "payroll",
)

#: Cohort tables the resolver may target.
SUPPORTED_COHORT_TABLES = ("edgar", "alpha")


# ---------------------------------------------------------------------------
# BusinessProfileInputContract -- Boundary INPUT shape
# ---------------------------------------------------------------------------

class BusinessProfileInputContract(BaseModel):
  """The 4-field business_profile input dict built at
  runner.py:558-578 from Contract 5 intake fields.

  R16 closure (Cleanup Commit 2): per-field composition
  assessment with Contracts 5b/5c/5d typed sub-contracts:
    - ``naics_6`` SHARED with 5b's
      ``OperatingModelJsonContract.business_naics_6`` + 5d's
      ``PeopleJsonContract.business_naics_6`` (both bare
      ``Optional[str] = None`` per §0). Previously DIVERGENT
      (Contract 6 had ``Field(pattern=r'^[0-9]{6}$')`` per
      F11); pattern dropped here to align with §0 policy.
      PSL2 production-reality-wins: runner.py:562 already
      strips non-digit characters before passing
      (``''.join(ch for ch in ... if ch.isdigit())``), so
      values reaching this contract are already digit-only
      or empty -- the pattern caught hypothetical legacy
      non-digit inputs that the upstream strip already
      handles. R16 retrofit aligns the typings.
    - ``stage`` SHARED with 5b's
      ``OperatingModelJsonContract.business_stage`` (both
      bare ``Optional[str] = None``). Already consistent
      pre-Cleanup-Commit-2; no change.
    - ``target_annual_revenue`` UNIQUE (sourced from
      ``financials_year1_json.company_revenue_total_year1``
      per runner.py:558-560 -- that's the python-aggregated
      Contract 5e/h R-residual track, not 5b/c/d). No
      composition opportunity until 5e/h lands.
    - ``business_model`` UNIQUE. ``Literal[None]`` per F2/R12
      preserved -- this is a STRUCTURAL value-pin (the field
      is always None per runner.py:577 placeholder
      semantic), NOT an enum-vocabulary narrowing. §0's
      Literal ban targets enum-vocabulary narrowings; this
      structural pin stays. R12 covers the upgrade when
      use cases land.

  Per F2 (a): ``business_model`` types as Literal[None]. Pins
  production reality verbatim (runner.py:577 always writes None
  as the placeholder per v1 §D-1). A future code change setting
  business_model = "saas" surfaces as ContractViolation, forcing
  contract amendment alongside code.
  """

  # R16 closure: pattern dropped per §0 alignment with 5b/5d's
  # bare Optional[str] = None typing. PSL2 production-reality-
  # wins (runner.py:562 strips non-digit chars upstream).
  naics_6: Optional[str] = None
  target_annual_revenue: Optional[float] = None
  stage: Optional[str] = None
  business_model: Literal[None] = None

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Shape A -- CascadeResolverPayloadContract (13 fields per metric)
# ---------------------------------------------------------------------------

class CascadeResolverPayloadContract(BaseModel):
  """The 13-field payload returned by ``_payload_from_row`` at
  ``post_intake_industry_baseline/lookup.py:240-256`` -- one per
  metric_key.

  Per F4 (a): ``fallback_chain_attempted`` is included as a
  ``List[str]`` field. Diagnostic-only per v1 §D-3 (no
  computational reader); the contract types it so producer drift
  surfaces at the boundary.

  Per F5-α (amended at a6fc352): ``cohort_query`` is NOT on this
  contract. Cascade resolver doesn't emit it (verified at
  lookup.py:240-256 verbatim). The field exists only on the
  cohort-side ``CohortBandResult`` intermediate dataclass at
  cohort_band_resolver.py:163 -- internal to the cohort resolver,
  not a boundary surface.

  Per F8 + F13: ``confidence_tier``, ``trust_flag``,
  ``naics_level_used`` all type as Literal. Typo-rejection +
  all-spellings-accepted pinned via Contract 1 typo-lock pattern.

  Per F11 / R24: ``naics_code_used`` types as Optional[str]
  with the same 6-digit pattern as ``business_profile.naics_6``.
  The producer emits the code that matched (could be 6, 5, 4, 3,
  2 digits or empty for no_coverage); the contract permits
  empty string as the no_coverage marker but requires
  digit-only when present.

  Per F8 / PSL2 (R-d-raw, P3.41): ``raw_confidence_tier`` types
  as ``Optional[str] = None``. The producer emits None on three
  fallback paths at
  ``post_intake_industry_baseline/lookup.py:299, :319, :483``:
  (1) ``_phase_9_p3_generic_default_payload`` for the working-
  capital structure metrics (Targets 3 & 4) when both alternating-
  walk + baseline come up empty; (2) ``_no_coverage_payload`` when
  no NAICS coverage exists at any level; (3) cohort_alternating
  fallback where the cohort-derived bands lack a raw signal from
  the underlying source row. The paired ``confidence_tier`` always
  resolves to a Literal value (defaults to ``"generic_default"``
  on the no-coverage paths), so the resolved tier remains pinned
  even when the raw signal is absent. This Optional flip is
  UNIVERSAL across any business hitting these no-coverage / generic-
  default paths -- not profile-specific. Surfaced by NexGen E2E
  re-run (b2b SaaS with no NAICS-6 cohort coverage).
  """

  metric_key: str = Field(min_length=1)
  benchmark_min: Optional[float] = None
  benchmark_target: Optional[float] = None
  benchmark_max: Optional[float] = None
  naics_code_used: str  # may be empty string for no_coverage
  naics_level_used: Literal[0, 2, 3, 4, 5, 6]
  data_source: str
  source_year: Optional[int] = None
  sample_size: Optional[int] = None
  confidence_tier: Literal["high", "medium", "low", "generic_default"]
  raw_confidence_tier: Optional[str] = None
  trust_flag: Literal[
    "naics_6_direct",
    "naics_5_fallback",
    "naics_4_fallback",
    "naics_3_fallback",
    "naics_2_fallback",
    "no_coverage",
  ]
  fallback_chain_attempted: List[str] = Field(default_factory=list)

  model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Shape B -- CohortSqlRowContract (17 cols + auto-stamp resolved_at)
# ---------------------------------------------------------------------------

class CohortSqlRowContract(BaseModel):
  """One row in the ``post_intake_cohort_bands`` SQL table, per
  the schema at ``cohort_bands_table.py:32-58``. 18 data columns
  + ``resolved_at`` (server-stamped on INSERT).

  Per F3: ``section`` types as Literal of 5 values.
  Per F8: ``confidence_tier`` types as Literal of 4 values.
  Per F13: ``naics_level_used`` types as Literal of 6
  non-contiguous values.
  Per F9 (a): ``robust_min`` + ``robust_max`` are Optional --
  cohort writes them; future cascade fallback rows would have
  NULL.

  Per F12 (a) cross-field invariant: when all 3 of
  benchmark_min / benchmark_target / benchmark_max are non-None,
  monotonicity (min <= target <= max) is enforced.

  R10 closure (Cleanup Commit 1): ``cohort_query`` IS now on
  this contract. Previously dropped at SQL INSERT
  (cohort_bands_table.py:209-244 silent-drop, v1 §F-1 known
  bug). The INSERT now persists the dict as JSON; this contract
  types the field as ``Optional[Dict[str, Any]] = None``.
  Original F5-α DROP from Shape A (CascadeResolverPayloadContract)
  stays -- that disposition was about Shape A, not Shape B.
  """

  draft_id: str = Field(min_length=1, max_length=64)
  planning_run_id: str = Field(min_length=1, max_length=64)
  section: Literal["drivers", "balance_sheet", "stage_ramp", "capex_rd", "payroll"]
  lever_id: str = Field(min_length=1, max_length=128)
  metric_key: str = Field(min_length=1, max_length=128)
  metric_column: Optional[str] = None
  benchmark_min: Optional[float] = None
  benchmark_target: Optional[float] = None
  benchmark_max: Optional[float] = None
  robust_min: Optional[float] = None
  robust_max: Optional[float] = None
  naics_level_used: Optional[Literal[0, 2, 3, 4, 5, 6]] = None
  naics_prefix_used: Optional[str] = None
  cohort_size: Optional[int] = None
  firm_count: Optional[int] = None
  confidence_tier: Optional[Literal["high", "medium", "low", "generic_default"]] = None
  cohort_table: Optional[Literal["edgar", "alpha"]] = None
  data_source: Optional[str] = None
  # R10 closure (Cleanup Commit 1) -- previously silently dropped
  # at SQL INSERT. Now persisted as JSON in the new cohort_query
  # column. Optional because legacy rows pre-dating Cleanup Commit
  # 1 carry NULL; PSL2 production-reality-wins.
  cohort_query: Optional[Dict[str, Any]] = None
  resolved_at: Optional[datetime] = None

  model_config = ConfigDict(extra="ignore")

  @model_validator(mode="after")
  def benchmark_monotonicity(self) -> "CohortSqlRowContract":
    """F12 (a): when all 3 benchmark values are non-None,
    enforce min <= target <= max. Cohort percentile interpolation
    guarantees this today; the validator pins it so future
    data-source changes can't silently violate."""
    if (
      self.benchmark_min is not None
      and self.benchmark_target is not None
      and self.benchmark_max is not None
    ):
      if not (self.benchmark_min <= self.benchmark_target <= self.benchmark_max):
        raise ValueError(
          f"CohortSqlRow benchmark monotonicity violated: "
          f"min={self.benchmark_min!r} target={self.benchmark_target!r} "
          f"max={self.benchmark_max!r}; required min <= target <= max"
        )
    return self


# ---------------------------------------------------------------------------
# Shape C -- GetBandsViewBandContract + GetBandsViewContract
# ---------------------------------------------------------------------------

class GetBandsViewBandContract(BaseModel):
  """One band entry inside ``GetBandsViewContract.bands``, keyed
  by lever_id. 14 fields per band -- per
  ``cohort_bands_table.py:347-386``.

  Per F7: this is a SEPARATE sub-contract from
  CohortSqlRowContract even though it's structurally a near-
  subset.

  R11 closure (Cleanup Commit 1): ``naics_prefix_used`` +
  ``data_source`` now flow through Shape B -> Shape C without
  silent drop. Previously dropped at the SQL -> in-memory
  translation in get_bands(); Contract 6 F7 documented the
  asymmetry. Asymmetry now RESOLVED -- both fields typed here
  as Optional so legacy in-memory views (if any cached
  anywhere) that pre-date Cleanup Commit 1 still validate.
  PSL2 production-reality-wins.

  Per F12 (b) cross-field invariant: same benchmark monotonicity
  as CohortSqlRowContract. Re-checked here so a future
  direct-instantiation path that bypasses Shape B can't silently
  produce non-monotonic bands.
  """

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
  # R11 closure (Cleanup Commit 1) -- the 2 fields previously
  # dropped at SQL -> in-memory translation. Now flow through
  # get_bands() so in-memory consumers (mirror.build_mirror,
  # evaluate_plan) see the same shape as the SQL row. Optional
  # for legacy-view compatibility.
  naics_prefix_used: Optional[str] = None
  data_source: Optional[str] = None

  model_config = ConfigDict(extra="ignore")

  @model_validator(mode="after")
  def benchmark_monotonicity(self) -> "GetBandsViewBandContract":
    """F12 (b): mirror of CohortSqlRowContract.benchmark_monotonicity."""
    if (
      self.benchmark_min is not None
      and self.benchmark_target is not None
      and self.benchmark_max is not None
    ):
      if not (self.benchmark_min <= self.benchmark_target <= self.benchmark_max):
        raise ValueError(
          f"GetBandsViewBand benchmark monotonicity violated: "
          f"min={self.benchmark_min!r} target={self.benchmark_target!r} "
          f"max={self.benchmark_max!r}; required min <= target <= max"
        )
    return self


class GetBandsViewContract(BaseModel):
  """The dict ``get_bands`` returns at
  ``cohort_bands_table.py:386-392``. Envelope (4 fields) +
  nested bands dict keyed by lever_id.

  Per F3: ``section`` types as Literal of 5 values.
  Per F7: bands dict values are typed as GetBandsViewBandContract.
  Per the trace: ``count`` is allowed to be 0 (empty section is
  a valid state per v1 §D-2 for capex_rd + payroll).

  R8 closure (Cleanup Commit 5/6): cross-field invariant
  ``count == len(bands)``. STRUCTURAL consistency check, not
  value-level — §0-compatible. Catches map/count drift if a
  future producer constructs the envelope with stale count.
  """

  section: Literal["drivers", "balance_sheet", "stage_ramp", "capex_rd", "payroll"]
  draft_id: str = Field(min_length=1)
  planning_run_id: str = Field(min_length=1)
  count: int = Field(ge=0)
  bands: Dict[str, GetBandsViewBandContract] = Field(default_factory=dict)

  model_config = ConfigDict(extra="ignore")

  @model_validator(mode="after")
  def count_matches_bands_length(self) -> "GetBandsViewContract":
    """R8 (Cleanup 5/6): structural cross-field consistency.
    ``count`` MUST equal ``len(bands)``. Catches a producer
    drift where the envelope reports a count that doesn't
    match the actual bands map size."""
    if self.count != len(self.bands):
      raise ValueError(
        f"GetBandsViewContract count/bands mismatch: count="
        f"{self.count} but len(bands)={len(self.bands)} "
        f"(section={self.section!r}). Producer should populate "
        f"count from len(bands) post-construction."
      )
    return self


# ---------------------------------------------------------------------------
# Shape D -- PopulationSummaryContract + PopulationSummarySectionContract
# ---------------------------------------------------------------------------

class PopulationSummarySectionContract(BaseModel):
  """One section entry inside PopulationSummaryContract, per the
  populator's return shape at ``cohort_bands_table.py:155-162``:
  ``Dict[str, Dict[str, int]]`` keyed by section name; values
  are ``{"resolved": int, "skipped": int}``."""

  resolved: int = Field(ge=0)
  skipped: int = Field(ge=0)

  model_config = ConfigDict(extra="ignore")


class PopulationSummaryContract(BaseModel):
  """Per F3: all 5 cohort sections enumerated as Optional fields.
  capex_rd + payroll are defined-but-not-yet-populated today per
  v1 §D-2; allowing Optional permits future populator extensions
  without contract amendment.

  Per F10 cross-field invariant: at least 1 resolved band must
  exist across all 5 sections combined. Surfaces v1 §F-2
  FAIL_COHORT_BANDS_MISSING precondition that today is swallowed
  by the soft try/except at runner.py:556-583.
  """

  drivers: Optional[PopulationSummarySectionContract] = None
  balance_sheet: Optional[PopulationSummarySectionContract] = None
  stage_ramp: Optional[PopulationSummarySectionContract] = None
  capex_rd: Optional[PopulationSummarySectionContract] = None
  payroll: Optional[PopulationSummarySectionContract] = None

  model_config = ConfigDict(extra="ignore")

  @model_validator(mode="after")
  def at_least_one_section_has_resolved_bands(self) -> "PopulationSummaryContract":
    """F10: total resolved bands across all 5 sections must be >= 1.
    A zero-resolved population (every section returned None or
    {resolved: 0, skipped: N}) is FAIL_COHORT_BANDS_MISSING per
    v1 §F-2 -- a contract-level fail-fast preventing downstream
    mirror_build from reading empty bands."""
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
        "PopulationSummary has zero resolved bands across all 5 sections "
        "(drivers/balance_sheet/stage_ramp/capex_rd/payroll); "
        "FAIL_COHORT_BANDS_MISSING precondition -- at least 1 "
        "resolved band is required for downstream mirror_build to "
        "succeed (v1 §F-2)"
      )
    return self


# ---------------------------------------------------------------------------
# Top-level IndustryBaselineResolvedContract
# ---------------------------------------------------------------------------

class IndustryBaselineResolvedContract(BaseModel):
  """Top-level wrapper for the 4-shape industry-baseline
  boundary. Each shape validates INDEPENDENTLY at its respective
  producer/consumer site per F15; this top-level exists for
  end-to-end test round-trips + diagnostic attribution.

  Per F0 (a): SINGLE Contract 6 module with 6 sub-contracts
  inside (BusinessProfileInputContract + 4 output shapes +
  this wrapper). Don't fragment across modules.

  Per F18: extra='forbid' on this top-level. Sub-contracts use
  extra='ignore' to preserve the F7 silent-drop asymmetry
  without forcing producer-side changes.
  """

  # Boundary INPUT shape
  business_profile: BusinessProfileInputContract

  # Boundary OUTPUT shapes (Shape A/B/C/D)
  cascade_payloads: Dict[str, CascadeResolverPayloadContract] = Field(default_factory=dict)
  cohort_rows: List[CohortSqlRowContract] = Field(default_factory=list)
  get_bands_views: Dict[str, GetBandsViewContract] = Field(default_factory=dict)
  population_summary: Optional[PopulationSummaryContract] = None

  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="after")
  def cascade_payloads_metric_key_consistency(self) -> "IndustryBaselineResolvedContract":
    """R9 closure (Cleanup 5/6): structural cross-field
    consistency. Each cascade_payloads[metric_key] entry's
    ``metric_key`` field MUST match the dict key it lives
    under. Catches map/key drift if a future producer
    constructs the dict with a payload keyed by a different
    metric_key than the payload itself carries.

    STRUCTURAL (key/value identity) -- §0-compatible. Not a
    value-level content check."""
    for key, payload in self.cascade_payloads.items():
      if payload.metric_key != key:
        raise ValueError(
          f"cascade_payloads key/value metric_key mismatch: "
          f"dict key={key!r} but payload.metric_key="
          f"{payload.metric_key!r}. Producer must key each "
          f"entry by its own metric_key field."
        )
    return self

  @model_validator(mode="after")
  def get_bands_views_section_key_consistency(self) -> "IndustryBaselineResolvedContract":
    """R9 mirror for get_bands_views (structural key/value
    consistency for the section-keyed dict). Each
    get_bands_views[section] entry's ``section`` field MUST
    match its dict key."""
    for key, view in self.get_bands_views.items():
      if view.section != key:
        raise ValueError(
          f"get_bands_views key/value section mismatch: "
          f"dict key={key!r} but view.section={view.section!r}. "
          f"Producer must key each entry by its own section field."
        )
    return self


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
  "INDUSTRY_BASELINE_STAGE_LABEL",
  "SUPPORTED_NAICS_LEVELS",
  "SUPPORTED_CONFIDENCE_TIERS",
  "SUPPORTED_TRUST_FLAGS",
  "SUPPORTED_SECTIONS",
  "SUPPORTED_COHORT_TABLES",
  "BusinessProfileInputContract",
  "CascadeResolverPayloadContract",
  "CohortSqlRowContract",
  "GetBandsViewBandContract",
  "GetBandsViewContract",
  "PopulationSummarySectionContract",
  "PopulationSummaryContract",
  "IndustryBaselineResolvedContract",
  # Re-exported from finmo_model_input_contract for one-stop
  # import at gate call sites:
  "ContractViolation",
]
