# P3.33 Phase 3.5 — Fail-Fast Point Inventory

**Status:** Inventory (companion to Step 9d-implementation).
**Predecessors:** Steps 9a (diagnostics enums + writer), 9b (SessionDriver +
adjacent-layer emits), 9c (downstream pipeline emits).
**Successor:** Step 9d-implementation — wires every entry below to a
`FailFastCode` and an assertion site.

---

## 0. Doctrine recap

A *fail-fast point* is a structural invariant that, when violated, must
**stop the pipeline with a re-raised structured RuntimeError** rather than
silently degrade. The pattern is the wrapper-D contract from the
step-8 design discussion:

```python
try:
  ...invariant check or production call...
except SomeStructuredFault as exc:
  # Best-effort audit row. safe_emit() swallows its own exceptions so
  # observability never crashes the pipeline.
  safe_emit(conn, draft_id=..., planning_run_id=...,
            phase=PhaseCode.X, event_code=EventCode.X_FAILED,
            status=Status.FAILED,
            diagnostic_data={"fail_fast_code": code.value,
                             "where": "...", "detail": str(exc)[:500]})
  # ALWAYS re-raise.
  raise RuntimeError(
    f"post_intake_fail_fast::{code.value}: {detail}"
  ) from exc
```

§10.5 forbids silent degradation: there is **no** path where a fail-fast
point's invariant is violated and the pipeline continues. The wrapper's
job is to attach an audit row; the pipeline's job is to die.

The exception type is `RuntimeError` whose message **starts with**
`post_intake_fail_fast::` followed by the FailFastCode value. Tests and
upstream handlers parse this prefix.

---

## 1. `FailFastCode` enum

New module: `python/client_intake_and_finmo/post_intake_diagnostics/fail_fast_codes.py`.

The enum is closed and partitioned by phase, identically to `EventCode`
in `phase_codes.py`. Every code below names the invariant it guards.

```python
class FailFastCode(str, Enum):
  # cohort_bands_populator
  FAIL_COHORT_BANDS_MISSING            = "fail_cohort_bands_missing"
  FAIL_COHORT_BANDS_MALFORMED          = "fail_cohort_bands_malformed"

  # mirror_build
  FAIL_MIRROR_PLAN_STATE_NOT_DICT      = "fail_mirror_plan_state_not_dict"
  FAIL_MIRROR_BANDS_UNRESOLVED         = "fail_mirror_bands_unresolved"
  FAIL_MIRROR_FINMO_BASELINE_BUILD     = "fail_mirror_finmo_baseline_build"

  # round1_authoring
  # NOTE: round-1 authors three sections only — capex_rd_balance_seed,
  # stage_ramp, payroll. set_drivers(anchors=None) is NOT a round-1
  # authoring path; it returns accepted=False with
  # "amalgamated_session_pending" by design, and drivers are authored
  # via revise_drivers inside the cascade.
  FAIL_ROUND1_SET_TOOL_REJECTED        = "fail_round1_set_tool_rejected"
  FAIL_ROUND1_PLAN_STATE_INCOMPLETE    = "fail_round1_plan_state_incomplete"

  # evaluate_plan
  FAIL_EVALUATE_PLAN_EXCEPTION         = "fail_evaluate_plan_exception"
  FAIL_EVALUATE_PLAN_MALFORMED         = "fail_evaluate_plan_malformed"

  # cascade_walk
  FAIL_CASCADE_MODE_UNKNOWN            = "fail_cascade_mode_unknown"
  FAIL_CASCADE_TIER_UNKNOWN            = "fail_cascade_tier_unknown"
  FAIL_CASCADE_HALTED_WITHOUT_RESOLUTION = "fail_cascade_halted_without_resolution"

  # floor_invocation
  # NOTE: no FAIL_FLOOR_BUDGET_EXCEEDED. The §9.2 floor primitives are
  # one-shot deterministic computations dispatched by
  # ``floor_for_mode``; there is no loop and therefore no budget to
  # exhaust. Only the per-primitive exception path is guarded.
  FAIL_FLOOR_PRIMITIVE_FAILED          = "fail_floor_primitive_failed"

  # session_terminated
  FAIL_SESSION_TERMINAL_STATE_UNKNOWN  = "fail_session_terminal_state_unknown"

  # finmo_sync
  FAIL_FINMO_NO_QUARTER_ROWS           = "fail_finmo_no_quarter_rows"
  FAIL_FINMO_SCHEMA_MISSING            = "fail_finmo_schema_missing"

  # target_seeking
  FAIL_TARGET_SEEKING_MODE_UNKNOWN     = "fail_target_seeking_mode_unknown"
  FAIL_TARGET_SEEKING_REASON_UNKNOWN   = "fail_target_seeking_reason_unknown"

  # cash_pass
  FAIL_CASH_PASS_RESULT_MALFORMED      = "fail_cash_pass_result_malformed"

  # realism_gate
  FAIL_REALISM_BAND_SOURCE_MISSING     = "fail_realism_band_source_missing"
  FAIL_REALISM_COUNT_MISMATCH          = "fail_realism_count_mismatch"

  # finalize
  FAIL_FINALIZE_STAGE_NOT_FINALIZED    = "fail_finalize_stage_not_finalized"

  # workbook_accept
  FAIL_WORKBOOK_ACCEPT_NO_RUN_ID       = "fail_workbook_accept_no_run_id"
  FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID     = "fail_workbook_accept_no_draft_id"
```

A `FAIL_FAST_CODES_BY_PHASE: Dict[PhaseCode, FrozenSet[FailFastCode]]`
mirror partitions this set the same way `EVENT_CODES_BY_PHASE` does,
and a `raise_fail_fast(conn, *, draft_id, planning_run_id, phase, code,
detail, cause=None)` helper in `fail_fast.py` emits the audit row then
re-raises.

---

## 2. Per-phase inventory

For each item: **(Invariant) → (FailFastCode) → (assertion site)**.

### 2.1 `cohort_bands_populator`

1. **Cohort bands exist for the draft's resolved industry / cohort.**
   `FAIL_COHORT_BANDS_MISSING`. Site:
   `post_intake_cohort_bands/runner.py` after the populator's INSERT
   loop, when `SELECT COUNT(*) FROM post_intake_cohort_bands WHERE
   draft_id=...` is zero.

2. **Each row's band columns parse as `[float, float]` ranges.**
   `FAIL_COHORT_BANDS_MALFORMED`. Site: same module, immediately after
   row writes (validate before COMMIT).

### 2.2 `mirror_build`

3. **`mirror.plan_state` is a dict on every read.**
   `FAIL_MIRROR_PLAN_STATE_NOT_DICT`. Site:
   `post_intake_amalgamated/mirror/mirror.py::ensure_plan_state` (new
   guard); also asserted at the top of `_walk_cascade` and `_evaluate`
   in `session_driver.py`.

4. **Cohort bands have been resolved into `mirror.bands` before the
   session opens.** `FAIL_MIRROR_BANDS_UNRESOLVED`. Site:
   `post_intake_amalgamated/session/factory.py::build_amalgamated_session`
   after the bands lookup returns no rows.

5. **Baseline FINMO builds without exception during mirror
   construction.** `FAIL_MIRROR_FINMO_BASELINE_BUILD`. Site: same
   factory, where the FINMO baseline is requested before round-1.

### 2.3 `round1_authoring`

6. **Every set_* tool invoked with `contract=None` returns
   `accepted=True` for the THREE round-1 sections.**
   `FAIL_ROUND1_SET_TOOL_REJECTED`. Site:
   `post_intake_solver/orchestrator.py::run_round1_authoring`
   (introduced in Step 8b-fix) — wrap each of
   `set_capex_rd_balance_seed`, `set_stage_ramp_contract`,
   `set_payroll_schedule`. **`set_drivers` is intentionally NOT
   wrapped** — drivers are not authored in round-1; the cascade
   authors them via `revise_drivers`, and
   `set_drivers(anchors=None)` returns
   `accepted=False / "amalgamated_session_pending"` by design.

7. **After round-1, `mirror.plan_state` carries non-empty sections:
   `capex_rd_balance_seed`, `stage_ramp`, `payroll`.**
   `FAIL_ROUND1_PLAN_STATE_INCOMPLETE`. Site: same wrapper, at the
   end of round-1 (post-set, pre-session open). Section keys match
   the `"section": "<key>"` field returned by each set_* tool's
   envelope (verified by grep against the tools' source). Drivers
   being empty post-round-1 is the design and must NOT trigger this
   invariant.

### 2.4 `evaluate_plan`

8. **`_evaluate` returns a dict with `passed: bool` plus
   `failures: List[Dict]`.** `FAIL_EVALUATE_PLAN_MALFORMED`. Site:
   `session_driver.py::_evaluate` postcondition guard.

9. **`_evaluate` does not raise.** `FAIL_EVALUATE_PLAN_EXCEPTION`.
   Site: a `try` in `session_driver.py::run` that wraps the
   `_evaluate()` call.

### 2.5 `cascade_walk`

10. **Dispatched mode is a registered key in
    `CASCADES_BY_MODE`.** `FAIL_CASCADE_MODE_UNKNOWN`. Site:
    `session_driver.py::_walk_cascade` entry.

11. **Each tier name walked is registered for the dispatched mode.**
    `FAIL_CASCADE_TIER_UNKNOWN`. Site: `_walk_cascade` per-tier loop.

12. **On `cascade_exhausted`, control transfers to floor — never
    silently returns.** `FAIL_CASCADE_HALTED_WITHOUT_RESOLUTION`.
    Site: `session_driver.py::run` post-cascade dispatch.

### 2.6 `floor_invocation`

13. *(DROPPED.)* There is no FLOOR_BUDGET to enforce. The §9.2
    floor primitives in `protocol/floor.py` are one-shot
    deterministic computations dispatched by `floor_for_mode`; they
    do not loop, so termination is guaranteed by construction.

14. **Floor primitives apply cleanly (no exception in the §9.2
    primitives).** `FAIL_FLOOR_PRIMITIVE_FAILED`. Site: `floor.py`
    per-primitive wrap inside `apply_floor_primitive` /
    `floor_for_mode`.

### 2.7 `session_terminated`

15. **Terminal state ∈ `{RESOLVED, MODE_FLOOR, STAGNATION_FLOOR_ALL,
    META_HALTED, BUDGET_EXHAUSTED_FLOOR}`** — the exact attribute
    names on
    `post_intake_amalgamated/protocol/session_driver.py::TerminationState`.
    There is no `EXCEPTION_HALTED` (it was removed in Step 8b-fix).
    `FAIL_SESSION_TERMINAL_STATE_UNKNOWN`. Site:
    `session_driver.py::_terminate`, guarded at entry against the
    `TerminationState` class attribute set.

### 2.8 `finmo_sync`

16. **`build_python_finmo_json` returns `quarter_rows` non-empty.**
    `FAIL_FINMO_NO_QUARTER_ROWS`. Site:
    `post_intake_amalgamated/finmo_sync.py` post-build.

17. **FINMO row schema carries the required columns (period,
    revenue, gross_profit, op_income, cash_end).**
    `FAIL_FINMO_SCHEMA_MISSING`. Site: same module.

### 2.9 `target_seeking`

18. **`planning_mode ∈ {growth, stability, runway_extension,
    survival}` at entry.** `FAIL_TARGET_SEEKING_MODE_UNKNOWN`. Site:
    `post_intake_solver/orchestrator.py::
    run_target_seeking_orchestrated_system_run` after planning_mode
    resolution (uses the same lookup table as §11.4 of the spec).

19. **Hard-fail reason codes accumulated through the cascade are
    members of `REASON_CODES`.**
    `FAIL_TARGET_SEEKING_REASON_UNKNOWN`. Site: same orchestrator,
    after `run_adaptation_cascade` returns.

### 2.10 `cash_pass`

20. **`run_mode_based_cash_strategy` returns a `CashStrategyResult`
    with `applied_updates_count: int ≥ 0`.**
    `FAIL_CASH_PASS_RESULT_MALFORMED`. Site:
    `orchestrator.py::_run_post_cascade_completion` immediately after
    the cash-strategy call (already inside the existing instrumented
    `with` block).

### 2.11 `realism_gate`

21. **Every result row carries `band_source` provenance.**
    `FAIL_REALISM_BAND_SOURCE_MISSING`. Site:
    `orchestrator.py::_run_post_cascade_completion` after
    `validate_industry_realism_bands` returns (whether or not it
    raised `RealismBandViolation`).

22. **`result_count == checked_metric_count + skipped_metric_count`
    OR all three are zero.** `FAIL_REALISM_COUNT_MISMATCH`. Site:
    same callsite.

### 2.12 `finalize`

23. **After `run_finalize_post_intake_validation` returns
    successfully, `planning_run.current_stage == 'finalized'`.**
    `FAIL_FINALIZE_STAGE_NOT_FINALIZED`. Site:
    `orchestrator.py::_run_post_cascade_completion` finalize block.

### 2.13 `workbook_accept`

24. **`resolved_run_id` is a non-empty string at entry.**
    `FAIL_WORKBOOK_ACCEPT_NO_RUN_ID`. Site:
    `post_intake_acceptance/gate.py::verify_run_acceptance` near top
    after `_planning_run_row`.

25. **`d_id` is non-empty — already enforced by the existing
    `acceptance_gate_draft_id_required` raise (line 675). Upgrade
    that raise to use the FailFastCode prefix.**
    `FAIL_WORKBOOK_ACCEPT_NO_DRAFT_ID`. Site: same function, line 675.

---

## 3. Implementation plan (Step 9d-implementation)

The implementation sub-commit will:

1. Add `post_intake_diagnostics/fail_fast_codes.py` with the enum,
   the per-phase partition, and a `raise_fail_fast(...)` helper that
   wraps the safe-emit + re-raise pattern.

2. Wire each numbered invariant to its site by adding a guard. The
   guards are small (≤8 lines each). Most are postcondition checks
   on values already in hand at the relevant line.

3. Tests:
   - `test_phase_9_p3_33_phase3_step9d_fail_fast_codes.py` —
     enum closure + partition completeness (every code appears in
     exactly one phase's frozenset).
   - `test_phase_9_p3_33_phase3_step9d_fail_fast_helper.py` —
     `raise_fail_fast` emits the audit row AND re-raises with the
     expected message prefix.
   - `test_phase_9_p3_33_phase3_step9d_fail_fast_sites.py` —
     source-shape regression: each of the **24** numbered sites
     contains a reference to its FailFastCode.

The implementation sub-commit is expected at ~400-600 LOC (one new
module + ~24 small guards + 3 test files). Stays under the 800 cap.

**Total fail-fast points after corrections: 24** (was 25; item 13
dropped — see §2.6).

---

## 4. What is **not** in scope

- Adding observability for invariants that are not strictly
  pipeline-halting (those remain warnings in the diagnostic stream).
- Reworking the cascade dispatch, floor walker, or solver loop bodies
  — only their **boundary postconditions** are guarded here.
- Phase 4 (cloud-Claude audit + structured verification). This
  inventory is the last documentation artifact before STOP.
