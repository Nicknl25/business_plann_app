# P3.40 — Post-Intake Pipeline Data-Flow Inventory (v2)

**Status:** Post-fix re-run. v1 inventory at
[docs/architecture/p3_40_pipeline_data_flow_inventory.md](p3_40_pipeline_data_flow_inventory.md)
(commit 8ba4154) identified five critical bugs that would lock silent-failure
behavior into the typed stage contracts. All five have been fixed; this v2
re-inventory confirms closure, re-checks the residual bug list, and surfaces
anything that the fixes themselves uncovered.

**Method:** Same as v1 — 7 parallel `Explore` agents per boundary,
grep-tracing the whole `python/` tree, with main-thread verification on the
explosive claims. Each agent received the v1 baseline + the per-fix change
list and was instructed to be explicit about CHANGED vs UNCHANGED vs NEW.

**Fix commits in scope:**

| Fix | SHA | Bug |
|---|---|---|
| 1 | `9c2a74f` | `_inner_runner` undefined NameError (B5 F1) |
| 2 | `851fa28` | `mirror.plan_state` never refreshed after revise_* commits (B3 F1) |
| 3 | `b6968ae` | `mirror.set_validation_state` zero callers (B3 F2) |
| 4 | `b40c25a` | slot working_capital subkeys writer-missing (B4 F1, B6 F1) |
| 5 | `07938c8` | stage_ramp_contract 4-path silent fallback (B7 F1) |

---

## Executive Summary

**All 5 critical v1 bugs are closed.** Each fix was verified by the
corresponding boundary agent against current code and by integration tests
during the fix commits themselves.

**The fixes did not introduce new bugs.** Each agent ran a NEW phantoms /
inconsistencies / bugs sweep alongside the closure verification; nothing new
landed.

**The 14 lower-priority v1 bugs are unchanged.** They are residual exactly as
v1 documented them. Each was either out of scope for the 5 critical fixes or
deferred until after contracts.

**One new behavior to flag:** Fix 5 changed the workbook's
`stage_ramp_contract` property from silent fallback to fail-fast
`RuntimeError`. This is intentional hardening — operators now see writer-side
gaps instead of silently delivered wrong data — but it does mean that any
draft persisted before fix 5 with the `business_world_contract.stage_ramp_contract`
path unpopulated will now refuse to render until either re-converged or
explicitly migrated.

**Recommendation:** **Contract-writing can proceed.** The five fixes closed
the contract-blocking gaps; the residual 14 bugs are individually
contract-friendly (they're stable, documented, and either lower-blast-radius
or surrounded by adequate fallback behavior). The contracts work can encode
current intent without locking silent-failure shape.

---

## Per-Bug Closure Verification

### Bug 1 (B5 F1) — `_inner_runner` undefined → **CLOSED**

- Fix 1 (`9c2a74f`) removed `inner_runner_callable` from `run_adaptation_cascade`'s
  signature and inlined the Phase 8 passthrough dict at both invocation sites.
- Grep confirms zero remaining code references to `_inner_runner` or
  `inner_runner_callable` (residual hits are diagnostic status strings, log
  identifiers, and architecture doc text — none are name lookups).
- The cascade now fires cleanly via the inlined passthrough; the NameError
  pathway is structurally impossible.
- Side effect surfaced by the v2 sweep: 6 orchestrator parameters that were
  forwarded into `inner_runner_kwargs` (target_market_json,
  planning_context_summary_json, catalog_source_model_input_json,
  planning_result, grid_application_summary, and indirectly people_json /
  fulfillment_json / marketing_model_json) are now confirmed READER_MISSING
  for the cascade. They remain consumed via the build_finmo closure (the
  first three of those) or unused entirely (the last four). Documented in
  Boundary 5 §D; contract-writing should consider whether to keep them on
  the cascade call.

### Bug 2 (B3 F1) — `mirror.plan_state` never refreshed → **CLOSED**

- Fix 2 (`851fa28`) added `Mirror.set_plan_state_section`, threaded
  `apply_to_plan_state_fn` through SessionDriver, and wired it from
  `session_factory`. After every successful revise_* commit, the mirror is
  patched in place with the post-commit payload before the next
  `_current_payload_for` read.
- New `CASCADE_PROPOSAL_APPLIED_TO_MIRROR` EventCode registered in
  CASCADE_WALK phase; emitted on success, FAILED-status variant emitted on
  refresh failure (best-effort, doesn't abort the cascade).
- Verified with the integration test in the fix-2 commit message:
  tier-2 read sees tier-1's commit; veto path does NOT refresh; alias keys
  stay in sync for balance_sheet / capex_rd_balance_seed.

### Bug 3 (B3 F2) — `mirror.set_validation_state` zero callers → **CLOSED**

- Fix 3 (`b6968ae`) rewrote `Mirror.set_validation_state` to store a small
  projection (capped at 12 failing checks + 12 outside-band lever margins to
  control prompt budget), added `apply_to_validation_state_fn` callback,
  invoked it from `SessionDriver._evaluate` right after `_last_result` was
  stashed.
- `responder.render_mirror_for_proposal` now renders a "Current
  standards-check state" block into the user prompt, showing
  worst-failing-check + failing-check names + out-of-band lever margins with
  pin status. Verified in the integration test in the fix-3 commit message.

### Bug 4 (B4 F1, B6 F1) — slot working_capital subkeys writer-missing → **CLOSED**

- Fix 4 (`b40c25a`) deleted the dead per-quarter WC override path
  end-to-end. Slot-level reads of `dso`/`dpo`/`inventory_days` are gone from
  `finmo_bridge.py:3465+`; `ExpenseDriverSet.working_capital` field is gone
  from `model_inputs.py`; `set_expense_drivers`'s dead `working_capital`
  parameter is gone; `to_controller_expenses` no longer emits the key;
  `from_controller_seed` silently tolerates any legacy seed input.
- Verified with 5 integration tests covering attribute removal, signature
  changes, and backward compatibility for legacy seed input.
- The row-level WC writer path (`set_capex_rd_balance_seed` writing to
  `model_input.sections.balance_sheet[].values`) is the single remaining
  source of truth and was unchanged. The `working_capital_days` override
  shape used by `_patch_from_proposal` is unrelated to the deleted
  slot-level dict and remains live.

### Bug 5 (B7 F1) — stage_ramp_contract 4-path silent fallback → **CLOSED**

- Fix 5 (`07938c8`) collapsed the 4-candidate reader at
  `client_statements_output_excel/data.py:151+` to a single canonical read
  at PATH 2 (`planning_run_json.unified_convergence_context.business_world_contract.stage_ramp_contract`).
  Empty/missing `planning_run_json` still returns `{}` (legitimate
  pre-convergence scenario). Populated `planning_run_json` with the
  canonical path missing or empty `quarter_ramp_grid` now raises
  `RuntimeError("stage_ramp_contract_missing_at_canonical_path: ...")`.
- Removed the orchestrator's PATH 3 mirror write at
  `_build_minimal_convergence_context` since the reader's fallback chain no
  longer needs it. PATH 2 is the canonical writer; PATHS 1 and 4 had no
  writers anywhere.
- Verified with 7 tests covering all paths: legitimate-empty,
  legitimate-populated, missing-canonical-raises, empty-grid-raises,
  legacy-paths-no-longer-consulted, orchestrator-no-longer-mirrors.

---

## Residual v1 Bug List (Unchanged)

The 14 non-critical v1 bugs are out of scope for this commit batch and
remain as documented in v1. Each boundary agent confirmed they are
unchanged.

### High-priority residual

- **B7 F4** — Checks sheet silently skips rows when their `schedule_row`
  registration is missing
  ([checks_sheet.py:727](../../client_statements_output_excel/checks_sheet.py#L727)).
  Validations vanish without notice. Should be addressed soon; not strictly
  contract-blocking because the contract can require every check to have a
  mapped row, but the runtime gate is silent today.
- **B5 F2** — Feasibility-restoration in-place shadowing at
  [orchestrator.py:1254-1270](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1254).
  The closure construction at
  [orchestrator.py:1361-1369](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1361)
  happens AFTER the reassignments, so today's code is OK — but the pattern
  is fragile. A later refactor that moves the closure construction earlier
  would reintroduce the shadowing silently. Contract can document the
  intended timing but cannot enforce it.

### Medium-priority residual

- **B3 F3** — Operating-model levers (unit_price, utilization_rate,
  capacity) have no `revise_*` tool; cascade proposals for these are logged
  and silently dropped.
- **B3 F4** — WC scalar patch shape `{"working_capital_days": {...}}` was
  undocumented in v1. The fix-4 agent noted that v1's call here was already
  partially addressed by docstring updates in
  `_patch_from_proposal`; the wrapper shape is now documented but not yet
  formalized in `CascadeLever.direction`.
- **B2 F2** — `FAIL_COHORT_BANDS_MISSING` is hard with no cascade-only
  fallback. A NAICS with zero cohort coverage in every section fails the
  run. Possibly by design; if so, the contract must encode the precondition.
- **B1 F1** — `fulfillment_json` silent drop. Persisted by intake but the
  post-intake-side consumer was never wired in. *Update from v2 Boundary 1
  agent:* a new reader (`build_revenue_guardrail_signals`) added since v1
  consumes `fulfillment_context=fulfillment_json` BUT only in the
  interactive intake flow, NOT in the post-intake planning system run path.
  So the post-intake silent-drop status is unchanged.
- **B7 F2** — `days_in_quarter` defaults to 0 at
  [finmo_sheet.py:162](../../client_statements_output_excel/finmo_sheet.py#L162);
  formulas dividing by 0 silently produce DIV/0 errors masked by Excel.
- **B5 F3** — `stage_ramp_contract` is consumed at multiple orchestrator
  sites without shape validation. Fix 5 hardened the workbook reader; the
  orchestrator consumers still don't check.

### Low-priority residual

- **B1 F3** — `build_shared_context` swallows legacy-table import errors
  with bare `except`.
- **B2 F1** — `cohort_query` field on `CohortBandResult` silently dropped
  on SQL INSERT.
- **B2 F3** — NAICS normalizer doesn't validate length.
- **B2 F4** — Cohort row cache keyed by query filters, not by metric.
- **B7 F3** — `periods` 3-path fallback generates 21 spurious blank
  periods when all upstream sources empty.
- **B7 F5** — `run_diagnostics` load failure is silent.

---

## Boundary 1: INTAKE → POST_INTAKE

**Touched by fixes:** None directly. v1 baseline holds.

### A. SHAPE — UNCHANGED

Eight top-level JSON fields cross the boundary. The v1 SHAPE table is
re-confirmed verbatim (with line numbers slightly drifted to
[runner.py:190-197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L190)
due to unrelated commits between v1 and v2).

### B. WRITERS — UNCHANGED

Single producer per field as in v1. Edit-mode behavior at
[intake_consultant.py:610-622](../../python/client_intake_and_finmo/intake_consultant.py#L610)
is unchanged.

### C. READERS — UNCHANGED PRIMARY + ONE NEW SECONDARY (out of scope)

Primary parse at runner.py:190-197 unchanged. v2 agent flagged that
`build_revenue_guardrail_signals`
([financials_year1.py:1353-1410](../../python/client_intake_and_finmo/financials_year1.py#L1353))
now reads `fulfillment_context=fulfillment_json` at
[intake_consult.py:8269](../../python/api_handlers/intake_consult.py#L8269) and
[9158](../../python/api_handlers/intake_consult.py#L9158), but these call sites
are in the **interactive intake_consult flow** (the chat-turn handler), NOT in
the post-intake system run path. For the post-intake boundary the
`fulfillment_json` consumer is still missing.

### D. PHANTOMS — UNCHANGED

The three v1 phantoms remain (fulfillment_json silent drop for post-intake,
realism_memo_json never read by planning path, all 8 JSON fields are
FALLBACK_PATH reads via `parse_json_dict`).

### E. INCONSISTENCIES — UNCHANGED

v1 inconsistencies (financials_year1_json dual access patterns,
marketing_model_json version field unchecked by reader, NAICS field name
varies) all stand.

### F. KNOWN BUGS — UNCHANGED

All three v1 bugs still present (`fulfillment_json` silent drop;
`fulfillment_json` has no schema gate;
`build_shared_context` swallows legacy-table import errors with bare except).

---

## Boundary 2: POST_INTAKE_INPUT → INDUSTRY_BASELINE

**Touched by fixes:** None directly. v1 baseline holds; one fix-4-related
clarification.

### A. SHAPE — UNCHANGED

The `business_profile` input shape, NAICS cascade output shape, cohort
populator output shape, and in-memory `get_bands` shape are all unchanged
from v1.

### B. WRITERS — UNCHANGED

NAICS source normalization, business_profile construction, cascade resolver
writes, cohort SQL writes, and confidence-tier-downgrade logic are unchanged.

### C. READERS — UNCHANGED

`_attach_seed_provenance`, `driver_movement_assembler._resolve_naics_band`,
and the amalgamated `_echo_*_bands` helpers all read as before.

### D. PHANTOMS — UNCHANGED + 1 CLARIFICATION

The four v1 phantoms (`business_profile.business_model` always None;
cohort sections capex_rd/payroll defined but not yet populated;
`fallback_chain_attempted` diagnostic-only; `cohort_query` dropped on
INSERT) are all unchanged.

**Clarification from fix 4:** the v1 entry noting that fix 4 deleted the
dead slot-level WC override reader at finmo_bridge.py (which is a downstream
boundary) confirms that this boundary's cohort-band output is the **only**
band source for WC days — the per-quarter override path was indeed
unreachable, and the cohort/cascade fallback is now the single source of
truth.

### E. INCONSISTENCIES — UNCHANGED

NAICS field name variation, cohort_bands shape drift, confidence-tier gate
differences, and `robust_min`/`robust_max` only-on-cohort-rows all stand.

### F. KNOWN BUGS — UNCHANGED

All five v1 bugs unchanged.

---

## Boundary 3: INDUSTRY_BASELINE → AMALGAMATED_SESSION

**Touched by fixes:** Fix 2 (mirror.plan_state refresh), Fix 3
(mirror.set_validation_state wired).

### A. SHAPE — CHANGED

`Mirror` dataclass shape itself is unchanged. Two methods changed:

- **`Mirror.set_plan_state_section(section, payload)`** — NEW
  ([mirror.py:163-180](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L163)).
  Deep-copies the payload, writes to `plan_state[section]`, keeps
  `balance_sheet`/`capex_rd_balance_seed`/`capex_rd` aliases in sync with
  the read-side alias chain in `_build_current_payload_for`.
- **`Mirror.set_validation_state`** — REWRITTEN
  ([mirror.py:106-161](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L106)).
  Stores a small projection (capped at
  `_VALIDATION_STATE_RENDER_CAP = 12`): `all_pass`, `round_number`,
  `strictness`, `failing_check_count`, `worst_failing_check`,
  `worst_failing_distance`, `failing_check_names[]` (failing only,
  capped, with truncation flag), `failing_lever_margins[]` (outside_band
  only, capped, with truncation flag), `evaluated_at`. Old behavior
  (store full to_dict) is removed; the v1 inventory confirmed zero
  callers, so this rewrite is safe.

`mirror.plan_state` and `mirror.validation_state` are now actively
populated during the cascade; in v1 both were effectively dead snapshots.

### B. WRITERS — CHANGED

Original B1-B6 from v1 unchanged. Two new write paths added:

- `mirror.plan_state[section]` (refreshed after every successful
  revise_* commit) — written by `SessionDriver._commit_proposal` at
  [session_driver.py:663-680](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L663)
  via the new `apply_to_plan_state_fn` callback wired in
  [session_factory.py:339-340](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L339).
- `mirror.validation_state` (refreshed after every `_evaluate`) — written
  by `SessionDriver._evaluate` at
  [session_driver.py:857-865](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L857)
  via the new `apply_to_validation_state_fn` callback wired in
  [session_factory.py:346-347](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L346).

New EventCode `CASCADE_PROPOSAL_APPLIED_TO_MIRROR` registered in the
CASCADE_WALK phase
([phase_codes.py:90](../../python/client_intake_and_finmo/post_intake_diagnostics/phase_codes.py#L90)).

### C. READERS — CHANGED

Original v1 readers unchanged. One new read path:

- **`responder.render_mirror_for_proposal`** now renders the
  `mirror.validation_state` block into the GPT user prompt
  ([responder.py:269-309](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L269)).
  Shows round/strictness/all_pass header, failing-check count + worst
  check, failing-check names list (with truncation flag), and
  out-of-band lever margins with pin status.

### D. PHANTOMS — TWO CLOSED, RESIDUALS UNCHANGED

- v1 D1 (`mirror.validation_state` WRITER_MISSING) — **CLOSED by fix 3**.
- v1 D2 (`mirror.recent_decisions` setter called but no reader) — UNCHANGED.
  Ring buffer still fills with no consumer.
- v1 D3 (`mirror.sequence_position` and `mirror.budget` never written) —
  UNCHANGED.

### E. INCONSISTENCIES — ONE CLOSED, RESIDUALS UNCHANGED

- v1 E1 (`mirror.plan_state` read-only during cascade) — **CLOSED by fix 2**.
- v1 E2 (`mirror.bands` loaded once but `evaluate_plan` re-fetches) — UNCHANGED.
- v1 E3 (operating-model levers no revise_* tool) — UNCHANGED.
- v1 E4 (WC scalar patch shape undocumented) — agent reports docstring at
  `_patch_from_proposal` now documents the shape explicitly; the formalization
  in `CascadeLever.direction` is not yet done, so still partial.

### F. KNOWN BUGS — TWO CLOSED, THREE RESIDUAL

- v1 F1 (`mirror.plan_state` never refreshes) — **CLOSED by fix 2** (851fa28).
- v1 F2 (`mirror.set_validation_state` zero callers) — **CLOSED by fix 3**
  (b6968ae).
- v1 F3 (operating-model levers silently vetoed) — UNCHANGED.
- v1 F4 (WC scalar patch shape undocumented in CascadeLever.direction) —
  partially addressed (docstring); formal documentation still pending.
- v1 F5 (no diagnostic emit for stale plan_state reads) — **CLOSED by fix 2**
  via the new `CASCADE_PROPOSAL_APPLIED_TO_MIRROR` event.

**No new bugs found in this boundary by the v2 sweep.**

---

## Boundary 4: AMALGAMATED_SESSION → MODEL_INPUT

**Touched by fixes:** Fix 4 (slot working_capital deletion).

### A. SHAPE — CHANGED

Top-level keys of `model_input_json` unchanged. Per-quarter
`ExpenseDriverSet` shape **changed**: the `working_capital: Dict[str, Any]`
field is **removed** ([model_inputs.py:179-193](../../python/financial_model_engine/model_inputs.py#L179)).
The dataclass now carries exactly 10 float fields (cogs_percent through
capex). `to_controller_expenses()` returns exactly these 10 keys.

WC days rows in `sections.balance_sheet` (the row-level structure) are
unchanged.

### B. WRITERS — CHANGED

The row-level WC writer (`set_capex_rd_balance_seed` writing into
`model_input.sections.balance_sheet[].values`) is **unchanged** and is now
the single source of truth.

The slot-level writer surface is **gone**:
- `ExpenseDriverSet.working_capital` field removed
- `from_controller_seed` no longer assigns it
- `set_expense_drivers` no longer accepts it

### C. READERS — CHANGED

Three explicit-value branches at `finmo_bridge.py:3465-3510` for
"Accounts Receivable Days" / "Inventory Days" / "Accounts Payable Days"
**removed**. Each branch now goes directly NAICS-band → envelope-default.
A leading comment at
[finmo_bridge.py:3465](../../python/client_intake_and_finmo/finmo_bridge.py#L3465)
documents the removal.

Backward-compat: `from_controller_seed` silently tolerates legacy seed
input that still includes a `"working_capital"` key — the key is present
in the input but no assignment occurs, so the dataclass instance is clean.

### D. PHANTOMS — CLOSED

All three v1 working-capital phantoms (slot `dso` / `dpo` / `inventory_days`
writer-missing reads) are closed by fix 4. The dead `working_capital`
parameter on `set_expense_drivers` is also gone.

No new phantoms found by the v2 sweep.

### E. INCONSISTENCIES — CLOSED

The v1 inconsistency about two-writers-different-shapes (slot dict vs
balance-sheet rows) is closed; only the row-level writer remains.

The migration-footprint comment at
[set_drivers.py:33-38](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_drivers.py#L33)
that documented the P3.33 move is consistent now (slot-level reader is
gone).

### F. KNOWN BUGS — CLOSED

All three v1 bugs (unreachable defensive WC read path; incomplete WC-days
migration; `set_expense_drivers`'s `working_capital` parameter dead) are
closed by fix 4. No new bugs found.

---

## Boundary 5: MODEL_INPUT → SOLVER (target_seeking)

**Touched by fixes:** Fix 1 (`_inner_runner` removal), Fix 5
(`_build_minimal_convergence_context` mirror write removal).

### A. SHAPE — Roster reduced

The 19-parameter signature of `run_target_seeking_orchestrated_system_run`
is structurally unchanged at the call surface, but the **post-fix-1
landscape redistributes** which parameters are actually consumed vs
forwarded-but-unused:

| Param | v1 status | v2 status |
|---|---|---|
| `ops_json`, `financials_json`, `financials_year1_json`, `payroll_headcount` | consumed (restoration + finmo closure) | consumed (restoration + finmo closure + cascade restoration context) |
| `applied_model_input_json`, `applied_finmo_json` | consumed | consumed |
| `business_facts`, `planning_mode`, `planning_mode_reason` | consumed | consumed |
| `stage_ramp_contract` | consumed | consumed (4 sites) |
| `people_json`, `fulfillment_json`, `marketing_model_json` | indirect via build_finmo closure | indirect via build_finmo closure (unchanged) |
| `target_market_json` | forwarded to inner_runner_kwargs | now READER_MISSING — no inner runner consumes it |
| `planning_context_summary_json` | forwarded + secondary mirror write | now READER_MISSING in solver (fix 5 removed the mirror; the parameter is kept for caller-compat per fix 5 docstring) |
| `planning_result`, `grid_application_summary`, `catalog_source_model_input_json` | forwarded to inner_runner_kwargs | now READER_MISSING — no inner runner consumes them |

`inner_runner_kwargs` is still constructed and passed to the cascade because
restoration at adaptation_cascade.py:813-816, 841-846 reads
`ops_json`/`financials_json`/`financials_year1_json`/`payroll_headcount` from
it. The other dict entries are packed but never unpacked.

### B. WRITERS — UNCHANGED

All produced by `prepare_initial_grid_for_draft` as in v1.

### C. READERS — Restructured

The orchestrator's direct reads (lines 1153-1287 region) are mostly
unchanged. The cascade's read path was simplified: in v1 the inner runner
(then-deleted convergence runner) would have consumed the full
`inner_runner_kwargs`; now only restoration reads from it.

### D. PHANTOMS — Major recategorization

Six parameters are now confirmed READER_MISSING for the cascade
post-fix-1: `target_market_json`, `planning_result`,
`grid_application_summary`, `catalog_source_model_input_json`,
`planning_context_summary_json`, and (indirectly) the three closure-only
params (people_json, fulfillment_json, marketing_model_json) still see
direct use via the build_finmo closure so they're not phantoms.

This is contract-friendly information: the solver call signature can be
trimmed (or formally documented as having forwarded-only fields) in the
contracts work that follows.

### E. INCONSISTENCIES — UNCHANGED

All four v1 inconsistencies (lossy model_input transformations;
envelope/targets double-tracked; in-place parameter shadowing;
stage_ramp_contract consumed without shape validation) are unchanged.

The in-place shadowing item has nuance: closure construction at
[orchestrator.py:1361-1369](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1361)
happens AFTER the reassignments at
[orchestrator.py:1264-1266](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1264),
so today's code captures the post-restoration objects correctly. The
fragility is a maintenance risk, not an active bug.

### F. KNOWN BUGS — One closed, residuals unchanged

- v1 F1 (`_inner_runner` NameError) — **CLOSED by fix 1** (9c2a74f).
- v1 F2 (feasibility-restoration in-place shadowing) — UNCHANGED;
  lurking architectural fragility.
- v1 F3 (`stage_ramp_contract` consumed without validation) — UNCHANGED
  at the orchestrator sites; partially addressed by fix 5's RuntimeError
  at the workbook reader.

**No new bugs found in this boundary by the v2 sweep.**

---

## Boundary 6: SOLVER → FINMO_BUILD

**Touched by fixes:** Fix 4 (slot working_capital deletion at finmo_bridge).

### A. SHAPE — CHANGED

Slot dicts no longer carry a `working_capital` sub-dict
([finmo_bridge.py](../../python/client_intake_and_finmo/finmo_bridge.py)
post-fix-4). Per-quarter expense drivers remain (10 fields per slot).

Debt/lease/balance-sheet schedules in `sections.schedules.rows` unchanged.

### B. WRITERS — CHANGED

Row-level WC days writer (`set_capex_rd_balance_seed`) unchanged. Slot-level
WC writer surface is gone (fix 4).

### C. READERS — CHANGED

The three explicit-value branches in `_build_model_input_overlay` are gone;
NAICS-band → envelope-default is now the only path for AR/AP/Inventory Days.

FINMO engine still reads balance_sheet **rows** at
[finmo_model.py:73-75](../../python/financial_model_engine/finmo_model.py#L73)
for the AR/AP/Inventory formulas (unchanged).

### D. PHANTOMS — CLOSED

All three v1 working-capital phantoms (corroborated with Boundary 4) are
closed. The slot-level read path is gone; the row-level writer path is now
the single source of truth.

No new phantoms found.

### E. INCONSISTENCIES — UNCHANGED

Period vs slot terminology and balance-sheet row naming inconsistencies
are unchanged (low-impact).

### F. KNOWN BUGS — CLOSED

- v1 F1 (unreachable defensive WC read path) — **CLOSED by fix 4** (b40c25a).
- v1 F2 (no contract for per-quarter WC overrides) — UNCHANGED;
  architectural limitation, now honest (the dead scaffolding is gone).

---

## Boundary 7: FINMO_BUILD → WORKBOOK

**Touched by fixes:** Fix 5 (stage_ramp_contract reader collapse + orchestrator
mirror write removal).

### A. SHAPE — CHANGED

`DraftWorkbookData.stage_ramp_contract` property
([data.py:151-193](../../client_statements_output_excel/data.py#L151)) now
reads only the canonical location. v1's 4-candidate fallback list is
removed. Property docstring documents the new contract.

All other properties (`periods`, `revenue_rows`, etc.) unchanged.

### B. WRITERS — CHANGED

PATH 2 (canonical, written by `_build_minimal_convergence_context`) is
unchanged. PATH 3 mirror write (was at
`orchestrator.py:439-446` in v1) is **removed**. PATHS 1 and 4 had no
writers in v1 and still have none.

### C. READERS — CHANGED

`build_revenue_drivers_sheet` reads `data.stage_ramp_contract` via the
new property. The property now **fails fast** with `RuntimeError` when
`planning_run_json` is populated but the canonical path is missing or
empty. This is a **new failure mode** in the workbook export — operators
will see a clear error instead of silently rendering zeros.

Other consumers (workbook_email, workbook_model_status) unchanged.

### D. PHANTOMS — One closed, residuals unchanged

- v1 D1 (`stage_ramp_contract` 4-path fallback) — **CLOSED by fix 5**.
- v1 D2-4 (`periods.days_in_quarter` defaults to 0; `periods` 3-path
  fallback creates spurious blanks; Checks sheet silently skips unmapped
  rows) — UNCHANGED.

### E. INCONSISTENCIES — UNCHANGED

PERIOD_COUNT vs QUARTER_COUNT ambiguity, hardcoded payroll-sheet column
letters, intentional interest+depreciation combination — all unchanged.

### F. KNOWN BUGS — One closed, four residual

- v1 F1 (`stage_ramp_contract` 4-path fallback) — **CLOSED by fix 5**.
  NEW intentional fail-fast behavior documented above.
- v1 F2-F5 (`days_in_quarter` → 0; `periods` 21 spurious blanks; Checks
  sheet silent skip; `run_diagnostics` load silent fail) — UNCHANGED.

---

## Cross-Cutting Findings — Updated

Status of v1's 6 cross-cutting patterns after the fixes:

### CC-1: Phantom field reads masked by `.get()`/`or {}` fallbacks

- B4/B6 working_capital phantom → **CLOSED by fix 4**.
- B7 stage_ramp_contract 4-path → **CLOSED by fix 5**.
- B3 mirror.validation_state → **CLOSED by fix 3**.
- B3 mirror.recent_decisions setter-only — RESIDUAL.
- B7 days_in_quarter default-to-0 — RESIDUAL.

Pattern still present in residual form but the headline cases are closed.

### CC-2: Multi-writer fields with no coordination

- B7 stage_ramp_contract had 4 read paths, 1+1+0+0 writers; now 1 read
  path, 1 writer (fix 5).
- B5 model_input multi-stage transform unchanged.
- B1/B2 `business_naics_6` multi-source unchanged.

Pattern reduced but not eliminated. Remaining instances are
contract-friendly (writer drift is documented).

### CC-3: In-memory snapshots that never refresh

- B3 mirror.plan_state never refreshes → **CLOSED by fix 2**.
- B3 mirror.validation_state would have the same shape but setter never
  called → **CLOSED by fix 3**.
- B3 mirror.bands loaded once, evaluate_plan re-reads — RESIDUAL.

Pattern's worst manifestations are closed.

### CC-4: List-vs-dict drift for the same data

- B2 cohort_bands shape drift — UNCHANGED.
- B7 revenue/expense/balance_sheet rows list-vs-dict — UNCHANGED.

No change. Contract-writing can fix these.

### CC-5: Phase-N bypasses that left dangling references

- B5 `_inner_runner` NameError — **CLOSED by fix 1**.

Pattern eliminated for the highest-blast-radius case. No other dangling
Phase-N refs found by the v2 sweep.

### CC-6: Closures capturing mutable state

- B5 `_build_finmo_callable` captures over names; restoration mutates the
  names — UNCHANGED. Today's code is OK due to ordering (closure built
  after reassignments) but the pattern is fragile.

Pattern unchanged. Contract can document the intended ordering but cannot
enforce it without restructuring.

---

## Recommended Path Forward

**Contract-writing can proceed.** The five critical bugs are closed.
Each fix was surgical, integration-tested, and verified by the v2
boundary re-runs. No new bugs were introduced.

**Suggested contract sequence** (one contract per boundary, written one
at a time so we can validate each before moving on):

1. **Boundary 4: model_input_json** — most stable now (fix 4 simplified
   the writer surface significantly; the canonical structure is clean).
2. **Boundary 7: workbook DraftWorkbookData** — also stable now (fix 5
   gave a single canonical reader for the most-contested field).
3. **Boundary 3: amalgamated mirror + plan_state + validation_state** —
   refresh semantics now defined by fixes 2 and 3; contract can encode
   them as official.
4. **Boundary 5: orchestrator parameters** — needs a small cleanup
   decision on the 5-6 forwarded-but-unused params (target_market_json,
   planning_context_summary_json, etc.) before contract; could be in
   scope of the contract itself.
5. **Boundary 1: intake JSONs** — the fulfillment_json silent drop is the
   biggest open question; contract should either require the wiring or
   formalize the field's not-consumed-by-post-intake status.
6. **Boundary 2: cohort bands** — multiple residual bugs (cohort_query
   drop, NAICS length, cache key, bands shape drift) but each is
   individually small. Contract can encode the current shapes and the
   FAIL_COHORT_BANDS_MISSING precondition.
7. **Boundary 6: FINMO build** — minimal surface change; contract is
   straightforward now.

Several residual bugs (B7 F4 Checks sheet silent skip; B5 F2
restoration in-place shadowing; B3 F3 operating-model levers no
revise_*) are worth a separate cleanup pass after the contracts are in
place — they're known and stable but not contract-friendly to leave
silent forever.
