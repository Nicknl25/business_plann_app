# P3.40 — Post-Intake Pipeline Data-Flow Inventory

**Status:** Pre-contract investigation. Foundation for the typed inter-stage
contracts work that follows.

**Scope:** Inventory only. Documents what flows across each of the 7 post-intake
stage boundaries, who writes each field, who reads each field, what is phantom
(read with no writer, written with no reader, fallback-masked), what is
inconsistent, and what real code bugs were uncovered along the way. **No
contract designs, no redesigns, no removal recommendations are made here** —
those decisions belong to the next phase, after this inventory is reviewed.

**Method:** Seven parallel `Explore` agents per boundary, each grep-tracing the
whole `python/` tree (not just its boundary's files) so cross-boundary
writer/reader chases resolved correctly. Each agent's most explosive claims
were independently verified in the main thread before publication. File:line
citations throughout.

---

## Executive Summary

**Boundaries found and inventoried:** all 7, ending at the Excel workbook.

**Phantoms found:** Multiple, distributed across most boundaries. The most
load-bearing are the working-capital slot subkeys (`dso`/`dpo`/`inventory_days`
read by [finmo_bridge.py:3466-3510](../../python/client_intake_and_finmo/finmo_bridge.py#L3466)
with **zero writers anywhere in the codebase**), the `stage_ramp_contract`
4-path fallback chain at [data.py:151-165](../../client_statements_output_excel/data.py#L151),
and `mirror.plan_state` which is read by every cascade tier but **never
refreshed** after a revise_* tool commits a change. Most phantoms are masked
today by `.get()`/`or {}` fallbacks; failures don't surface as crashes but as
silently degraded plans.

**Real code bugs found (must address before contracts lock the shape):**
1. `_inner_runner` is **referenced but never defined** at
   [orchestrator.py:1617](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1617).
   Phase 8 bypass deleted the call site but left this dangling argument to the
   cascade — when the cascade fires, it raises `NameError`.
2. `mirror.plan_state` is a frozen snapshot at session entry; revise_* tools
   commit to the DB but **never update the mirror**, so subsequent cascade
   tiers read stale state.
3. `mirror.set_validation_state()` is defined at
   [mirror.py:100](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L100)
   but **has zero callers** — validation_state stays empty all session.
4. Feasibility-restoration mutates orchestrator parameters in-place
   ([orchestrator.py:1254-1270](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1254)),
   shadowing names like `ops_json` and `payroll_headcount` so closures captured
   earlier see different data than later sites.
5. `slot["working_capital"]["dso"|"dpo"|"inventory_days"]` reads at
   [finmo_bridge.py:3466-3510](../../python/client_intake_and_finmo/finmo_bridge.py#L3466)
   are unreachable defensive code — never written, fallback chain handles the
   absence. Decide: complete the per-quarter override design, or delete the
   dead read path.

These are the things that, if left in place, would lock the wrong invariants
into the contracts.

---

## Boundary 1: INTAKE → POST_INTAKE

**Entry:** [`_run_planning_system_for_draft_unified` at intake_consult.py:7039](../../python/api_handlers/intake_consult.py#L7039)
hands off to [`prepare_initial_grid_for_draft` at post_intake_initial_grid/runner.py:30](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30).

Post-intake reads the persisted `intake_consult_drafts` row via `get_draft`
and parses each JSON column via `parse_json_dict`. Intake's structured-JSON
synthesis (per `project_p3_33_amalgamation` memory) is the load-bearing
contract: post-intake never sees raw Q&A.

### A. SHAPE

Eight top-level JSON fields cross the boundary, plus business-fact scalar
fields on the draft row.

| Field | Producer (intake-side) | Consumer (post-intake) | Notes |
|---|---|---|---|
| `operating_model_json` | [`consultant_finalize` at intake_consultant.py:583](../../python/client_intake_and_finmo/intake_consultant.py#L583) (OpenAI schema) | [runner.py:194](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L194) | `consumer_type`, `business_type`, `business_stage`, `lob_models[]`, `unit_*`, capacity, price, NAICS, milestones, confidence |
| `target_market_json` | [`target_market_finalize` at target_market_consultant.py:659](../../python/client_intake_and_finmo/target_market_consultant.py#L659) | [runner.py:195](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L195) | B2C selections OR B2B `naics_6`/size/age bands; both `target_market_summary` and `marketing_plan_summary` |
| `people_json` | [`people_capability_finalize` at people_capability_consultant.py:368](../../python/client_intake_and_finmo/people_capability_consultant.py#L368) | [runner.py:196](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L196) | `people[]`, `inferred_roles[]` with `months_until_hire`/`annual_wage`/`wage_source`, `business_naics_6` |
| `financials_json` | [`financials_chat_turn` accumulator at financials_consultant.py:1873](../../python/client_intake_and_finmo/financials_consultant.py#L1873) | [runner.py:197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L197) | Many ratios + opening balances; least schema-disciplined of the eight |
| `financials_year1_json` | [`assemble_financials_year1` at financials_year1.py:684](../../python/client_intake_and_finmo/financials_year1.py#L684) | [runner.py:198](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L198) | `lobs[]` nested by product + flat `company_revenue_total_year1` |
| `fulfillment_json` | Patch-system writes only ([intake_consult.py:6769](../../python/api_handlers/intake_consult.py#L6769)) | [runner.py:200](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L200) | No schema; ad-hoc patches; see Section F |
| `marketing_model_json` | [`_compute_marketing_model_json` at intake_consult.py:3667](../../python/api_handlers/intake_consult.py#L3667) | [runner.py:199](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L199) | Carries a `version` int; reader never checks it |
| `planning_context_summary_json` | Constructed by `_build_planning_context_summary_payload` | [runner.py:201](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L201) | Planning-mode metadata |

Persistence is uniform: every JSON column is `json.dumps`-encoded and written
via `append_messages` ([intake_consult_draft.py:1781+](../../python/client_intake_and_finmo/intake_consult_draft.py#L1781)).

### B. WRITERS

Single producer per field (above table). `operating_model_json`,
`target_market_json`, `people_json` are OpenAI-schema-enforced; `financials_*`
and `marketing_model_json` are computed by Python aggregation;
`fulfillment_json` accepts arbitrary keys from the patch system without a
schema gate.

`operating_model_json`, `target_market_json`, `people_json` support
`edit_mode` (e.g. [intake_consultant.py:610-622](../../python/client_intake_and_finmo/intake_consultant.py#L610)) so
their writer can overwrite the same field multiple times if the user revisits
the consultant. The persistence layer takes whatever was passed; there's no
revision count or checksum.

### C. READERS

Primary parse happens at
[runner.py:190-201](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L190).
Secondary readers across the pipeline:

- `build_shared_context` ([shared_context.py:31+](../../python/api_handlers/shared_context.py#L31)) re-reads from the same row and from
  legacy per-consult tables as a fallback.
- `build_python_finmo_json` ([finmo_bridge.py:2931-2956](../../python/client_intake_and_finmo/finmo_bridge.py#L2931)) reads
  `people_json`, `financials_json`, `financials_year1_json`, `marketing_model_json`.
- `apply_balance_sheet_contextual_seed_to_model_input` reads `financials_json` + `financials_year1_json`.
- `estimate_payroll_headcount_schedule_with_gpt` reads `people_json`, both `financials_*`.
- Orchestrator/cascade access all JSONs through `business_facts` and direct
  parameters threaded from `prepare_initial_grid_for_draft` (see Boundary 5).

### D. PHANTOMS

- **`fulfillment_json` is effectively READER_MISSING.** It's parsed at
  [runner.py:200](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L200)
  and passed as `fulfillment_context=fulfillment_json` to
  `estimate_balance_sheet_contextual_seed_with_gpt` at
  [runner.py:854](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L854),
  but the callee's signature does not accept that parameter. Result: any data
  the user enters via fulfillment patches is persisted but silently dropped.
  *Uncertainty:* this is presented as a real bug, but the deeper cause may be
  that the patch system writes to this column without anyone having wired the
  downstream consumer — i.e., it may be an in-progress feature, not a
  regression.
- **`realism_memo_json` is READER_MISSING for the planning path.** Written
  at [intake_consult.py:8230](../../python/api_handlers/intake_consult.py#L8230) on
  intake completion. No grep hit for any post-intake reader consuming it
  during the planning flow. Likely diagnostic only.
- **All eight JSON fields are FALLBACK_PATH reads.** Every parse uses
  `parse_json_dict(draft.get("…"))` which silently returns `{}` on missing or
  malformed JSON. Defensive by design, but means a malformed write upstream
  surfaces as an empty plan rather than an exception.

### E. INCONSISTENCIES

- **`financials_year1_json` has two valid access patterns**: nested via
  `lobs[].products[].revenue_total_year1` ([financials_year1.py:731-734](../../python/client_intake_and_finmo/financials_year1.py#L731))
  *and* flat via `.get("company_revenue_total_year1")` ([intake_consult.py:3691](../../python/api_handlers/intake_consult.py#L3691)).
  Both are intentional but the reader has to know which to use.
- **`marketing_model_json` carries `version: 3`** ([intake_consult.py:3685](../../python/api_handlers/intake_consult.py#L3685))
  but no reader checks the version. If the schema is bumped, older draft rows
  will silently pass through with the new readers expecting the new shape.
- **NAICS source field name varies** between `people_json.business_naics_6`,
  `ops_json.business_naics_6`, `ops_json.naics_code`, `ops_json.business_naics`
  — see Boundary 2 for full discussion.

### F. KNOWN BUGS

1. **`fulfillment_json` silent drop** — Section D above. Data persists,
   downstream never consumes it.
2. **`fulfillment_json` has no schema gate** — patch system at
   [intake_consult.py:6769](../../python/api_handlers/intake_consult.py#L6769)
   accepts arbitrary keys.
3. **`build_shared_context` swallows legacy-table import errors**
   ([shared_context.py:61, 77](../../python/api_handlers/shared_context.py#L61))
   with bare `except Exception: pass`, masking import errors.

---

## Boundary 2: POST_INTAKE_INPUT → INDUSTRY_BASELINE

**Entry:** the normalized intake bundle feeds NAICS resolver
([lookup.py](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py))
and the cohort-bands populator
([cohort_bands_table.py:160+](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L160))
which writes the SQL table read later by amalgamated tools.

### A. SHAPE

**Input to the populator/lookup:**
```python
business_profile = {
  "naics_6": str,                       # 6-digit, normalized by stripping non-digits
  "target_annual_revenue": float|None,  # from financials_year1_json
  "stage": str|None,                    # from ops_json.business_stage
  "business_model": None,               # always None (placeholder — see Section D)
}
```
Built at [runner.py:528-533](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L528).

**Output from NAICS cascade resolver** (`_payload_from_row` at
[lookup.py:240-254](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L240)):
```python
{
  "metric_key", "benchmark_min", "benchmark_target", "benchmark_max",
  "naics_code_used", "naics_level_used", "confidence_tier",
  "trust_flag",                # "naics_6_direct"|"naics_5_fallback"|…|"no_coverage"
  "fallback_chain_attempted",  # diagnostic only
  "data_source",
}
```

**Output from cohort populator** ([cohort_bands_table.py:31-57](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L31)):
SQL rows in `post_intake_cohort_bands` keyed by
`(draft_id, planning_run_id, section, lever_id, metric_key)` carrying
`benchmark_*`, `robust_min/max`, `naics_level_used`, `cohort_size`,
`firm_count`, `confidence_tier`, `cohort_table`, `data_source`.

**In-memory cohort-bands shape** (`get_bands` at
[cohort_bands_table.py:344-392](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L344)):
```python
{"section": str, "count": int, "bands": {lever_id: {…flat fields…}}}
```

### B. WRITERS

- `naics_6` source: intake-form-driven; normalized by `_naics_6_from_ops` at
  [finmo_bridge.py:332](../../python/client_intake_and_finmo/finmo_bridge.py#L332).
- `business_profile` constructed at
  [runner.py:528-533](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L528).
- NAICS cascade resolver writes the lookup payload row at
  [lookup.py:242-253](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L242).
- Cohort-bands SQL writer at
  [cohort_bands_table.py:206-244](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L206).
- Confidence-tier downgrade: `_downgrade_confidence` at
  [lookup.py:216-228](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L216)
  (cascade) vs `_confidence_tier_for_cohort_size` at
  [cohort_band_resolver.py:286](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L286)
  (cohort). Different logic, same tier vocabulary.

### C. READERS

- `_attach_seed_provenance` ([finmo_bridge.py:339-353](../../python/client_intake_and_finmo/finmo_bridge.py#L339))
  reads lookup output, stamps `seed_provenance_json` onto model_input rows.
- `driver_movement_assembler._resolve_naics_band` ([driver_movement_assembler.py:97-102](../../python/client_intake_and_finmo/post_intake_solver/driver_movement_assembler.py#L97))
  reads the cascade output to assemble per-lever envelopes.
- Cohort bands SQL is read by every amalgamated tool's `_echo_*_bands` helper
  (set_drivers, set_stage_ramp_contract, set_capex_rd_balance_seed,
  set_payroll_schedule), by [mirror.build_mirror at mirror.py:140-160](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L140),
  and by [evaluate_plan._margin_distance_from_bands at evaluate_plan.py:189-220](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L189).

### D. PHANTOMS

- **`business_profile.business_model` is always `None`** at the writer
  ([runner.py:532](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L532))
  and `map_revenue_to_cap_categories` at
  [cohort_band_resolver.py:211-247](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L211)
  accepts but does not consume it. Placeholder reserved for future use.
- **Cohort sections `capex_rd` and `payroll`** are defined in the table schema
  but not yet populated (Phase 3 step 1 only writes `drivers`,
  `balance_sheet`, `stage_ramp`). `set_payroll_schedule._resolve_bounds`
  ([set_payroll_schedule.py:125-138](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L125))
  already calls `get_bands(conn, section="payroll")` and softly handles the
  empty section. Status: in-progress feature, not phantom — see commit
  history. Worth flagging because the contract will need to allow "section
  present, no rows" as a valid state until the populator catches up.
- **`fallback_chain_attempted` from cascade**: diagnostic only, no
  computational reader. Safe to drop from a contract.
- **`cohort_query` field on `CohortBandResult`** ([cohort_band_resolver.py:165](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L165))
  is populated by the resolver but **not included in the SQL INSERT** at
  [cohort_bands_table.py:231-244](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L231)
  — silently dropped on materialization. Audit trail cannot reconstruct which
  revenue/stage/date windows were used. *Categorization:* READER_MISSING after
  persistence; the dataclass field exists for in-memory use only and that
  may have been intentional. Not a crash bug.

### E. INCONSISTENCIES

- **NAICS field name varies** across sources:
  - intake (people): `business_naics_6`
  - intake (ops): `business_naics_6` OR `naics_code` OR `business_naics`
    ([runner.py:239-240](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L239))
  - runtime context: `business_naics` (singular)
    ([runner.py:237](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L237))
  - model_input: `solver_input.business_profile.naics_6`
    ([finmo_bridge.py:3121](../../python/client_intake_and_finmo/finmo_bridge.py#L3121))
  - cohort populator: `business_profile.naics_6`
- **Cohort bands shape** is row-flat in SQL but nested
  `{section: {bands: {lever_id: row}}}` in-memory via `get_bands`. Any code
  that consumes a raw SQL row directly will not work with the in-memory shape
  used by tools and the mirror.
- **Confidence-tier gates differ**: cascade uses NAICS-level logic, cohort
  uses firm-count logic. Same vocabulary, different meaning.
- **`robust_min`/`robust_max` exist on cohort rows but not on legacy
  baseline-cascade outputs.** Tools reading from cohort bands expect them; if
  cohort is empty and code falls back to the cascade payload, those keys are
  missing.

### F. KNOWN BUGS

1. **`cohort_query` silently dropped on INSERT** — Section D above.
2. **`FAIL_COHORT_BANDS_MISSING` is hard with no cascade fallback.** If a
   business hits a NAICS where every section returns zero resolved cohort
   bands, [runner.py:509-537](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L509)
   will fail-fast (the populate call has a soft wrapper at lines 536-537, but
   the internal `raise_fail_fast` propagates when called non-soft per the
   comment at [cohort_bands_table.py:268-270](../../python/client_intake_and_finmo/post_intake_solver/cohort_bands_table.py#L268)).
   No path falls back to the cascade-only baseline. *Uncertain:* may be by
   design (the comment frames it as a precondition for the mirror), but if so
   the contract needs to encode that precondition.
3. **NAICS normalizer doesn't validate length** —
   `_naics_6_from_ops` strips all non-digits but returns whatever length
   results. A garbage input like `"ABC"` becomes `""`, treated as no_coverage
   silently. Soft-fallback; documented for completeness.
4. **Cohort row cache is keyed by query filters, not by metric**
   ([cohort_band_resolver.py:340](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L340)).
   If a cohort table is missing a column the caller expects, the percentile
   returns `(None, None, None)` and the resolver returns `None` silently —
   caller may not realize a different lever in the same cohort succeeded
   while this one fell back.
5. **No invariant check that `benchmark_min ≤ benchmark_target ≤ benchmark_max`**
   on INSERT. Mathematically guaranteed by the percentile interpolation today,
   but no defensive assertion. Low priority.

---

## Boundary 3: INDUSTRY_BASELINE → AMALGAMATED_SESSION

**Entry:** the SessionDriver is constructed by `session_factory.make_session_driver`
([session_factory.py:308](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L308))
and handed a `Mirror` ([mirror.py:119](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L119))
built with the cohort bands + the plan-state seed assembled by the initial-grid
runner. This is the boundary at the heart of the new architecture.

### A. SHAPE

**Mirror** (at session entry):
```
Mirror {
  invariants:        Dict[str,str]            # static
  authority:         str                      # static
  business_facts:    Dict[str,Any]            # from draft (NAICS, stage, name, …)
  plan_state: {                               # section → current committed payload
    "stage_ramp":              Dict           # from runner:1747
    "payroll":                 Dict           # from runner:1748
    "capex_rd_balance_seed":   Dict           # from runner:1749-1750
    "balance_sheet":           Dict           # alias of capex_rd_balance_seed
    "drivers":                 {}             # intentionally empty; authored by cascade
  }
  bands: {section: {lever_id: band_row}}      # from post_intake_cohort_bands
  validation_state:  Dict                     # empty until first evaluate
  recent_decisions:  List[RecentDecision]     # ring buffer cap=10
  sequence_position: Dict                     # never written (see Section D)
  budget:            Dict                     # never written (see Section D)
}
```

**Operating context** handed alongside the mirror
([runner.py:1766-1770](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1766)):
```python
{
  "model_input_template": model_input_json,
  "build_finmo": build_python_finmo_json,    # callable closure
  "stage_ramp_contract": stage_ramp_contract,
}
```

`model_input_json` and `finmo_json` are also passed directly to SessionDriver
as `model_input_json=`/`finmo_json=` at
[runner.py:1781-1782](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1781).

### B. WRITERS

| Mirror field | Writer | File:line |
|---|---|---|
| `plan_state["stage_ramp"]` | `set_stage_ramp_contract` | [runner.py:945](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L945) |
| `plan_state["payroll"]` | `set_payroll_schedule` | [runner.py:1103](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1103) |
| `plan_state["capex_rd_balance_seed"]` and `["balance_sheet"]` | `set_capex_rd_balance_seed` | [runner.py:771](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L771) |
| `plan_state["drivers"]` | seeded `{}`; cascade-authored via `revise_drivers` | [tools/revise_drivers.py:22](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/revise_drivers.py#L22) |
| `bands[section][lever_id]` | `populate_cohort_bands_for_run` (table) → `get_bands` (in-memory) | [runner.py:524](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L524) / [mirror.py:146](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L146) |
| `business_facts` | runner-built dict | [runner.py:1757](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1757) |

**During the cascade**, revise_* tools commit changes to the database (via the
corresponding `set_*` tool) but **do not mutate the mirror in place**. See
Section F bug 1.

### C. READERS

| Mirror field | Reader | Access |
|---|---|---|
| `plan_state[section]` | `_current_payload_for` closure | [session_factory.py:181](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L181) — `mirror.plan_state.get(key)` |
| `plan_state` (whole) | `_build_evaluate_plan_fn` closure | [session_factory.py:220](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L220) — `dict(mirror.plan_state)` |
| `business_facts` | CAPACITY primitive kwargs | [session_factory.py:262-264](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L262) |
| `business_facts` | `render_mirror_for_proposal` (responder prompt) | [responder.py:255-262](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L255) |
| `bands` (via `get_cohort_bands` re-read) | `_compute_lever_margins` | [evaluate_plan.py:195](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L195) |

### D. PHANTOMS

- **`mirror.validation_state` is WRITER_MISSING.** The setter
  `mirror.set_validation_state` exists at
  [mirror.py:100](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L100)
  and **has no callers anywhere in the codebase** (verified by grep). After
  the first `_evaluate()` ([session_driver.py:254](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L254)),
  the result is stashed on `self._last_result` but not propagated back to the
  mirror. Responder rendering will always see `validation_state == {}`.
- **`mirror.recent_decisions`** is appendable via a setter
  ([mirror.py:81-98](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L81))
  but `.recent_decisions` is never read by session_driver or responder. Ring
  buffer fills with no consumer.
- **`mirror.sequence_position` and `mirror.budget`** are declared on the
  dataclass and initialized empty ([mirror.py:74, 78](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L74))
  but no writer ever populates them. `SessionState.tool_call_budget_remaining`
  exists in the driver state but the mirror copy is dead.

### E. INCONSISTENCIES

- **`mirror.plan_state` is read-only during the cascade.** revise_* tools
  call set_* which commits to the database, but the in-memory mirror is never
  refreshed. The next cascade tier reads stale plan_state. This is the
  highest-priority issue at this boundary — see Section F bug 1.
- **`mirror.bands` is loaded once at session entry but `evaluate_plan` calls
  `get_cohort_bands` fresh from the table each invocation.** Two sources of
  truth for the same data. Low actual impact (bands don't change during a
  session) but architecturally muddled.
- **Operating-model levers (unit_price, utilization_rate, capacity) have no
  `revise_*` tool.** [`session_factory.dispatch`](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L165)
  returns `None` for these sections; session_driver logs the proposal but
  silently does not apply it ([session_driver.py:643-647](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L643)).
  Any cascade tier proposing operating-model adjustments is implicitly vetoed.
- **WC scalar levers (AR/AP/Inventory days) get a special wrapper shape**
  `{"working_capital_days": {lever_id: v}}` in `_patch_from_proposal`
  ([session_driver.py:1076-1106](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L1076)),
  which is undocumented in `CascadeLever.direction`. A future tier patching
  with a flat shape would be silently ignored.

### F. KNOWN BUGS

1. **`mirror.plan_state` never refreshes after a revise_* commit.** Closure
   at [session_factory.py:181-193](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L181)
   captures the mirror reference at factory time. After
   [session_driver.py:649](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L649)
   calls revise_fn (which persists to DB), the mirror still holds the entry
   payload. Tier-2 proposals patch against tier-1's pre-change state. **This
   is critical for the contracts work** — the contract needs to define who
   owns plan_state mutation and when the in-memory snapshot refreshes.
2. **`mirror.set_validation_state` defined, zero callers** — Section D above.
   Mirror's validation_state stays empty all session.
3. **Operating-model levers silently vetoed** — Section E above. Anything
   the cascade proposes for `unit_price`/`utilization`/`capacity` is logged
   and dropped.
4. **WC scalar patch shape undocumented** — Section E above.
5. **No diagnostic emit for stale plan_state reads** —
   [session_driver.py:649](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L649)
   reads the stale state without any log line; debugging cross-tier
   consistency issues is currently impossible from observability alone.

---

## Boundary 4: AMALGAMATED_SESSION → MODEL_INPUT

**Entry:** the amalgamated session's cascade and floor produce/mutate
`model_input_json`. FINMO consumes it via
[`build_python_finmo_json` at finmo_bridge.py:619](../../python/client_intake_and_finmo/finmo_bridge.py#L619).

### A. SHAPE

Top-level keys of `model_input_json` ([model_inputs.py:600-622](../../python/financial_model_engine/model_inputs.py#L600)):
```
{
  engine_contract_version: "financial_model_inputs_v1",
  business_name, start_date,
  sections: {
    revenue:       [row, …]   # named_range, controller_write, lever_id, lob, product, driver, revenue_slot_key, values[]
    expenses:      [row, …]   # named_range, controller_write, lever_id, label, value_kind, input_semantics, values[]
    balance_sheet: [row, …]   # same shape as expenses
    schedules: {
      debt_opening_balance_seed, lease_opening_balance_seed,
      ppe_opening_balance_seed, …,
      rows: [row, …]
    }
  }
}
```

Per-quarter internal structure — `ExpenseDriverSet` at
[model_inputs.py:179-205](../../python/financial_model_engine/model_inputs.py#L179) — carries
`cogs_percent`, `marketing_percent`, `r_and_d_percent`, `lease_amount`,
`payroll_amount`, `g_and_a_percent`, `interest_rate`, `depreciation_percent`,
`tax_percent`, `capex`, **and an opaque `working_capital: Dict[str, Any]`
that the system intended to hold per-quarter override sub-keys.**

### B. WRITERS

- Full structure: `FinancialModelInputs.to_model_input_json`
  ([model_inputs.py:539-622](../../python/financial_model_engine/model_inputs.py#L539)).
- Per-section population during session:
  - P&L driver anchors: `set_drivers` writes via
    `_write_gpt_authored_per_quarter_values` ([set_drivers.py:145-273](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_drivers.py#L145)).
  - Balance-sheet rows + WC days: `set_capex_rd_balance_seed`.
  - From-seed path: `FinancialModelInputs.from_controller_seed`
    ([model_inputs.py:362-402](../../python/financial_model_engine/model_inputs.py#L362)).
- `working_capital` (the dict itself) is read from each
  `controller_input_seed` slot at [model_inputs.py:400](../../python/financial_model_engine/model_inputs.py#L400)
  and from `set_expense_drivers` at [model_inputs.py:471](../../python/financial_model_engine/model_inputs.py#L471),
  but **the dict is always empty in practice** because the seed list itself
  is empty in normal runs (see Boundary 6).

### C. READERS

- Full model: `FinancialModelInputs.from_model_input_json`
  ([model_inputs.py:303-360](../../python/financial_model_engine/model_inputs.py#L303))
  feeds `calculate_finmo_model`.
- Balance-sheet assembly: `_build_model_input_overlay`
  ([finmo_bridge.py:3456-3520](../../python/client_intake_and_finmo/finmo_bridge.py#L3456))
  reads `slot["working_capital"]["dso"]` / `["dpo"]` / `["inventory_days"]`
  for AR/AP/Inventory Days rows.

### D. PHANTOMS

This is the most consequential set of phantoms in the pipeline. All three
sub-keys of `slot["working_capital"]` are **WRITER_MISSING** — read at
[finmo_bridge.py:3466, 3481, 3497](../../python/client_intake_and_finmo/finmo_bridge.py#L3466)
with **no writer anywhere in the codebase** (verified by grep — the only
other hits are for `industry_metrics` data-pull writes which never reach the
model_input slot).

The reads are guarded by an explicit→band→envelope fallback chain, so they
don't crash. They silently fall through to NAICS baseline values every time.
*Categorization:* WRITER_MISSING for the explicit-override path,
FALLBACK_PATH for the surrounding code. Boundary 6 reaches the same
conclusion independently with high confidence.

**`set_expense_drivers`'s `working_capital` parameter** is also
READER_MISSING — defined at
[model_inputs.py:447](../../python/financial_model_engine/model_inputs.py#L447) and used at
[model_inputs.py:470-471](../../python/financial_model_engine/model_inputs.py#L470), but
no caller ever supplies a non-None value.

### E. INCONSISTENCIES

- **WC days have two writers writing to different shapes**:
  `set_capex_rd_balance_seed` writes flat per-period values into
  `model_input.sections.balance_sheet[].values`; meanwhile `finmo_bridge`
  reads from `slot["working_capital"]["dso"]` (a different shape, never
  written). These two paths are uncoordinated; only the first does anything,
  the second is dead.
- A code comment at [set_drivers.py:33-38](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_drivers.py#L33)
  documents that WC scalar levers moved out of `set_drivers` and into
  balance_sheet under P3.33 — but the slot-level read path was never updated.
  This is the migration footprint.

### F. KNOWN BUGS

1. **Slot-level WC days reads at
   [finmo_bridge.py:3466-3510](../../python/client_intake_and_finmo/finmo_bridge.py#L3466)
   are unreachable in practice.** Either the per-quarter override feature
   needs a writer wired in (and contract would encode that shape), or this
   defensive code should go. Decision belongs to the user.
2. **Incomplete WC-days migration** (Section E above).
3. **`set_expense_drivers`'s `working_capital` parameter** is a dead
   parameter (Section D).

---

## Boundary 5: MODEL_INPUT → SOLVER (target_seeking)

**Entry:** `_run_unified_post_grid_system_run` at
[intake_consult.py:6962](../../python/api_handlers/intake_consult.py#L6962) calls
`run_target_seeking_orchestrated_system_run` at
[orchestrator.py:1024](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1024)
with 18+ named parameters.

### A. SHAPE

Parameter roster (all required unless marked):

| Param | Producer | Notes |
|---|---|---|
| `conn`, `draft_id`, `planning_run_id` | upstream | DB context |
| `business_facts` | initial-grid runner | dict with `fact_template`, addresses |
| `planning_context_summary_json` | (Optional) | metadata only |
| `ops_json`, `target_market_json`, `people_json`, `financials_json`, `financials_year1_json`, `fulfillment_json`, `marketing_model_json` | initial-grid runner | parsed from draft |
| `planning_mode`, `planning_mode_reason` | initial-grid runner | string |
| `planning_result` | initial-grid runner | grid application output |
| `grid_application_summary` | (Optional) | cohort-band application |
| `catalog_source_model_input_json` | initial-grid runner | original baseline |
| `applied_model_input_json` | initial-grid runner | post-grid model input |
| `applied_finmo_json` | initial-grid runner | post-grid FINMO output |
| `stage_ramp_contract` | (Optional) | stage profile + ramp grid |
| `payroll_headcount` | (Optional) | headcount schedule with quarter_totals |

### B. WRITERS

All produced by `prepare_initial_grid_for_draft`
([runner.py:30+](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30))
via the dependency-injection pattern documented in Boundary 1 and the
amalgamated session committing to `model_input_json` / `finmo_json` per
Boundary 4.

### C. READERS

Inside the orchestrator (selected — full table available; here are the most
load-bearing):

- `compute_adaptive_policy` at
  [orchestrator.py:1153-1160](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1153)
  reads `business_facts`, `ops_json`, `financials_json`, `financials_year1_json`,
  `applied_finmo_json`, `planning_mode`, `planning_mode_reason`.
- `authoritative_annual_revenue` at
  [orchestrator.py:1176-1180](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1176)
  reads `ops_json`, `financials_year1_json`, `financials_json`.
- `_ensure_solver_inputs` at
  [orchestrator.py:1197](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1197)
  consumes `applied_model_input_json`.
- `verify_structural_feasibility` /
  `restore_feasibility` /
  `_apply_restoration_to_model_input` (lines 1223-1265) read and mutate ops,
  financials, payroll.
- `_build_finmo_callable` ([orchestrator.py:1357-1365](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1357))
  captures business_facts, ops_json, people_json, financials_json,
  financials_year1_json, fulfillment_json, marketing_model_json into a
  closure used by every solver iteration.
- `inner_runner_kwargs` packs every original param (except `conn`) at
  [orchestrator.py:1560-1581](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1560)
  to forward to `run_adaptation_cascade`.

The target-seeking loop itself ([target_seeking_loop.py:189+](../../python/client_intake_and_finmo/post_intake_solver/target_seeking_loop.py#L189))
receives only `model_input_json`, the build/apply callables, and the
envelope/targets/influence payloads — it doesn't see the original
orchestrator params except through the closures.

### D. PHANTOMS

- **`target_market_json`, `planning_context_summary_json`,
  `catalog_source_model_input_json`, `planning_result`,
  `grid_application_summary`**: received by the orchestrator and forwarded
  into `inner_runner_kwargs`, but only consumed by the inner runner if it
  fires. With Phase 8 bypass active (Section F bug 1), the inner runner is a
  hardcoded passthrough dict — these params are effectively
  READER_MISSING in normal execution.
- **`people_json`, `fulfillment_json`, `marketing_model_json`**: read only
  through the `_build_finmo_callable` closure, not directly by the
  orchestrator. They are consumed every FINMO iteration, so READER_MISSING
  does not apply — but the indirection through a closure rather than a
  direct call site makes the read path easy to miss when refactoring.

### E. INCONSISTENCIES

- **Lossy model-input transformations**: `applied_model_input_json` is
  wrapped into `{solver_input: {envelope, targets}}` via `_ensure_solver_inputs`,
  re-stamped by `_stamp_solver_inputs`, and possibly mutated in-place by
  `_apply_restoration_to_model_input`. The raw structure is not preserved
  through the pipeline; later sites see a transformed view.
- **Envelope/targets are double-tracked**: `envelope_payload` and
  `targets_payload` are extracted as standalone arguments AND embedded in
  `model_input_json`. The target-seeking loop at
  [target_seeking_loop.py:235-252](../../python/client_intake_and_finmo/post_intake_solver/target_seeking_loop.py#L235)
  uses the standalone arguments if present, ignoring whatever is embedded.
- **In-place parameter shadowing** at
  [orchestrator.py:1254-1270](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1254):
  feasibility restoration reassigns `ops_json`, `payroll_headcount`,
  `applied_model_input_json`. Closures captured earlier (e.g. the
  build_finmo_callable at line 1357) still see the pre-restoration values;
  later code sees the post-restoration values. If an exception fires between
  these two regions, error reporting may show inconsistent state.

### F. KNOWN BUGS

1. **`_inner_runner` is referenced but never defined.** At
   [orchestrator.py:1617](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1617)
   the orchestrator passes `inner_runner_callable=_inner_runner` to
   `run_adaptation_cascade`, but `_inner_runner` is not a name defined
   anywhere in the module (verified by grep — only that single reference
   exists in the file). The cascade uses the callable at
   [adaptation_cascade.py:432](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L432)
   and [875](../../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L875).
   This is the Phase 8 cleanup that was started but not finished — the
   direct invocation was replaced by a hardcoded passthrough dict at
   [orchestrator.py:1420-1425](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1420)
   (`"status": "phase_8_inner_runner_bypassed"`), but the argument to the
   cascade was not updated. **When the cascade actually fires
   (`final_hard_fails` non-empty or `inner_runner_abort_reason` not None),
   this raises `NameError`.** Critical — must fix before contracts. Plans
   that succeed via the `"high_no_adaptation"` path
   ([orchestrator.py:1554](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1554))
   work; plans that need cascade adaptation crash.
2. **Feasibility-restoration in-place shadowing** — Section E above.
3. **`stage_ramp_contract` is consumed at multiple sites
   ([orchestrator.py:1368, 2076, 2114](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1368))
   without validation** that it has `quarter_ramp_grid`/`stage_family`.
   If upstream returns `None` or `{}`, downstream sites see empty data
   silently.

---

## Boundary 6: SOLVER → FINMO_BUILD

**Entry:** `build_python_finmo_json(model_input_json)` at
[finmo_bridge.py:619](../../python/client_intake_and_finmo/finmo_bridge.py#L619).
Cash strategy invocation rides on the same model_input.

### A. SHAPE

Forecast structure is **periods** (input meta) + **slots** (forecast
quarters). Periods carry `slot_index`, `column_index`, `column_letter`,
`year`, `quarter`, `date`, `is_stub`
([finmo_bridge.py:641-725](../../python/client_intake_and_finmo/finmo_bridge.py#L641)).
Slot dicts (from either `controller_input_seed` at
[finmo_bridge.py:2984](../../python/client_intake_and_finmo/finmo_bridge.py#L2984) or
`forecast_quarters` at [finmo_bridge.py:2989](../../python/client_intake_and_finmo/finmo_bridge.py#L2989))
carry per-quarter expense drivers + an opaque `working_capital` dict.

Debt/lease/balance-sheet schedules live in `sections.schedules.rows`
([finmo_bridge.py:2910-2920](../../python/client_intake_and_finmo/finmo_bridge.py#L2910)).

### B. WRITERS

- Revenue/expense/derived drivers — all properly written, see the full
  table in the agent's report (sources: target-seeking-loop applies lever
  updates; `apply_derived_driver_policies_to_model_input` for capex).
- Capex is the most derived: `_derived_capex_and_depreciation_runtime` at
  [finmo_bridge.py:1958-1970](../../python/client_intake_and_finmo/finmo_bridge.py#L1958)
  → stamp at [finmo_bridge.py:1998-2001](../../python/client_intake_and_finmo/finmo_bridge.py#L1998).
- **`slots[q].working_capital.dso`**: **zero writers** (verified).
- **`slots[q].working_capital.dpo`**: zero writers.
- **`slots[q].working_capital.inventory_days`**: zero writers.

### C. READERS

- Balance-sheet assembly: `_build_model_input_overlay`
  ([finmo_bridge.py:3456-3520](../../python/client_intake_and_finmo/finmo_bridge.py#L3456))
  reads the three WC sub-keys for AR/AP/Inventory Days.
- FINMO engine reads model_input balance_sheet **rows** (not slots) for the
  actual AR/AP/Inventory formulas (per
  [finmo_model.py:73-75](../../python/financial_model_engine/finmo_model.py#L73)).

### D. PHANTOMS — CORROBORATED WITH BOUNDARY 4

The Boundary 6 agent reached the same conclusion as Boundary 4
independently: `slot["working_capital"]["dso"]` /`["dpo"]` /
`["inventory_days"]` are **WRITER_MISSING with HIGH CONFIDENCE**.

Root cause hypothesis (from Boundary 6): the slot-level override path was
scaffolded for per-quarter working-capital variation but the solver
refactored to row-level period arrays instead. The read code at
[finmo_bridge.py:3456-3520](../../python/client_intake_and_finmo/finmo_bridge.py#L3456)
is orphaned defensive code that never executes the explicit-value branch
in production. Fallback chain (explicit → NAICS band → envelope default)
correctly handles the absence; no crashes.

### E. INCONSISTENCIES

- **Period vs slot terminology** is implicit; slot structure has no schema
  validation.
- **Balance-sheet row naming**: `"Accounts Receivable Days"` (row label) vs
  `"dso"` (slot field) vs `"ar_days_dso"` (metric key) — all consistent
  through a centralized mapping at
  [orchestrator.py:83-85](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L83),
  but the slot-level short names are never materialized today.

### F. KNOWN BUGS

1. **Unreachable defensive WC read path** (already documented in Boundary 4).
   No crash, but the per-quarter override feature is incomplete and the
   read code is misleading to future readers.
2. **No contract for per-quarter WC overrides.** If the design wants to
   allow Q8 capex-phase WC days to differ from Q4 ramp WC days, the current
   row-level structure cannot express it. Architectural limitation, not a
   bug per se.

---

## Boundary 7: FINMO_BUILD → WORKBOOK

**Entry:** `build_client_financial_model_workbook(data)` at
[workbook_builder.py:30](../../client_statements_output_excel/workbook_builder.py#L30),
where `data: DraftWorkbookData`
([data.py:64](../../client_statements_output_excel/data.py#L64)) is built from
the persisted draft row's JSON columns + an optional `run_diagnostics` payload
loaded from a separate table.

### A. SHAPE

`DraftWorkbookData` wraps six JSON columns: `model_input_json`, `finmo_json`,
`payroll_headcount`, `debt_schedule`, `planning_run_json`, optional
`run_diagnostics`.

Sheets and what they read:

- Revenue Drivers: `data.revenue_rows` from `model_input_json.sections.revenue`;
  `data.stage_ramp_contract` via 4-path fallback (see Section D).
- Payroll Schedule: `data.payroll_headcount` (root metadata + `.rows`).
- Debt Schedule, CapEx & Depreciation, Working Capital, Cash & Equity:
  `data.schedule_rows`, `data.expense_rows`, `data.balance_sheet_rows`,
  schedule seeds.
- Model Inputs sheet: bridges all schedules to FINMO via cell references.
- FINMO sheet: reads `data.periods` (3-path fallback: `finmo_json.quarter_rows`
  → `finmo_json.periods` → `model_input_json.periods` → generated default
  at [data.py:118](../../client_statements_output_excel/data.py#L118)).
- Source Audit: renders `finmo_json.pl` / `.balance_sheet` / `.cash_flow`
  read-only.
- Checks sheet: orchestrates validations across other sheets.
- Diagnostics sheet (optional): renders `run_diagnostics` payload.

### B. WRITERS

- `model_input_json` + `finmo_json` written by the orchestrator's UPDATE
  near [orchestrator.py:470-490](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L470).
- `planning_run_json.stage_ramp_contract` written via the orchestrator's
  post-cascade UPDATE around line 535-560.
- `payroll_headcount` written by `post_intake_headcount`.
- `debt_schedule` written by the convergence/debt builder.
- `run_diagnostics` written to its own table by `post_intake_run_diagnostics.py`.

### C. READERS

In addition to the sheet builders above:

- `build_run_email_body` ([workbook_email.py:280-347](../../python/client_intake_and_finmo/workbook_email.py#L280))
  reads `run_diagnostics` fields for the deliverable email.
- `workbook_model_status` ([workbook_model_status.py:100-184](../../python/client_intake_and_finmo/post_intake_runtime_validation/workbook_model_status.py#L100))
  reads the rendered Checks!B2 cell to fail-fast-gate on Model Status = OK.

### D. PHANTOMS

- **`stage_ramp_contract` 4-path fallback** at
  [data.py:151-165](../../client_statements_output_excel/data.py#L151) is the
  most pathological pattern in the codebase. Four candidate locations are
  tried in order; the first with a non-empty `quarter_ramp_grid` wins. The
  primary writer is the orchestrator's `planning_run_json.stage_ramp_contract`
  direct write; the other three appear to be legacy/safety fallbacks but
  none are documented. If all four come back empty, the Stage Ramp Contract
  section renders as all zeros silently. Categorization: FALLBACK_PATH that
  masks possibly-broken writers. Need to know which paths are actually
  populated in production before writing the contract.
- **`periods.days_in_quarter` defaults to `0`** if missing at
  [finmo_sheet.py:162](../../client_statements_output_excel/finmo_sheet.py#L162).
  Formulas at [finmo_sheet.py:213](../../client_statements_output_excel/finmo_sheet.py#L213)
  divide by this value — if it ever lands as `0` (because finmo_bridge
  failed to write `quarter_rows`), the workbook renders DIV/0 errors and
  the Model Status gate would surface them. Status: FALLBACK_PATH that
  masks a writer-side problem.
- **`periods` 3-path fallback** at
  [data.py:94-118](../../client_statements_output_excel/data.py#L94) generates
  21 spurious blank periods if all upstream sources are empty.
- **Checks sheet rows with missing `schedule_row` mappings**: builders that
  forget to call `ctx.add_schedule_row(...)` cause the corresponding check
  to silently no-op ([checks_sheet.py:713-727](../../client_statements_output_excel/checks_sheet.py#L713)).
  Validations vanish without notice; Model Status can pass while a check
  doesn't exist.

### E. INCONSISTENCIES

- **`PERIOD_COUNT=21` vs `QUARTER_COUNT=20`** at
  [data.py:8-9](../../client_statements_output_excel/data.py#L8) — the names
  are ambiguous; `values_21` papers over both shapes
  ([data.py:37-43](../../client_statements_output_excel/data.py#L37)).
- **Hardcoded payroll-sheet column letters** at
  [checks_sheet.py:270-280](../../client_statements_output_excel/checks_sheet.py#L270)
  reference column G/H/M against the layout at
  [schedule_sheets.py:304-306](../../client_statements_output_excel/schedule_sheets.py#L304).
  Reordering payroll columns silently breaks the check formulas.
- **Interest expense and depreciation combine debt+lease components**
  intentionally in FINMO ([finmo_sheet.py:201-202](../../client_statements_output_excel/finmo_sheet.py#L201)),
  documented as Phase 9 P3.17 reconciliation — not a bug, but the contract
  needs to know the FINMO sheet expects both `is::Interest Expense` and
  `cash::Lease Interest Expense` (likewise for depreciation).

### F. KNOWN BUGS

1. **`stage_ramp_contract` 4-path fallback** is fragile and undocumented.
   Decide which path is canonical, fail-fast on the rest.
2. **`days_in_quarter` defaulting to 0** masks an upstream failure and
   produces silent DIV/0 errors. Either guarantee upstream writes it, or
   refuse to render with a missing value.
3. **`periods` generated default** lets the workbook render 21 blank
   periods when all upstream sources are empty.
4. **Checks sheet silently skips unmapped rows** —
   [checks_sheet.py:727](../../client_statements_output_excel/checks_sheet.py#L727)
   `if source_row:` is the gate. Missing schedule_row registrations remove
   validations without surfacing the omission. Contract should require
   every check to have a mapped row.
5. **`run_diagnostics` load failure is silent** at
   [export_client_workbook.py:61-78](../../client_statements_output_excel/export_client_workbook.py#L61)
   — bare except returns `None`; user gets a blank Diagnostics sheet with no
   error indication.

---

## Cross-Cutting Findings

Patterns observed across multiple boundaries.

### CC-1: Phantom field reads masked by `.get()`/`or {}` fallbacks

Every boundary exhibits this. The pattern is:

```python
value = (container or {}).get("field")
if value is None:
    value = fallback_chain()
```

Most of the time the fallback is legitimate (NAICS baseline, envelope
default). But in several documented cases the fallback is masking a writer
that doesn't exist anywhere in the codebase:

- B4/B6: `slot["working_capital"]["dso" | "dpo" | "inventory_days"]` — zero
  writers.
- B7: `stage_ramp_contract` — written by the orchestrator at one path,
  three other fallback paths read but never written by current code.
- B3: `mirror.validation_state` — setter defined, zero callers; mirror's
  copy is permanently empty.
- B3: `mirror.recent_decisions` — setter called, but no reader anywhere.
- B7: `days_in_quarter` defaults to `0` and propagates as DIV/0 in formulas.

**Contract implication:** for each phantom, the choice is concrete and
binary — either the contract makes the field required (and a writer must
exist), or the contract makes it optional (and the absence path is the
*only* path). Treating the current "phantom + fallback" as the spec locks
in the silent-failure shape.

### CC-2: Multi-writer fields with no coordination

Several fields have multiple potential writers in different code paths,
producing the same nominal data through different code:

- `business_naics_6` lives in `people_json`, `ops_json` (under multiple
  key names), and gets normalized at three distinct call sites
  (B1/B2).
- `stage_ramp_contract` has at least four locations in `planning_run_json`
  that callers read in fallback order (B7).
- `model_input` is shape-transformed multiple times in the orchestrator
  (raw → wrapped → re-stamped → mutated in-place) without a single
  authoritative "current state" reference (B5).

**Contract implication:** the contract should pick the canonical
producer/location per field and document it. Other paths become either
deprecation candidates or alias-only.

### CC-3: In-memory snapshots that never refresh

- B3: `mirror.plan_state` is a frozen snapshot at session entry; revise_*
  tools commit to the DB but never refresh the mirror. Tier-2 reads tier-1's
  pre-change state.
- B3: `mirror.validation_state` would have the same shape but the setter
  itself is never called.
- B3: `mirror.bands` is loaded once; `evaluate_plan` calls `get_cohort_bands`
  fresh from the table on each invocation — duplicated reads, two sources
  of truth.

**Contract implication:** the contract must define mutation/refresh
semantics for the mirror. "Read-only snapshot" is a valid design but
incompatible with the current revise_* flow.

### CC-4: List-vs-dict drift for the same data

- B2: cohort_bands is row-flat in SQL but `{section: {bands: {lever_id: row}}}`
  in-memory via `get_bands`. Any reader switching paths will fail.
- B7: revenue/expense/balance_sheet rows come as lists of dicts; helpers
  re-key them by `label` ([data.py:50-60](../../client_statements_output_excel/data.py#L50))
  for some access patterns. Both shapes are live.

**Contract implication:** decide which shape is the contract shape and
provide a single adapter from the other.

### CC-5: Phase-N bypasses that left dangling references

The `_inner_runner` NameError (B5 F1) is the most acute instance. The
Phase 8 bypass replaced the inner-runner invocation with a hardcoded
passthrough dict but the cascade still receives the now-undefined
`_inner_runner` name. Similar pattern risk exists wherever a phase deleted
a code path but left arguments wired in — worth a sweep before writing
contracts.

### CC-6: Closures capturing mutable state

- B5: `_build_finmo_callable` at
  [orchestrator.py:1357](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1357)
  captures `ops_json`, `payroll_headcount`, etc. into a closure. Later
  feasibility restoration reassigns these names at the orchestrator scope
  but the closure still references the original objects (Python closes
  over names, but reassignment in the enclosing scope rebinds the name —
  if the restoration MUTATES the dict in place vs reassigns, the closure
  sees the mutation; if it reassigns to a new dict, the closure does not).
  Either way, the implicit data-flow is hard to follow.

**Contract implication:** the contract should either (a) make the params
immutable through the pipeline, or (b) explicitly route mutations through
a defined refresh point.

---

## Known Bugs List

The following are real code bugs uncovered during the inventory (distinct
from contract issues). They are listed roughly in order of severity — but
see the next section for which ones MUST be fixed before contract-writing
begins, vs which can be addressed after.

### Critical

1. **B5 F1 — `_inner_runner` undefined.** When `final_hard_fails` is
   non-empty or `inner_runner_abort_reason` is not None,
   [orchestrator.py:1617](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1617)
   passes a name that does not exist. Raises `NameError` at cascade tier 0.
   Plans that succeed via `"high_no_adaptation"` work; any plan needing
   cascade adaptation crashes. Phase 8 bypass left this dangling.

2. **B3 F1 — `mirror.plan_state` never refreshed after revise_* commits.**
   Multi-tier cascades read stale plan_state. Tier-2 patches against
   tier-1's pre-change state.

3. **B3 F2 — `mirror.set_validation_state` has zero callers.** Mirror's
   validation_state stays empty all session; responder rendering never
   sees evolving check results.

### High

4. **B4/B6 F1 — slot WC sub-keys (`dso`/`dpo`/`inventory_days`) have zero
   writers.** Defensive fallback path is unreachable in practice. Decide:
   complete the per-quarter override design, or delete the dead read path.

5. **B7 F1 — `stage_ramp_contract` 4-path fallback at
   [data.py:151-165](../../client_statements_output_excel/data.py#L151).**
   Undocumented; primary writer is path 1; paths 2-4 appear to be legacy.
   If all four are empty, Stage Ramp section renders as zeros silently.

6. **B5 F2 — Feasibility-restoration shadows parameters in-place at
   [orchestrator.py:1254-1270](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1254).**
   `ops_json`, `payroll_headcount`, `applied_model_input_json` are
   reassigned mid-function; pre-restoration closures see different data
   than post-restoration code.

7. **B7 F4 — Checks sheet silently skips unmapped rows.** Missing
   `ctx.add_schedule_row(...)` registrations remove validations without
   notice; Model Status can pass while a check doesn't exist.

### Medium

8. **B3 F3 — Operating-model levers have no `revise_*` tool.** Cascade
   proposals for unit_price/utilization/capacity are logged and silently
   dropped.

9. **B3 F4 — WC scalar patch shape `{working_capital_days: {...}}` is
   undocumented in `CascadeLever.direction`.** A future tier patching with
   a flat shape would be silently ignored.

10. **B2 F2 — `FAIL_COHORT_BANDS_MISSING` is hard with no cascade-only
    fallback.** A NAICS with zero cohort coverage in every section fails
    the run. Possibly by design; if so, the contract needs to encode the
    precondition.

11. **B1 F1 — `fulfillment_json` silent drop.** Persisted but downstream
    consumer never wired in.

12. **B7 F2 — `days_in_quarter` defaults to `0` masks an upstream failure
    and produces silent DIV/0 errors.**

13. **B5 F3 — `stage_ramp_contract` consumed at multiple sites without
    shape validation.**

### Low

14. **B1 F3 — `build_shared_context` swallows legacy-table import errors**
    with bare `except`.
15. **B2 F1 — `cohort_query` field on `CohortBandResult` silently dropped
    on SQL INSERT.**
16. **B2 F3 — NAICS normalizer doesn't validate length.**
17. **B2 F4 — Cohort row cache keyed by query filters, not by metric.**
18. **B7 F3 — `periods` 3-path fallback creates 21 spurious blank periods
    when all upstream sources empty.**
19. **B7 F5 — `run_diagnostics` load failure silent.**

---

## Recommended Bugs to Fix First

Fixing these *before* writing contracts means the contracts encode the
intended behavior rather than the silent-failure shape. Leaving them in
place would lock the wrong invariants into the contracts.

1. **B5 F1 — `_inner_runner` NameError.** The contract for boundary 5
   needs to specify what the cascade receives for `inner_runner_callable`.
   Today the answer is "an undefined name that will crash." Either:
   - wire up a real inner runner (restoring the convergence-runner path), or
   - remove the parameter entirely (cascade no longer invokes the inner
     runner, since Phase 8 bypassed it).
   Either decision unblocks the contract. Leaving it as-is means the
   contract documents a crash.

2. **B3 F1 — `mirror.plan_state` refresh semantics.** The contract at
   boundary 3 needs to define who owns plan_state mutation and when the
   in-memory snapshot refreshes. Today, multiple tiers read stale data;
   if the contract codifies the current shape, multi-tier cascade
   correctness is forever broken-by-design. Decision point: should
   revise_* tools return the new payload and SessionDriver patch the
   mirror, or should SessionDriver re-read plan_state from the DB after
   each tier commits?

3. **B3 F2 — `mirror.set_validation_state` zero callers.** The contract
   should either remove the setter (validation_state is permanently empty)
   or wire it in (after every `_evaluate()` call). The current state —
   "field exists, setter exists, never called" — would survive into the
   contract as a permanently-stub field.

4. **B7 F1 — `stage_ramp_contract` 4-path fallback.** Decide which path is
   canonical *before* the contract encodes the fallback chain. If path 1
   is the only intended writer, paths 2-4 should fail-fast (and the
   contract requires path 1).

5. **B4/B6 F1 — slot WC sub-keys writer-missing.** Decide whether to
   complete the per-quarter override design (writer added; contract
   requires the field) or delete the read path (contract has no
   per-quarter WC override; downstream stays row-based). Either is valid;
   leaving the phantom-read in is not.

Once these five are addressed, the contracts can encode current intent
faithfully. The remaining 14 bugs can be triaged after the contracts are
in place — they're either lower-blast-radius or have working fallbacks
that the contract can codify as official.
