# P3.40 Contract 6 — IndustryBaselineResolvedContract — Pre-spec trace

**Boundary:** 2 (POST_INTAKE_INPUT → INDUSTRY_BASELINE).
**Status:** pre-spec trace. Holds for review before the spec doc is drafted.
**Companion to:** [p3_40_contract_6_industry_baseline_spec.md](./p3_40_contract_6_industry_baseline_spec.md) (not yet written).
**v2 inventory baseline:** [p3_40_pipeline_data_flow_inventory_v2.md §Boundary 2](./p3_40_pipeline_data_flow_inventory_v2.md#boundary-2-post_intake_input--industry_baseline) (lines 251-293).
**v1 inventory baseline (richer details):** [p3_40_pipeline_data_flow_inventory.md §Boundary 2](./p3_40_pipeline_data_flow_inventory.md#boundary-2-post_intake_input--industry_baseline) (lines 167-310).

Same trace-before-spec discipline as Contracts 1-5: enumerate
actual producer + consumer paths from production code, surface
divergences from v2, and call out anything that changes contract
design before the spec is written.

---

## Headline findings — read these first

1. **This is the first MULTI-SHAPE boundary in the P3.40 series.**
   Unlike Contracts 1-5 (each typed ONE dict at ONE handoff
   point), Contract 6 spans **4 distinct payload shapes** at the
   boundary:

   | Shape | Source | Consumer | File:line |
   |---|---|---|---|
   | A. NAICS cascade resolver payload (13 fields per metric) | `_payload_from_row` | `_attach_seed_provenance`, driver_movement_assembler | [lookup.py:237-256](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L237) |
   | B. Cohort SQL rows (17 columns per row) | `populate_cohort_bands_for_run` INSERT at [cohort_bands_table.py:209-244](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L209) | every amalgamated tool's `_echo_*_bands` helper | persisted to `post_intake_cohort_bands` SQL table |
   | C. In-memory `get_bands` view (nested by section + lever_id) | `get_bands` at [cohort_bands_table.py:344-392](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L344) | `mirror.build_mirror`, `evaluate_plan._margin_distance_from_bands` | derived from SQL rows |
   | D. Population summary | `populate_cohort_bands_for_run` return value | logged into `sequence_trace["cohort_bands_populated"]` only | [cohort_bands_table.py:155-261](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L155) |

   Spec needs to decide whether Contract 6 is ONE contract with
   4 sub-contracts (one per shape), or 4 separate contracts
   (Contract 6a / 6b / 6c / 6d). Headline flag F0 in spec §7.

2. **Boundary 2 has ZERO composition with Contract 5
   (IntakeDraftContract).** The cascade resolver and cohort
   populator take a normalized `business_profile` dict
   (4 fields: `naics_6`, `target_annual_revenue`, `stage`,
   `business_model`) extracted FROM Contract 5's intake JSON
   columns at [runner.py:556-580](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L556).
   The resolved baseline does NOT wrap intake fields; it carries
   only the new resolved-baseline data. **No composition with
   Contract 5.**

3. **v1 inventory understates resolver field count.** v1 §A
   lists 10 fields in the cascade resolver payload; actual at
   lookup.py:237-256 is **13 fields** (adds `source_year`,
   `sample_size`, `raw_confidence_tier`). NEW STRUCTURAL per §T8.

4. **v1 inventory's `get_bands` shape misses 2 SQL columns.**
   The SQL row has 17 columns; `get_bands` only echoes 11.
   `naics_prefix_used` and `data_source` are dropped at the
   in-memory shape. NEW STRUCTURAL per §T8.

5. **Multiple small residuals as predicted by the handoff doc.**
   Surface 11 distinct residual/flag candidates from T8 plus
   the standard F0/F-producer-gate/F-consumer-gate/F-AdjB/
   F-invariant slots — spec §7 likely 12-16 flags total.

---

## T1. Producer-side resolution

### T1.1 Two parallel resolvers — cascade + cohort

The industry baseline gets resolved by TWO independent code
paths that run in parallel:

- **NAICS cascade resolver** at
  [lookup.py:_payload_from_row](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L237).
  Takes (NAICS-6, metric_key); walks 6→5→4→3→2→0 levels;
  returns a 13-field dict per metric_key.
- **Cohort populator** at
  [cohort_bands_table.py:populate_cohort_bands_for_run](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L155).
  Takes business_profile; iterates over `_SECTION_LEVERS`;
  calls `resolve_cohort_band(metric_key, business_profile)` per
  lever; persists results as SQL rows into
  `post_intake_cohort_bands`; returns a population summary.

Different shapes per consumer per section. NOT a single
function returning a single payload.

### T1.2 Input: `business_profile` (Boundary 2 INPUT shape)

Built at
[runner.py:573-579](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L573):

```python
business_profile = {
  "naics_6": _bp_naics_6,                # str|None, digits-only strip of ops_json.business_naics_6
  "target_annual_revenue": _bp_target_revenue,  # float|None from financials_year1_json.company_revenue_total_year1
  "stage": _bp_stage,                    # str|None lowercased from ops_json.business_stage
  "business_model": None,                # ALWAYS None (placeholder per v1 §D-1)
}
```

4 fields. Per v1 §D-1, `business_model` is always None —
placeholder reserved for future use. `map_revenue_to_cap_categories`
at cohort_band_resolver.py:211-247 accepts but does not consume
it.

**Producer of business_profile inputs:** Contract 5
(IntakeDraftContract) provides `ops_json` and
`financials_year1_json`. The runner extracts/normalizes the 4
fields. Contract 6 takes this as INPUT but does NOT compose
Contract 5 — `business_profile` is a derived 4-field projection,
not a wrapper.

### T1.3 Output A — Cascade resolver payload (per metric)

Verbatim from
[lookup.py:237-256](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L237):

```python
return {
  "metric_key": metric_key,
  "benchmark_min": _decimal_to_float(row.get("benchmark_min")),
  "benchmark_target": _decimal_to_float(row.get("benchmark_target")),
  "benchmark_max": _decimal_to_float(row.get("benchmark_max")),
  "naics_code_used": str(row.get("naics_code") or "").strip(),
  "naics_level_used": int(level_used),
  "data_source": str(row.get("data_source") or "").strip(),
  "source_year": int(row["source_year"]) if row.get("source_year") is not None else None,
  "sample_size": int(row["sample_size"]) if row.get("sample_size") is not None else None,
  "confidence_tier": _downgrade_confidence(raw_confidence, level_used=level_used),
  "raw_confidence_tier": raw_confidence,
  "trust_flag": trust_flag,
  "fallback_chain_attempted": list(fallback_chain),
}
```

**13 fields per metric_key.** v1 §A claimed 10 (missing
`source_year`, `sample_size`, `raw_confidence_tier`). Documented
as NEW STRUCTURAL Div-3 in §T8.

Numeric fields type as `float` (decimal-coerced via
`_decimal_to_float`); int fields cast via `int(...)`;
`raw_confidence_tier` is a non-downgraded variant alongside
the level-downgraded `confidence_tier`.

### T1.4 Output B — Cohort SQL rows

SQL schema at
[cohort_bands_table.py:32-58](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L32):

```sql
CREATE TABLE IF NOT EXISTS post_intake_cohort_bands (
  draft_id VARCHAR(64) NOT NULL,
  planning_run_id VARCHAR(64) NOT NULL,
  section VARCHAR(64) NOT NULL,
  lever_id VARCHAR(128) NOT NULL,
  metric_key VARCHAR(128) NOT NULL,
  metric_column VARCHAR(64) NULL,
  benchmark_min DECIMAL(18,6) NULL,
  benchmark_target DECIMAL(18,6) NULL,
  benchmark_max DECIMAL(18,6) NULL,
  robust_min DECIMAL(18,6) NULL,
  robust_max DECIMAL(18,6) NULL,
  naics_level_used TINYINT NULL,
  naics_prefix_used VARCHAR(8) NULL,
  cohort_size INT NULL,
  firm_count INT NULL,
  confidence_tier VARCHAR(16) NULL,
  cohort_table VARCHAR(16) NULL,
  data_source VARCHAR(64) NULL,
  resolved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (draft_id, planning_run_id, section, lever_id, metric_key),
  ...
)
```

**18 columns total** (17 data + 1 auto-stamp `resolved_at`).
Primary key: `(draft_id, planning_run_id, section, lever_id, metric_key)`.

The INSERT statement at
[cohort_bands_table.py:209-244](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L209)
populates the 18 columns from a `CohortBandResult` dataclass
return.

**`cohort_query` Phantom (v1 §D-4, F-bug-1, CONFIRMED RESIDUAL):**
the `CohortBandResult` dataclass at
[cohort_band_resolver.py:150-176](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L150)
includes a `cohort_query: Dict[str, Any]` field, but it's
**NOT in the SQL INSERT column list** — silently dropped at
materialization. Audit trail cannot reconstruct which
revenue/stage/date windows were used.

### T1.5 Output C — In-memory `get_bands` view

`get_bands(conn, *, draft_id, planning_run_id, section)` at
[cohort_bands_table.py:344-392](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L344)
returns:

```python
{
  "section": str,
  "draft_id": str,
  "planning_run_id": str,
  "count": int,
  "bands": {
    "<lever_id>": {
      "metric_key": str,
      "metric_column": str|None,
      "benchmark_min": float|None,
      "benchmark_target": float|None,
      "benchmark_max": float|None,
      "robust_min": float|None,
      "robust_max": float|None,
      "confidence_tier": str|None,
      "cohort_size": int|None,
      "firm_count": int|None,
      "naics_level_used": int|None,
      "cohort_table": str|None,
    },
    ...
  }
}
```

**11 fields per lever_id band** in the in-memory view. **6
fields are dropped vs the SQL row**: `naics_prefix_used`,
`data_source`, `resolved_at` are stripped silently in the SQL
→ in-memory conversion. NEW STRUCTURAL per §T8 Div-4.

### T1.6 Output D — Population summary

`populate_cohort_bands_for_run` returns
[cohort_bands_table.py:155-162](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L155):

```python
Dict[str, Dict[str, int]]
# e.g. {"drivers": {"resolved": 5, "skipped": 0},
#       "balance_sheet": {"resolved": 12, "skipped": 1},
#       "stage_ramp": {"resolved": 8, "skipped": 0}}
```

Just resolved/skipped counts per section. Stamped into
`sequence_trace["cohort_bands_populated"]` at
[runner.py:582](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L582)
and logged only. No structural downstream consumer.

### T1.7 Caller (single producer-side call site)

`populate_cohort_bands_for_run` is called from a SINGLE site
at [runner.py:569-581](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L569),
wrapped in a soft `try/except` (the `# Soft failure` comment at
runner.py:557 notes this is a new audit sink). T7 elaborates.

The cascade resolver (`_payload_from_row` via its public callers)
is invoked from `_attach_seed_provenance` and
`driver_movement_assembler._resolve_naics_band` — at the
CONSUMER side, not as a separate producer event. So Shape A is
resolved on-demand at consumer-side; Shape B+C+D are persisted
at runner.py:569 producer-side.

---

## T2. Boundary surface — what's resolved

Per T1 there are 4 distinct shapes; per T2 enumerate each
shape's fields with Tier classification.

### T2.1 Shape A — Cascade resolver payload (13 fields per metric)

| # | Field | Type | Source | Required? | Tier |
|---|---|---|---|---|---|
| 1 | `metric_key` | str | input arg passed through | required | A |
| 2 | `benchmark_min` | float (decimal-coerced) | SQL row | required (None possible if row has NULL) | A |
| 3 | `benchmark_target` | float | SQL row | required | A |
| 4 | `benchmark_max` | float | SQL row | required | A |
| 5 | `naics_code_used` | str | SQL row | required | A |
| 6 | `naics_level_used` | int (0/2/3/4/5/6) | derived from cascade walk | required | A |
| 7 | `data_source` | str | SQL row | required | A |
| 8 | `source_year` | int|None | SQL row | Optional | A |
| 9 | `sample_size` | int|None | SQL row | Optional | A |
| 10 | `confidence_tier` | str (downgraded) | derived | required | A |
| 11 | `raw_confidence_tier` | str (un-downgraded) | SQL row | required | A |
| 12 | `trust_flag` | str | derived from cascade walk | required | A |
| 13 | `fallback_chain_attempted` | List[str] (diagnostic) | derived | Optional (diagnostic per v1 §D-3) | C (diagnostic) |

`confidence_tier` is a closed set per the SQL FIELD ordering at
lookup.py:208-210: `{"high", "medium", "low", "generic_default"}`.
`trust_flag` is a closed set per v1 §A:
`{"naics_6_direct", "naics_5_fallback", "naics_4_fallback",
"naics_3_fallback", "naics_2_fallback", "no_coverage"}`. Both
are `Literal[...]` candidates.

### T2.2 Shape B — Cohort SQL row (17 data columns + resolved_at)

| # | Column | SQL type | Required? |
|---|---|---|---|
| 1 | `draft_id` | VARCHAR(64) NOT NULL | required (PK) |
| 2 | `planning_run_id` | VARCHAR(64) NOT NULL | required (PK) |
| 3 | `section` | VARCHAR(64) NOT NULL | required (PK) |
| 4 | `lever_id` | VARCHAR(128) NOT NULL | required (PK) |
| 5 | `metric_key` | VARCHAR(128) NOT NULL | required (PK) |
| 6 | `metric_column` | VARCHAR(64) NULL | Optional |
| 7 | `benchmark_min` | DECIMAL(18,6) NULL | Optional |
| 8 | `benchmark_target` | DECIMAL(18,6) NULL | Optional |
| 9 | `benchmark_max` | DECIMAL(18,6) NULL | Optional |
| 10 | `robust_min` | DECIMAL(18,6) NULL | Optional (cohort-specific; absent on cascade fallback per v1 §E) |
| 11 | `robust_max` | DECIMAL(18,6) NULL | Optional |
| 12 | `naics_level_used` | TINYINT NULL | Optional |
| 13 | `naics_prefix_used` | VARCHAR(8) NULL | Optional |
| 14 | `cohort_size` | INT NULL | Optional |
| 15 | `firm_count` | INT NULL | Optional |
| 16 | `confidence_tier` | VARCHAR(16) NULL | Optional |
| 17 | `cohort_table` | VARCHAR(16) NULL (`"edgar"`/`"alpha"`) | Optional |
| 18 | `data_source` | VARCHAR(64) NULL | Optional |
| 19 | `resolved_at` | DATETIME (auto) | required (server-stamped) |

`cohort_table` is a closed set per CohortBandResult.cohort_table
default (`"cohort_alternating"`) — but the field's INSERT value
comes from `result.cohort_table` which the resolver sets to
`"edgar"` or `"alpha"`. Literal[...] candidate.

### T2.3 Shape C — In-memory `get_bands` view

11 fields per lever_id band (per T1.5 listing). 5 fields
dropped from Shape B: `metric_column` is included (1 of the
6); `naics_prefix_used`, `data_source` are dropped. Plus the
3 PK fields (`draft_id`, `planning_run_id`, `section`) are
hoisted to top-level dict keys; `lever_id` becomes the inner
dict key. Plus `resolved_at` is dropped.

### T2.4 Shape D — Population summary

`Dict[str, Dict[str, int]]` keyed by section name; values are
`{"resolved": int, "skipped": int}`. Diagnostic-only. Tier C.

---

## T3. Consumer-side per shape

### T3.1 Shape A consumers — Cascade resolver payload

| Consumer | File:line | What it reads |
|---|---|---|
| `_attach_seed_provenance` | [finmo_bridge.py:339-353](../../python/client_intake_and_finmo/finmo_bridge.py#L339) | `trust_flag` (guard), then full payload via `baseline_seed_provenance` for stamping `model_input_row.seed_provenance_json[metric_key]` |
| `driver_movement_assembler._resolve_naics_band` | [driver_movement_assembler.py:97-102](../../python/client_intake_and_finmo/post_intake_solver/driver_movement_assembler.py#L97) | per-lever cascade payload for envelope assembly |

Both consumers structure-read Shape A. No phantom-read. The
`fallback_chain_attempted` field is documented diagnostic-only
(v1 §D-3) — present in the payload but no computational reader.

### T3.2 Shape B+C consumers — Cohort bands

Per v1 §C: every amalgamated tool's `_echo_*_bands` helper
(`set_drivers`, `set_stage_ramp_contract`,
`set_capex_rd_balance_seed`, `set_payroll_schedule`),
`mirror.build_mirror` at
[mirror.py:140-160](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L140),
and `evaluate_plan._margin_distance_from_bands` at
[evaluate_plan.py:189-220](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L189).

All consumers go through `get_bands` (Shape C) — the SQL row
shape (B) is the persistence representation but the consumer
surface is the nested in-memory shape.

`robust_min`/`robust_max` are read by tools but are
**cohort-only** — if a future cascade fallback writes Shape B
rows, those columns will be NULL and consumers will fall back
to `benchmark_min`/`benchmark_max` (v1 §E). NEW STRUCTURAL flag
candidate.

### T3.3 Shape D consumers — Population summary

Logged only at runner.py:582:
`sequence_trace["cohort_bands_populated"] = _bands_summary`. No
structural consumer. Tier C diagnostic.

---

## T4. Composition with Contract 5 (IntakeDraftContract)

### T4.1 NO wrapping — Contract 6 is INPUT-derivative, not OUTPUT-wrapping

Contract 5 (IntakeDraftContract) types the 8 SQL JSON columns
on `intake_consult_drafts`. Contract 6's producer
(`populate_cohort_bands_for_run`) does NOT receive an
IntakeDraftContract — it receives a 4-field `business_profile`
dict EXTRACTED from Contract 5's fields:

- `business_profile.naics_6` extracted from
  `Contract5.operating_model_json.business_naics_6` via
  digits-only strip at
  [runner.py:561-564](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L561).
- `business_profile.target_annual_revenue` extracted from
  `Contract5.financials_year1_json.company_revenue_total_year1`.
- `business_profile.stage` extracted from
  `Contract5.operating_model_json.business_stage`.
- `business_profile.business_model` always None (placeholder).

The intake JSON columns are NOT carried inside the resolved
baseline payload. Consumers of Shape A/B/C don't see intake
fields at all — they see the cohort-resolved values + metadata.

**Spec F0 disposition: NO composition with Contract 5.** Contract
6 stands alone. The 4-field `business_profile` input is the
INPUT surface of Boundary 2 (could be its own sub-contract) but
the OUTPUT shapes (A/B/C/D) are the boundary-defining payloads.

### T4.2 Cross-contract reference (R-residual retrofit)

After Contract 5b/c/d follow-ups type the OpenAI-schema-enforced
intake shapes, `business_profile` could compose
`IntakeOperatingModelJsonContract.business_naics_6` + 
`IntakeFinancialsYear1JsonContract.company_revenue_total_year1` +
`IntakeOperatingModelJsonContract.business_stage`. R-residual.

---

## T5. NAICS-6 fallback mechanism — "by design"

### T5.1 Cascade walk pattern

`_lookup_naics_metric` (callers of `_payload_from_row`) walks
the NAICS hierarchy. Per the `_downgrade_confidence` function at
[lookup.py:216-229](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L216):

```python
def _downgrade_confidence(raw_confidence: str, *, level_used: int) -> str:
  raw = (raw_confidence or "").strip().lower() or "generic_default"
  if level_used == 6:    return raw
  if level_used in (5, 4):  return "medium" if _CONFIDENCE_RANK.get(raw, 0) >= 3 else raw  # Cap at medium
  if level_used in (3, 2):  return "low" if _CONFIDENCE_RANK.get(raw, 0) >= 2 else raw     # Cap at low
  if level_used == 0:    return "generic_default"
  return raw
```

So the cascade attempts NAICS levels 6 → 5 → 4 → 3 → 2 → 0
(generic_default). At each level, confidence is automatically
DOWNGRADED to reflect lookup-fidelity. Level 0 = "no NAICS
match anywhere; falling back to industry-universal default".

### T5.2 `trust_flag` enumeration

Per v1 §A and consumer-side reads at finmo_bridge.py:
- `"naics_6_direct"` (exact match)
- `"naics_5_fallback"`, `"naics_4_fallback"`, `"naics_3_fallback"`, `"naics_2_fallback"`
- `"no_coverage"` (universal/generic_default)

6 values. **Literal[...] candidate per PSL3 (NAICS-6 fallback
typing).** Pin via paired typo-rejection test like Contract 1
and 3.

### T5.3 `naics_level_used` integer values

Closed set: `{6, 5, 4, 3, 2, 0}`. NOT contiguous (no level 1).
Contract candidate: `Literal[0, 2, 3, 4, 5, 6]` or
`int = Field(ge=0, le=6)` with a custom validator excluding 1.

### T5.4 `confidence_tier` enumeration

Per `_CONFIDENCE_RANK` (referenced but not shown in this trace
window):
`{"high", "medium", "low", "generic_default"}`. Literal[...]
candidate. Per v1 §E: "Confidence-tier gates differ between
cascade and cohort; same vocabulary, different meaning."
Whichever the spec types must reflect the SHARED vocabulary, not
just the cascade or just the cohort version.

---

## T6. Silent fallback / defensive patterns

### T6.1 Soft try/except wrapping populate_cohort_bands_for_run

At
[runner.py:556-583](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L556),
the entire `populate_cohort_bands_for_run` call is wrapped in
`try/except Exception` with the comment "Soft failure: this is
a new audit sink that no caller consumes yet". On failure,
`sequence_trace["cohort_bands_populated"] = {"error": repr(...)}`
and execution continues.

**v1 §F-2 bug:** the populator has an INTERNAL `raise_fail_fast`
at
[cohort_bands_table.py:265+](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L265)
that triggers `FAIL_COHORT_BANDS_MISSING` when zero rows are
resolved. This is INSIDE the try/except — currently swallowed.
v1 frames it as "uncertain — may be by design, but if so the
contract needs to encode that precondition." Flag candidate.

### T6.2 NAICS normalizer doesn't validate length

`_naics_6_from_ops` at
[finmo_bridge.py:332-336](../../python/client_intake_and_finmo/finmo_bridge.py#L332):

```python
def _naics_6_from_ops(ops_json: Any) -> Optional[str]:
  if not isinstance(ops_json, dict):
    return None
  digits = re.sub(r"[^0-9]", "", str(ops_json.get("business_naics_6") or "").strip())
  return digits or None
```

Strips all non-digits and returns whatever length results.
Garbage input like `"ABC"` → `""` → returned as None → treated
as no_coverage silently. v1 §F-3 known bug. **Contract candidate
for tightening** — `business_profile.naics_6` could type as
`str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")`
or as `Optional[str]` with the constraint when present.

### T6.3 Cohort row cache silent-None

Per v1 §F-4: `resolve_cohort_band` returns `None` silently if a
cohort table is missing a column the caller expects. The cache
is keyed by query filters, not by metric. Caller may not
realize a different lever in the same cohort succeeded while
this one fell back.

Not directly a contract concern (this is internal to the
resolver, not at the boundary surface) — but if `populate_cohort_bands_for_run`
returns `{"drivers": {"resolved": 5, "skipped": 4}}` with 4
skipped due to this silent-None, the contract could surface
this via a structured `skipped_metrics: List[...]` field
instead of just a count.

### T6.4 No benchmark monotonicity invariant

Per v1 §F-5: no validation that
`benchmark_min ≤ benchmark_target ≤ benchmark_max` on INSERT.
Mathematically guaranteed by percentile interpolation today,
but no defensive assertion. **Contract candidate** — add as a
`@model_validator(mode="after")` on the cohort-row sub-contract.

### T6.5 cohort_query silently dropped

Per v1 §D-4 / §F-1: `CohortBandResult.cohort_query` exists on
the dataclass but isn't in the SQL INSERT column list. Audit
trail cannot reconstruct which revenue/stage/date windows were
used. **Contract decision** — type as a required field on
the row contract (forces persistence), or as Optional matching
current reality?

### T6.6 Confidence-tier dual-meaning (NAICS-level vs firm-count)

Per v1 §E: cascade uses `_downgrade_confidence(level_used)`;
cohort uses `_confidence_tier_for_cohort_size(firm_count)` at
cohort_band_resolver.py:286. Same vocabulary (`high/medium/low/
generic_default`), different semantic. A field typed as
`Literal[...]` accepts the values from both producers but
doesn't distinguish them.

---

## T7. Producer-side gate feasibility

### T7.1 Two distinct producer-side gate placements

Producer surface for Contract 6 has TWO call sites:

1. **Cohort populator gate** — single call site at
   [runner.py:569-581](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L569).
   Soft-wrapped today. A producer-side gate would land
   immediately after the populator returns. Single point.

2. **Cascade resolver gate** — invoked from consumer-side
   (`_attach_seed_provenance` calls the resolver on-demand per
   metric). A producer-side gate at the resolver level would
   need to land inside `_payload_from_row` itself OR at each
   public caller.

**Spec F-PRODUCER-GATE recommendation candidate:**
- For Shape B+C+D (cohort): SHIP producer-side gate at
  runner.py:569 (Contract 3 single-producer pattern).
- For Shape A (cascade): SKIP producer-side gate (multiple
  consumer-driven call sites; Contract 2 R8 pattern).

### T7.2 Two consumer-side gate placements

Consumer-side gates needed at:

1. **Cascade Shape A consumers** — `_attach_seed_provenance`
   (finmo_bridge.py:339) and
   `driver_movement_assembler._resolve_naics_band`
   (driver_movement_assembler.py:97). Each gate validates Shape
   A before consumption. Two sites.

2. **Cohort Shape C consumer** — `get_bands` return value is
   consumed by amalgamated tools + mirror.build_mirror +
   evaluate_plan. Either gate inside `get_bands` (single point)
   OR at each amalgamated-tool consumer (4+ sites).

**Spec recommendation candidate:** gate inside `get_bands`
(single-point) is cleanest; covers all 4+ amalgamated-tool
consumers.

---

## T8. Divergences from v2 inventory

Taxonomy: **NEW SUBSTANTIVE / NEW STRUCTURAL / CONFIRMED
RESIDUAL / CONFIRMED CLOSED**. **Multi-residual surface
expected — this is the "multiple small residuals" the handoff
flagged.**

### Div-1. v1 §A understates cascade resolver field count (10 → 13)

NEW STRUCTURAL. v1's `_payload_from_row` listing has 10 fields;
actual at lookup.py:237-256 has 13. v1 missed `source_year`,
`sample_size`, `raw_confidence_tier`. Spec must type all 13.

### Div-2. v1 omits `metric_column` from Shape C `get_bands` shape

NEW STRUCTURAL. v1 §A lists the Shape C envelope but doesn't
enumerate the inner band fields exhaustively. Trace finds 11
fields per band (metric_key, metric_column, benchmark_min,
benchmark_target, benchmark_max, robust_min, robust_max,
confidence_tier, cohort_size, firm_count, naics_level_used,
cohort_table).

### Div-3. Shape C drops 6 SQL columns silently

NEW STRUCTURAL. SQL has 18 columns; in-memory has 11.
`naics_prefix_used`, `data_source` are dropped at the SQL → 
in-memory translation in `get_bands`. Plus the 3 PK fields are
hoisted, plus `resolved_at` is dropped. Worth surfacing —
amalgamated tools cannot access `naics_prefix_used` or
`data_source` from `get_bands` output even though SQL persists
them.

### Div-4. `business_profile.business_model` always None — CONFIRMED RESIDUAL

v1 §D-1 noted this. Trace confirms at runner.py:577 verbatim
(`"business_model": None`). Placeholder reserved for future use.
F-BUSINESS-MODEL flag candidate: type as `Optional[None]` to
explicitly pin the always-None state, OR type as
`Optional[str]` to permit future enabling without a contract
amendment?

### Div-5. Cohort sections `capex_rd` and `payroll` defined-but-not-populated — CONFIRMED RESIDUAL

v1 §D-2. Trace confirms: `_SECTION_LEVERS` at cohort_bands_table.py
defines drivers/balance_sheet/stage_ramp but capex_rd + payroll
aren't yet populated. `set_payroll_schedule._resolve_bounds`
already calls `get_bands(conn, section="payroll")` and softly
handles empty section. F-COHORT-SECTIONS flag candidate.

### Div-6. `fallback_chain_attempted` diagnostic-only — CONFIRMED RESIDUAL

v1 §D-3. F-FALLBACK-CHAIN flag candidate: include in contract
or exclude (R-residual)?

### Div-7. `cohort_query` silent drop on INSERT — CONFIRMED RESIDUAL

v1 §D-4 / §F-1. F-COHORT-QUERY flag candidate.

### Div-8. NAICS field name variation across sources — CONFIRMED RESIDUAL

v1 §E. F-NAICS-FIELD-NAME flag candidate: pin a single canonical
name in the contract, or accept multiple aliases?

### Div-9. Shape B vs Shape C drift — CONFIRMED RESIDUAL

v1 §E ("Cohort bands shape is row-flat in SQL but nested
in-memory via get_bands"). F-SHAPE-B-C-DRIFT flag candidate:
type Shape B and Shape C as separate sub-contracts (current
reality), or unify into a single canonical shape?

### Div-10. Confidence-tier dual-meaning — CONFIRMED RESIDUAL

v1 §E. F-CONFIDENCE-TIER flag candidate: same vocabulary across
cascade and cohort, different computation. Type as a single
`Literal[...]` (accepts both producers) or split into two
distinct typed fields?

### Div-11. `robust_min`/`robust_max` cohort-only — CONFIRMED RESIDUAL

v1 §E. Optional in Shape B; cohort writes them, future cascade
fallback wouldn't. F-ROBUST-FALLBACK flag candidate.

### Div-12. `FAIL_COHORT_BANDS_MISSING` with no cascade fallback — CONFIRMED RESIDUAL

v1 §F-2. Populator raise_fail_fast inside the soft try/except —
swallowed today. F-FAIL-COHORT flag candidate: encode the
precondition (require ≥1 resolved band per section) in the
contract?

### Div-13. NAICS normalizer length-blind — CONFIRMED RESIDUAL

v1 §F-3. F-NAICS-LENGTH flag candidate: type
`business_profile.naics_6` with `Field(min_length=6, max_length=6,
pattern=r"^[0-9]{6}$")` to surface garbage inputs at the contract
gate instead of silently treating them as no_coverage?

### Div-14. Cohort row cache silent-None — CONFIRMED RESIDUAL

v1 §F-4. Internal to resolver — not directly contract scope.

### Div-15. No benchmark monotonicity invariant — CONFIRMED RESIDUAL

v1 §F-5. F-BENCHMARK-MONOTONICITY flag candidate: add
`@model_validator(mode="after")` to cohort row sub-contract.

### Div-16. Multi-shape boundary surface — NEW STRUCTURAL (THE headline)

Trace finds 4 distinct shapes at the boundary (A/B/C/D). v1
inventory treats them implicitly as one boundary without
making the multi-shape structure explicit. F0 (composition
scope) decides: one Contract 6 with 4 sub-contracts, or 4
separate contracts (6a/6b/6c/6d)?

---

## Open questions / flags for the spec doc

Numbered for the spec doc's §7. Same format as Contracts 1-5.
Each flag: spec recommends + alternatives + reasoning. **16+
flag candidates surfaced — matches the handoff doc's
"multi-residual" framing.**

### F0 — Single contract vs split into 4

(a) **(Recommended) Single Contract 6 with 4 typed sub-contracts**
(`NaicsCascadePayloadContract`, `CohortBandRowContract`,
`CohortBandsInMemoryViewContract`, `CohortPopulationSummaryContract`).
Keeps the boundary unified for type discovery; mirrors Contract
2's pattern (one workbook payload contract, multiple sub-shapes).

(b) Four separate contracts (Contract 6a/6b/6c/6d). Each gets
its own focused trace + spec. Higher overhead; longer total
timeline.

### F1 — Composition with Contract 5

(a) **(Recommended) NO composition.** Per T4. Spec doc decides;
trace confirms NO wrapping in production.

### F2 — `business_profile.business_model` always-None typing

(a) `Optional[None]` (explicit always-None pin).
(b) **(Recommended) `Optional[str] = None`** — permits future
enabling without contract amendment.

### F3 — Cohort sections `capex_rd`/`payroll` definition

(a) **(Recommended) Allow "section present, no rows" as valid**
— Shape D summary may have these sections at `{"resolved": 0,
"skipped": 0}` or absent entirely. Shape C `get_bands(section="payroll")`
returns `{"section": "payroll", "count": 0, "bands": {}}`.

### F4 — `fallback_chain_attempted` inclusion

(a) Include in Shape A contract (matches production).
(b) **(Recommended) Include but mark as diagnostic** — type as
`List[str]` Optional/required. Future Contract 6b refactor
could move it to a separate diagnostic field.

### F5 — `cohort_query` field inclusion

(a) **(Recommended) Type as Optional[Dict] on `CohortBandRowContract`**
matching current SQL-INSERT reality (NULL because the column
doesn't exist in the table; the dataclass holds it in-memory
only). Closing the audit-trail gap is R-residual.

(b) Type as required AND add the SQL column. Out of scope for
Contract 6 — that's a producer-side fix.

### F6 — NAICS field name variation pinning

(a) **(Recommended) Pin canonical to `naics_6` in Contract 6**
(matches `business_profile.naics_6`). Document the upstream
aliases as known producer-side normalization scope (Contract 5b
runs ops_json normalization).

### F7 — Shape B vs Shape C separate sub-contracts

(a) **(Recommended) Two separate sub-contracts.** Matches
production reality — they're distinct shapes with distinct
consumers.

### F8 — `confidence_tier` Literal pinning

(a) **(Recommended) Single `Literal["high", "medium", "low",
"generic_default"]` field.** Type the vocabulary; let the
producer (cascade or cohort) compute the value. Same pattern
Contract 3 used for plan_confidence.

### F9 — `robust_min`/`robust_max` Optional handling

(a) **(Recommended) Optional[float] in Shape B**, default None.
Document in Shape B contract module docstring that they're
cohort-only — a future cascade fallback row would have NULL
values and consumers (Shape C `get_bands`) currently preserve
None.

### F10 — `FAIL_COHORT_BANDS_MISSING` precondition

(a) **(Recommended) Encode in Shape D contract**: add a
`@model_validator` requiring `sum(s["resolved"] for s in
summary.values()) >= 1`. Surfaces the v1 §F-2 precondition that
today is swallowed by the soft try/except.

(b) Skip — leave as runtime fail-fast inside the populator.

### F11 — NAICS-6 length validation

(a) **(Recommended) Type `business_profile.naics_6` as
`Optional[str] = Field(default=None, pattern=r"^[0-9]{6}$")`**.
Surfaces v1 §F-3 garbage inputs at the contract gate.

### F12 — Benchmark monotonicity invariant

(a) **(Recommended) Add `@model_validator(mode="after")` on
`CohortBandRowContract`** requiring
`benchmark_min <= benchmark_target <= benchmark_max` (when all
3 are non-None). Closes v1 §F-5 defensively.

### F13 — `trust_flag` + `naics_level_used` Literal pinning

(a) **(Recommended) Pin both via Literal[...]**. `trust_flag`
6 values; `naics_level_used` per the cascade walk 6/5/4/3/2/0
(no level 1). PSL3 explicitly recommends this for
NAICS-fallback typing.

### F14 — Producer-side gate

(a) **(Recommended) SHIP at runner.py:569** (post-populator)
for Shape B+C+D. **SKIP at cascade resolver** (Shape A
on-demand consumer-side).

### F15 — Consumer-side gate placement

(a) **(Recommended) Inside `get_bands` for Shape C** (single
point; covers all 4+ amalgamated-tool consumers).
**Inside `_attach_seed_provenance` + `_resolve_naics_band` for
Shape A** (two specific consumer sites).

### F16 — Diagnostic-emission invariant test

(a) **(Recommended) Add `ContractSixEmits*PhaseCodeTest` +
cross-contamination check per Contracts 2-5 pattern.** Lockstep
PhaseCode count 18 → 19.

### F17 — Adjustment B carry-over

(a) **(Recommended) Re-use Contract 4/5 pattern verbatim.** Same
intake_consult.py:7377 generic catch. The gate at runner.py:569
runs inside `prepare_initial_grid_for_draft`, downstream of the
Contract 5 gate at runner.py:189 — same call chain protects
both.

### F18 — extra policy

(a) **(Recommended) `extra="forbid"` on top-level
IndustryBaselineResolvedContract; `extra="ignore"` on
sub-contracts and rows.** Established pattern.

---

## Lessons baked in for Contract 6 spec drafting

- **Trace before spec.** The "multi-shape boundary surface"
  finding (T1, Headline #1) and the 3 NEW STRUCTURAL drifts
  from v1 (resolver field count, get_bands field count, Shape
  B/C asymmetry) would have been costly assumption errors in
  the spec. Multi-shape boundary changes the structure of the
  contract module; this is the Contract 4 Surface-A/B catch
  equivalent for Contract 6.
- **Match production vocabulary verbatim.** All 13 cascade
  fields + 17 cohort SQL columns + 11 in-memory get_bands fields
  + 6 trust_flag values + 4 confidence_tier values + 6 NAICS
  level integers lifted from source.
- **Constraints from production reality.** F11 NAICS length +
  F12 monotonicity invariant tighten defensively where
  production already produces compliant values. F2 + F4 + F5
  reflect production as-is without imposing new requirements
  upstream.
- **Don't loosen safety checks.** F10 (FAIL_COHORT_BANDS
  precondition) + F11 (NAICS length) tighten; F4/F5 preserve
  production reality opaquely.
- **`extra="forbid"` only on top-level.** F18.
- **Compose where downstream contracts already exist.** F1: NO
  composition with Contract 5 per T4 — confirmed by source. R-
  residual retrofit when Contract 5b/c/d sub-contracts ship.
- **Adjustment B is recurring.** F17 confirms same pattern.
- **Diagnostic-emission invariant matters.** F16.
- **Surface multiple residuals as multiple flags, not one
  mega-flag.** Per PSL9 — 18 flags surfaced (F0-F18 minus the
  F1 placeholder = 18 substantive decisions), matching the
  handoff doc's "multi-residual" framing.
