# P3.40 Contract 3 — SolverInputContract — Pre-spec trace

**Boundary:** 5 (MODEL_INPUT → SOLVER, target_seeking).
**Status:** pre-spec trace. Holds for review before the spec doc is drafted.
**Companion to:** [p3_40_contract_3_solver_input_spec.md](./p3_40_contract_3_solver_input_spec.md) (not yet written).
**v2 inventory baseline:** [p3_40_pipeline_data_flow_inventory_v2.md §Boundary 5](./p3_40_pipeline_data_flow_inventory_v2.md#boundary-5-model_input--solver-target_seeking) (lines 452-526).

This document captures the trace-before-spec work for Contract 3.
Same discipline as Contracts 1 and 2: enumerate the producer +
consumer call paths from production code, surface divergences from
the v2 inventory, and call out anything that would change the
shape of the contract before the spec doc is written.

---

## T1. Entry point + invocation

### T1.1 Public solver entry

`run_target_seeking_orchestrated_system_run` at
[python/client_intake_and_finmo/post_intake_solver/orchestrator.py:1028](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1028)

Signature (full, verbatim from the source):

```python
def run_target_seeking_orchestrated_system_run(
  *,
  conn,
  draft_id: str,
  planning_run_id: Optional[str],
  business_facts: Dict[str, Any],
  planning_context_summary_json: Optional[Dict[str, Any]],
  ops_json: Dict[str, Any],
  target_market_json: Dict[str, Any],
  people_json: Dict[str, Any],
  financials_json: Dict[str, Any],
  financials_year1_json: Dict[str, Any],
  fulfillment_json: Dict[str, Any],
  marketing_model_json: Dict[str, Any],
  planning_mode: str,
  planning_mode_reason: str,
  planning_result: Dict[str, Any],
  grid_application_summary: Optional[Dict[str, Any]],
  catalog_source_model_input_json: Dict[str, Any],
  applied_model_input_json: Dict[str, Any],
  applied_finmo_json: Dict[str, Any],
  stage_ramp_contract: Optional[Dict[str, Any]] = None,
  payroll_headcount: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
```

**22 keyword-only parameters.** 3 are runtime context (`conn`,
`draft_id`, `planning_run_id`). 19 are intake/planning data
payloads — that's the v2 inventory's "19" count.

### T1.2 Call chain from API → solver entry

Two-hop chain at the API layer:

1. [intake_consult.py:7103](../../python/api_handlers/intake_consult.py#L7103) — `_run_unified_post_grid_system_run(...)` is called with kwargs unpacked from the dict returned by `prepare_initial_grid_for_draft`.
2. [intake_consult.py:6962-7036](../../python/api_handlers/intake_consult.py#L6962) — `_run_unified_post_grid_system_run` is a thin wrapper that calls `run_target_seeking_orchestrated_system_run` with the same kwargs, except `payroll_headcount=copy.deepcopy(payroll_headcount or {})`.

Both hops deep-copy every dict before forwarding. There is no
intermediate transformation — the orchestrator entry receives the
shape `prepare_initial_grid_for_draft` returned, modulo deep copies.

### T1.3 Bundle producer

`prepare_initial_grid_for_draft` at
[python/client_intake_and_finmo/post_intake_initial_grid/runner.py:30+](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30)
returns a single dict whose keys form the bulk of the orchestrator
entry's kwargs. The return statement at
[runner.py:1830-1850](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1830)
materialises the 19 data params (plus two return-only fields
`post_intake_process_sequence_trace` and `shared_context` that the
solver does NOT consume).

This makes the producer / consumer asymmetric vs Contract 2:

- Contract 2's producer surface was 5 different writers in
  different modules — single producer-side gate not feasible.
- Contract 3's producer surface is ONE function that returns ONE
  dict — single producer-side gate at the bundle return is
  feasible.

This is the basis for the **producer-side enforcement flag**
deferred to the spec (§7 below).

### T1.4 Receives single bundle vs separate args?

**Separate kwargs.** The orchestrator entry has 22 explicit
keyword params; intake_consult.py:7103 unpacks
`initial_grid_state[...]` into them. There is no `SolverInput`
dataclass between producer and consumer today — the contract
would be the FIRST typed unit at this boundary.

This is structurally different from Contract 2's
`DraftWorkbookData` (which already existed as a dataclass and only
needed `to_contract` / `from_contract` adapters). For Contract 3
the adapter step has two shapes to choose between:

1. **No dataclass.** `SolverInputContract.from_initial_grid_state(...)` classmethod that takes the raw dict and returns the contract; `validate_solver_input_at_boundary(payload, side=...)` enforces.
2. **Introduce a `SolverInputBundle` dataclass** that mirrors `DraftWorkbookData` so producer + consumer share a typed handle.

Flag for the spec (§7 below): which adapter shape Nick prefers.

---

## T2. Parameter surface

### T2.1 Full parameter roster with consumption tier

19 data params, classified by who actually reads them. Citations
in the form `file:line` are file-relative to the repo root.

| # | Param | Type today | Required-or-optional | Consumed by orchestrator body? | Consumed by cascade? | Consumed by post-cascade completion? | Tier |
|---|---|---|---|---|---|---|---|
| 1 | `business_facts` | `Dict[str, Any]` | required | YES (`compute_adaptive_policy` orchestrator.py:1156-1162, `_bf_template` 1188-1195, `_build_finmo_callable` closure 1361) | indirect via inner_runner_kwargs (not unpacked) | NO | **A. consumed-direct** |
| 2 | `ops_json` | `Dict[str, Any]` | required | YES (`compute_adaptive_policy` 1158, `authoritative_annual_revenue` 1180, `verify_structural_feasibility` 1238, `restore_feasibility` 1261, `_build_finmo_callable` closure 1362, NAICS extraction 1206 & 1597); **mutated in place at 1273** | YES via `inner_runner_kwargs.get("ops_json")` (adaptation_cascade.py:818, 846) | NO | **A. consumed-direct + mutated** |
| 3 | `target_market_json` | `Dict[str, Any]` | required | NO | NO (packed into inner_runner_kwargs at 1571, never unpacked by cascade) | NO (signature has it at 1782, body never reads) | **F. TRULY PHANTOM — READER_MISSING everywhere** |
| 4 | `people_json` | `Dict[str, Any]` | required | indirect via `_build_finmo_callable` closure (1363) | NO | NO | **B. closure-only** |
| 5 | `financials_json` | `Dict[str, Any]` | required | YES (`compute_adaptive_policy` 1159, `authoritative_annual_revenue` 1183, `verify_structural_feasibility` 1239, `restore_feasibility` 1262, `_build_finmo_callable` closure 1364) | YES (cascade.py:819, 847) | NO | **A. consumed-direct** |
| 6 | `financials_year1_json` | `Dict[str, Any]` | required | YES (`compute_adaptive_policy` 1160, `authoritative_annual_revenue` 1182, `verify_structural_feasibility` 1240, `restore_feasibility` 1263, `_build_finmo_callable` closure 1365) | YES (cascade.py:820, 848) | NO | **A. consumed-direct** |
| 7 | `fulfillment_json` | `Dict[str, Any]` | required | indirect via `_build_finmo_callable` closure (1366) | NO | NO | **B. closure-only** |
| 8 | `marketing_model_json` | `Dict[str, Any]` | required | indirect via `_build_finmo_callable` closure (1367) | NO | NO | **B. closure-only** |
| 9 | `planning_mode` | `str` | required | YES (`compute_adaptive_policy` 1161, mode-unknown fail-fast 1100-1115, persist 1849) | YES via `original_planning_mode=planning_mode` at cascade entry (1623) | YES (signature 1789, persist 1849) | **A. consumed-direct** |
| 10 | `planning_mode_reason` | `str` | required | YES (`compute_adaptive_policy` 1162, persist 1850) | YES (`original_planning_mode_reason=` 1624) | YES (signature 1790, persist 1850) | **A. consumed-direct** |
| 11 | `planning_result` | `Dict[str, Any]` | required | NO | NO (packed at 1579, never unpacked) | NO | **F. TRULY PHANTOM** |
| 12 | `grid_application_summary` | `Optional[Dict[str, Any]]` | optional (None default at orchestrator entry; required at runner.py producer) | YES via persist site (3621: `copy.deepcopy(grid_application_summary or {})` → `_persist_unified_convergence_state`) | NO (packed at 1580, cascade never unpacks) | YES (signature 1791, persist 1842) | **C. persist-only — cascade-phantom** |
| 13 | `catalog_source_model_input_json` | `Dict[str, Any]` | required | NO | NO (packed at 1581, never unpacked) | NO | **F. TRULY PHANTOM** |
| 14 | `applied_model_input_json` | `Dict[str, Any]` | required | YES (`_ensure_solver_inputs` 1208; `_apply_restoration_to_model_input` 1280 **mutates in place**; `_stamp_solver_inputs` 1349 **mutates in place**) | indirect via cascade's `pre_input` argument | NO | **A. consumed-direct + heavily mutated** |
| 15 | `applied_finmo_json` | `Dict[str, Any]` | required | YES (`compute_adaptive_policy` 1156: `finmo_snapshot=applied_finmo_json or {}`) | NO (packed at 1582, never unpacked) | NO | **A. consumed-direct (one read)** |
| 16 | `stage_ramp_contract` | `Optional[Dict[str, Any]]` | Optional (None default) | YES (`_build_apply_lever_callable` 1370, `original_stage_family` extraction 1590, `original_stage_ramp_contract` cascade-restore 1626, persist 1851 via `_build_minimal_convergence_context`) | YES via `original_stage_ramp_contract` (1626) | YES (signature 1792, persist 1851) | **A. consumed-direct (4 sites — matches v2 §A line 469)** |
| 17 | `payroll_headcount` | `Optional[Dict[str, Any]]` | Optional (None default) | YES (`verify_structural_feasibility` 1241, `restore_feasibility` 1264, **mutated in place 1276**); also forwarded to cascade and _run_post_cascade_completion | YES (cascade.py:821, 849) | YES (signature 1786, persist 1842 region) | **A. consumed-direct + mutated** |
| 18 | `planning_context_summary_json` | `Optional[Dict[str, Any]]` | Optional (None default) | YES via persist sites (3609 `_persist_unified_convergence_state`; 3631 `_build_minimal_convergence_context`) | NO (packed at 1569, cascade never unpacks) | YES (signature 1788, persist 1830, 1852) | **C. persist-only — cascade-phantom** |
| 19 | `applied_finmo_json` | already counted | | | | | |

(Numbering jumps because applied_finmo_json appears twice in the v2 roster; deduped here.)

### T2.2 The "5-6 forwarded-but-unused" headline number — what it actually means

The hand-off referenced "5-6 forwarded-but-unused" params. The
trace finds **3 truly unused** params (Tier F: never read at
ANY site in the solver module) and **2 partially-phantom** params
(Tier C: cascade-phantom but read by orchestrator's persist site).
Total of 5 matches the lower bound; v2's count of 6 over-counts
because it conflated "phantom at cascade" with "phantom at the
boundary".

**Tier F — truly READER_MISSING** (recommend dropping or typing as `Optional[Any]` opaque):

| Param | Producer | Path of dead-end forwarding |
|---|---|---|
| `target_market_json` | initial-grid runner (parsed from draft) | orchestrator entry → inner_runner_kwargs (1571) → cascade ignores; orchestrator entry → _run_post_cascade_completion signature (1782) → body never reads |
| `planning_result` | initial-grid runner (grid application output) | orchestrator entry → inner_runner_kwargs (1579) → cascade ignores |
| `catalog_source_model_input_json` | initial-grid runner (original pre-grid baseline) | orchestrator entry → inner_runner_kwargs (1581) → cascade ignores |

**Tier C — partially-phantom** (cascade-only-missing; orchestrator persist site reads them):

| Param | Read site | What it's used for |
|---|---|---|
| `planning_context_summary_json` | orchestrator.py:3609 (`_persist_unified_convergence_state`), 3631 (`_build_minimal_convergence_context`) | persisted to `planning_runs.unified_convergence_context` for the workbook reader and the diagnostics view |
| `grid_application_summary` | orchestrator.py:3621 (`_persist_unified_convergence_state`) | persisted to `planning_runs` for diagnostic queries |

This is the Contract 3 analog of Contract 2's `debt_schedule`
REQUIRED-but-UNREAD finding. Two **structural** options for the
spec to decide between:

- **(a) Keep all 19 fields required + typed.** Forces upstream to
  hand a complete bundle, and pins down the "cascade-phantom"
  fields with structural shape constraints so a future cascade
  refactor that wants to unpack them doesn't need a contract
  amendment. Same disposition as Contract 2 Flag 1 for `debt_schedule`.
- **(b) Drop the 3 Tier-F params from the contract.** Treats them
  as truly dead; the orchestrator signature still has them
  (caller-compat) but the contract typed surface doesn't.
  Aligns with v2 §D's recommendation that the call signature
  "can be trimmed (or formally documented as having forwarded-only
  fields)".

Flag for spec §7.

### T2.3 Closure-only params (Tier B)

3 params (`people_json`, `fulfillment_json`, `marketing_model_json`)
are read ONLY through the closure that `_build_finmo_callable`
constructs at orchestrator.py:1361-1367. The closure is invoked
by every FINMO build inside the target-seeking loop, so they ARE
consumed — but the call path is indirect.

No action needed for the contract — these are real fields with
real readers. Flagging for the spec only because misreading the
read pattern (e.g. "the orchestrator doesn't reference them
directly so they must be phantom") is a known footgun. The
contract types them as required + Contract-1-shaped (or opaque
`Dict[str, Any]` if Contract 1 doesn't model the shape — see T3).

---

## T3. `applied_model_input_json` shape — does Contract 1 compose cleanly?

### T3.1 Producer side: yes

`applied_model_input_json` is produced by
`build_python_model_input_json` at
[finmo_bridge.py:2927](../../python/client_intake_and_finmo/finmo_bridge.py#L2927)
(Contract 1's producer). The initial-grid runner does some
post-build mutations via `_build_and_apply_payroll_schedule` and
`_apply_existing_payroll_authority`
([runner.py:1408, 1638](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1408))
but the writers all preserve Contract 1's surface — there's no
wrapping or re-shaping between build and bundle return.

Confirmed by Contract 1's producer-side gate at
[runner.py:1809-1822](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1809):
that gate calls `validate_model_input_at_boundary(applied_model_input_json, side=SIDE_PRODUCER)`
immediately before the dict return at line 1830-1850. So the value
handed to `run_target_seeking_orchestrated_system_run` is, by
construction, a validated Contract 1 shape.

**Consequence for Contract 3:** `SolverInputContract.applied_model_input_json`
types as `FinmoModelInputContract` (composition). Same pattern as
Contract 2's `WorkbookPayloadContract.model_input_json`. No
divergence to flag.

### T3.2 Consumer side: heavy in-place mutation

The orchestrator mutates `applied_model_input_json` in place at
two sites between entry and the cascade:

1. [orchestrator.py:1280](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1280) — `_apply_restoration_to_model_input` patches revenue + payroll rows after structural-feasibility restoration.
2. [orchestrator.py:1349](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1349) — `_stamp_solver_inputs` re-stamps calibrated envelope + targets onto the model_input.

The consumer-side gate validates at ENTRY, before any mutation.
After mutation the same value may no longer satisfy the contract
(rows get rewritten; the `controller_input_seed` gets re-stamped).
**This is acceptable** — the contract describes the producer →
consumer boundary, not internal mutation. But it means we cannot
re-validate post-mutation without re-shaping the contract. Same
limitation as Contract 1's consumer-side gate at
`build_python_finmo_json`.

### T3.3 `catalog_source_model_input_json` shape

Per runner.py:1846, `catalog_source_model_input_json =
copy.deepcopy(model_input_json)` — the pre-grid-application
baseline. Same Contract 1 shape. (Academic, since this is Tier F
truly unused; if Flag (a) keeps it, type as `FinmoModelInputContract`.)

---

## T4. Per-section consumption (analog of Contract 2 §T3 table)

Top-level field → reader function → reads what. Adapted from the
v2 inventory §C plus direct grep of the orchestrator body.

| Field | Reader function | What it reads from the field |
|---|---|---|
| `business_facts` | `compute_adaptive_policy` (orchestrator.py:1156-1162) | top-level dict → adaptive-policy contract |
| `business_facts` | `_bf_template` extraction (orchestrator.py:1188-1195) | `fact_template.business_stage`, `fact_template.business_model` |
| `business_facts` | `business_stage_for_cascade` (orchestrator.py:1605-1607) | `fact_template.business_stage` |
| `business_facts` | `_build_finmo_callable` closure (orchestrator.py:1361) | top-level dict → every FINMO build in the loop |
| `ops_json` | `compute_adaptive_policy` | top-level dict |
| `ops_json` | `authoritative_annual_revenue` | top-level dict |
| `ops_json` | NAICS extraction (orchestrator.py:1206, 1597) | `business_naics_6` (digits-only strip) |
| `ops_json` | `verify_structural_feasibility`, `restore_feasibility` | full payload (revenue/cost/capacity drivers) |
| `ops_json` | `_build_finmo_callable` closure | full payload |
| `target_market_json` | — | NEVER READ (T2.2 Tier F) |
| `people_json` | `_build_finmo_callable` closure | top-level dict → finmo per-quarter people drivers |
| `financials_json` | `compute_adaptive_policy`, `authoritative_annual_revenue`, `verify_structural_feasibility`, `restore_feasibility`, `_build_finmo_callable` closure | top-level dict |
| `financials_year1_json` | same five sites as `financials_json` | top-level dict |
| `fulfillment_json` | `_build_finmo_callable` closure | top-level dict |
| `marketing_model_json` | `_build_finmo_callable` closure | top-level dict |
| `planning_mode` | `compute_adaptive_policy`, fail-fast mode-unknown check (1100-1115), persist (1849), cascade `original_planning_mode` (1623) | string value |
| `planning_mode_reason` | `compute_adaptive_policy`, persist (1850), cascade `original_planning_mode_reason` (1624) | string value |
| `planning_result` | — | NEVER READ (T2.2 Tier F) |
| `grid_application_summary` | persist (orchestrator.py:3621) | full payload → persisted to planning_runs |
| `catalog_source_model_input_json` | — | NEVER READ (T2.2 Tier F) |
| `applied_model_input_json` | `_ensure_solver_inputs` (1208) | top-level — solver_input.{envelope, targets} extraction |
| `applied_model_input_json` | `_apply_restoration_to_model_input` (1280) | mutates `sections.revenue` rows, `sections.payroll` rows |
| `applied_model_input_json` | `_stamp_solver_inputs` (1349) | mutates `solver_input.{envelope, targets}` |
| `applied_finmo_json` | `compute_adaptive_policy` (1156: `finmo_snapshot=`) | full payload — one read at adaptive-policy compute |
| `stage_ramp_contract` | `_build_apply_lever_callable` (1370) | `stage_family`, `quarter_ramp_grid` |
| `stage_ramp_contract` | `original_stage_family` extraction (1590) | `stage_family` |
| `stage_ramp_contract` | cascade restoration (1626: `original_stage_ramp_contract=`) | full payload |
| `stage_ramp_contract` | persist (orchestrator.py:3631 via `_build_minimal_convergence_context`) | full payload → planning_runs.unified_convergence_context |
| `payroll_headcount` | `verify_structural_feasibility`, `restore_feasibility` | `rows` (per-quarter headcount entries) |
| `payroll_headcount` | cascade restoration (cascade.py:821, 849) | full payload |
| `payroll_headcount` | next_result post-stamp (1769: `next_result.setdefault("payroll_headcount", payroll_headcount)`) | full payload echoed in solver output |
| `planning_context_summary_json` | persist (orchestrator.py:3609, 3631) | full payload |

**No phantom-reads** (read but never required) found. The phantom
pattern at this boundary is exclusively phantom-required (T2.2
Tier F).

---

## T5. Silent fallback / defensive patterns

### T5.1 The dominant `or {}` pattern

Every required dict param is coerced to `{}` on read. Sample
counts in the orchestrator body for lines 1180-1380 (the pre-
cascade region — where the contract gate would land):

| Pattern | Sites |
|---|---|
| `<param> or {}` defensive coalesce | 20+ — every direct read of `business_facts`, `ops_json`, `financials_json`, `financials_year1_json`, `payroll_headcount`, `applied_model_input_json`, `applied_finmo_json`, `people_json`, `fulfillment_json`, `marketing_model_json` |
| `(payload or {}).get("key")` chains | `business_facts.fact_template.business_stage` (1190); `ops_json.business_naics_6` (1206, 1597) |
| `if isinstance(payload, dict)` guards before `.get` | `business_facts` guard at 1190; `ops_json` guard at 1206 |
| `cascade_outcome.get("envelope_payload") or envelope_payload` short-circuit fallback | orchestrator.py:1330-1331 |

**What the contract eliminates:** the `<param> or {}` coalesces.
With a typed gate at entry, `business_facts is None` is a contract
violation, not a silent empty-dict pass-through. The `.get()`
chains on `fact_template` / `business_naics_6` remain useful even
post-contract because those nested keys are intake-domain shapes
not currently modeled — flag for the spec whether to extend the
contract to model them (probably no for first cut; see Flag 4).

### T5.2 The mode-unknown fail-fast

[orchestrator.py:1100-1115](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1100)
implements an explicit fail-fast for unknown `planning_mode`
values. Four supported values: growth / stability / runway_extension /
(one more — confirm in spec). Contract should mirror this via
`Literal[...]` on the `planning_mode` field. Same pattern
Contract 2 used for `wage_positioning_tier`, `labor_intensity_class`.

### T5.3 `stage_ramp_contract` consumed without shape validation

Per v2 §F.3 — at three orchestrator sites (1370, 1590, 1626) and
one persist site (3631) the contract is read without validating
`quarter_ramp_grid` or `stage_family` is present. If upstream
returns `None` or `{}`, downstream sees empty data silently. v2
flagged this as UNCHANGED at the solver boundary; fix 5 only
addressed the workbook-reader side.

Contract 3 has the choice:
- **Type `stage_ramp_contract` as `Optional[StageRampContract]`** (composing the same model Contract 2 defines) — solves it at the boundary by failing fast on shape drift.
- **Leave as `Optional[Dict[str, Any]]`** — defers to producer-side fix; cheaper Contract 3 commit.

Flag for spec §7.

### T5.4 In-place parameter shadowing

[orchestrator.py:1273-1281](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1273)
reassigns `ops_json`, `payroll_headcount`, `applied_model_input_json`
during feasibility restoration. Per v2 §E this is fragile
architecture but not an active bug (closure constructed AT 1361
sees the post-reassignment names due to ordering).

**Not in scope for the contract** — the contract describes the
boundary, not internal mutation. Surfacing here per the spec
template's request to inventory fallback patterns.

---

## T6. Solver outputs (forward-looking note for Contract 4)

The orchestrator returns `Dict[str, Any]`. Key write sites for the
return value across the function body:

| Key | Write site | Source |
|---|---|---|
| `model_input_json` | 1665, 1933, 2008, 2095, 2218, 2284, 2470, 2630, 2831 | mutated `applied_model_input_json` final form |
| `finmo_json` | 1667, 1933, 2009, 2094, 2217, 2284, 2470, 2630, 2830 | `build_finmo_callable(final_model_input_json)` result |
| `target_seeking_diagnostics` | 1668 | per-iteration solver diagnostics dict |
| `plan_confidence` | 1669 | `"high_no_adaptation"` / `"high_with_adaptation"` / etc. |
| `adaptation_cascade_diagnostics` | 1671 | cascade-tier outcome dict (when cascade fires) |
| `adaptive_policy` | 1675 | `AdaptivePolicy.to_dict()` |
| `solver_target_assertion` | 3084 | finalize-validation assertion result |
| `debt_schedule` | 3105 | post-cash-pass debt schedule (Contract 2's `debt_schedule` field — same shape) |
| `capital_lease_schedule` | 3128 | post-cash-pass lease schedule |
| `payroll_headcount` | 1769 (setdefault) | echoed input + cascade-side updates |
| `post_cascade_completion` | 3660+ | finalize-validation trace dict |
| `realism_memo_json` | 3662 | realism-gate evaluation output |

**Not in scope for Contract 3.** Listed here so Contract 4
(FinmoJsonContract / SolverOutputContract — whichever scope Nick
chooses) has a starting roster. The shape is dict-keyed today; no
typed envelope at the return surface.

---

## T7. Divergences from v2 inventory

Taxonomy: **NEW SUBSTANTIVE** (contradicts v2 in a way that
changes contract design); **NEW STRUCTURAL** (new shape not noted
in v2); **CONFIRMED RESIDUAL** (v2 said RESIDUAL, still RESIDUAL);
**CONFIRMED CLOSED** (v2 said CLOSED, still CLOSED).

### Div-1. v2 §D miscounts "6 READER_MISSING for cascade post-fix-1" — NEW SUBSTANTIVE

v2 line 491-499 lists six params as cascade-phantom:
`target_market_json`, `planning_result`, `grid_application_summary`,
`catalog_source_model_input_json`, `planning_context_summary_json`,
plus the three closure-only params.

**Trace finds:**

- 3 params are truly READER_MISSING anywhere in the module
  (`target_market_json`, `planning_result`,
  `catalog_source_model_input_json`) — confirmed by grep.
- 2 params are cascade-phantom but orchestrator-persist-site reads
  them: `planning_context_summary_json` at orchestrator.py:3609 +
  3631; `grid_application_summary` at orchestrator.py:3621.
- The 3 closure-only params (people / fulfillment / marketing) are
  read via the closure and are NOT phantom in any sense.

**Impact on contract design:** distinguishes Tier-F (truly drop or
type-as-opaque) from Tier-C (must keep typed because persist needs
the shape). v2's count blurred this distinction.

### Div-2. Producer-side gate already exists at runner.py:1809-1822 — CONFIRMED CLOSED (Contract 1 carry-over)

Contract 1's producer-side gate validates `applied_model_input_json`
before bundle return. Means Contract 3's consumer-side gate over
`applied_model_input_json` will, in practice, never fail on that
sub-shape unless an out-of-band caller bypasses runner.py. Worth
documenting in the spec: the consumer-side gate at Contract 3 is
NOT redundant (the other 18 fields aren't gated upstream) but the
sub-composition of `applied_model_input_json` is structurally
redundant with Contract 1's producer gate.

Not a divergence per se — extends v2 §A's classification ("19
parameters" → "1 already-gated-as-Contract-1 + 18 newly-gated").

### Div-3. Two-hop wrapper between API and solver entry — NEW STRUCTURAL

v2 lists the entry as orchestrator.py:1024 called from
intake_consult.py:6962. v2 doesn't note that intake_consult.py
has TWO functions:

1. `_run_unified_post_grid_system_run` at 6962 — wraps
2. `_run_planning_system_for_draft_unified` at 7039 — adds another
   wrapper layer

The actual orchestrator-bound call lives at 7103. The two wrappers
contribute deepcopies + payroll_headcount default + planning_run_id
text-strip. Neither performs validation today.

**Impact on contract design:** the consumer-side gate at
orchestrator.py:1028 (inside the orchestrator entry, after the
`def` line) is the cleanest location. Placing it in either
wrapper layer would split the gate from the consumer.

### Div-4. v2 §F.3 `stage_ramp_contract` consumed without shape validation — CONFIRMED RESIDUAL

v2 said UNCHANGED at the solver boundary; trace confirms — at
orchestrator.py:1370, 1590, 1626, 3631 the contract is read with
only `isinstance(stage_ramp_contract, dict)` guards. Fix 5 only
hardened the workbook reader. Contract 3 could close this by
composing a typed `StageRampContract` sub-model (see Flag 3 below).

### Div-5. v2 §E "lossy model-input transformations" — CONFIRMED RESIDUAL

v2 noted `_ensure_solver_inputs` wraps + `_stamp_solver_inputs`
re-stamps + `_apply_restoration_to_model_input` mutates. Trace
confirms all three at orchestrator.py:1208, 1349, 1280.

**Not in scope for Contract 3** — boundary-level contract validates
at entry, doesn't track internal mutation. Surfacing here only to
acknowledge.

### Div-6. v2 §F.1 `_inner_runner` NameError — CONFIRMED CLOSED

v2 said fix 1 (9c2a74f) closed this. Trace confirms — the only
reference to `_inner_runner` in the module is the v2-cited
orchestrator.py:1617 line, but that line is now gated behind the
hard-fail / abort-reason branch and uses the bypass dict at
1420-1425 documented in v2. Not exercised at solve-time on healthy
plans.

### Div-7. v2 §F.2 "feasibility-restoration in-place shadowing" — CONFIRMED RESIDUAL

UNCHANGED. Already covered in T5.4.

### Div-8. Consumer-side exception propagation (Adjustment B carry-over) — CONFIRMED

The orchestrator entry is reached via two wrappers; the API
handler at [intake_consult.py:7298-7302](../../python/api_handlers/intake_consult.py#L7298)
catches `except RuntimeError as exc` (structured 500 with detail),
and at line 7377 catches `except Exception as exc` (generic 500
with `str(exc)`). `ContractViolation` is a subclass of `Exception`
(not `RuntimeError`) so it lands in the line-7377 catch — produces
a 500 with `detail=str(exc)`, persists snapshot via
`_persist_failed_system_run_snapshot`, dispatches failure email,
and logs `app.logger.exception("System run failed for draft %s", draft_id)`.

The `str(exc)` for `ContractViolation` carries
`MODEL_INPUT→SOLVER` + the field path + expected vs actual — same
structured message Contract 1 + 2 already provide. **Same end-to-end
verification pattern as Contract 2's Adjustment B applies here.**

No audit-wrapper layer (no `driver_run_with_audit_wrapper`) wraps
the orchestrator entry path — that wrapper is amalgamated-session
specific (Contract 1) and doesn't appear on the solver call
chain.

---

## Open questions / flags for the spec doc

Carrying forward as numbered flags in the format Contract 2 used
(spec §7). Listed here as a pre-spec digest — spec doc will expand
each into a recommendation + alternatives + Nick's pick.

1. **Adapter shape.** Introduce a `SolverInputBundle` dataclass mirroring `DraftWorkbookData`, or skip the dataclass and use a `SolverInputContract.from_initial_grid_state(...)` classmethod plus `validate_solver_input_at_boundary(payload, side=...)`? (T1.4)
2. **Tier-F field treatment.** Keep `target_market_json` + `planning_result` + `catalog_source_model_input_json` as typed required fields (matches Contract 2 Flag 1 disposition), or drop them from the contract and leave the orchestrator signature as caller-compat? (T2.2)
3. **`stage_ramp_contract` typed sub-model.** Compose Contract 2's `StageRampContract` model directly (closes v2 §F.3 at the solver boundary), or keep as `Optional[Dict[str, Any]]` opaque (defer to producer-side fix)? (T5.3 + Div-4)
4. **Nested-key typing.** Type `business_facts.fact_template` shape (currently read for `business_stage`, `business_model`) or leave as opaque? Recommend opaque for first cut — `fact_template` is an intake-domain shape not currently modeled and a Contract 3 detour into intake territory is scope creep.
5. **Producer-side gate.** Contract 1 placed its gate outside the floor wrapper. Contract 2 skipped (R8 follow-up — 5 different writers). Contract 3 has a single producer of all 19 fields (`prepare_initial_grid_for_draft`). Single producer-side gate at runner.py:1830 (just before bundle return) is feasible — adds one validate call. Recommend SHIPPING the producer-side gate as part of Contract 3 commit 3 (not deferring like Contract 2 R8). Confirm with Nick.
6. **Composition with Contract 1.** Type `applied_model_input_json` and `catalog_source_model_input_json` (if kept per Flag 2) as `FinmoModelInputContract`. (T3.1 — recommendation; no flag needed.)
7. **`extra` policy.** Follow Contracts 1 + 2: `extra="forbid"` on top-level `SolverInputContract`, `extra="ignore"` on every sub-contract. (No flag — established pattern.)
8. **Cross-field invariants.** Candidates: `planning_mode` ∈ {growth, stability, runway_extension, ...} via `Literal[...]`; `stage_ramp_contract.quarter_ramp_grid` length matches `LIVE_QUARTER_COUNT` (if Flag 3 is "compose"); `payroll_headcount` rows-cover-all-quarters (already in Contract 2 — re-export or re-declare?). Spec doc to enumerate.

---

## Lessons baked in for Contract 3 spec drafting

- **Trace before spec.** This trace doc surfaced 3 Div items v2
  didn't catch (Div-1, Div-3, Div-8) plus a recommendation flip
  on Flag 5 (producer-side gate is feasible here; Contract 2's
  R8 deferral doesn't transfer).
- **Match production vocabulary verbatim.** Param names + types in
  T1.1 lifted directly from orchestrator.py:1028 signature.
- **Don't loosen safety checks.** Tier-F flag (Flag 2) leans
  toward Option (a) keep-all-required per Nick's stance; the
  alternative (b) is documented but the recommendation is to
  type-them-required.
- **`extra="forbid"` only on top-level.** Established pattern;
  Flag 7 above.
- **Adjustment B verification at consumer-side.** Div-8 confirms
  the API-handler catch propagates ContractViolation cleanly via
  the existing line-7377 generic catch. No audit wrapper to
  bypass. Test in the consumer-gate commit will mirror Contract
  2's `ApiCatchPatternEndToEndTest`.
