# P3.40 Contract 3 — Pre-implementation impact notes (PI1 + PI2)

Two impact verifications run before Commit 1a per the directive.
Both resolved with no surprises; spec dispositions stand.

---

## PI1. Existing-test impact from the consumer-side gate

**Question:** how many tests in `tests/` invoke either the
orchestrator entry (`run_target_seeking_orchestrated_system_run`)
or its two API-layer wrappers
(`_run_unified_post_grid_system_run`,
`_run_planning_system_for_draft_unified`) directly? Each such
test would need either (a) a fixture update to a valid 21-field
bundle or (b) a fixture-generator helper gate.

### Method

Grep across `tests/` for the three function names:

```
run_target_seeking_orchestrated_system_run
_run_unified_post_grid_system_run
_run_planning_system_for_draft_unified
```

### Result

**Two matches; ZERO are invocations.**

| File:line | What it does |
|---|---|
| [tests/test_phase_9_p3_10_iter_12_blind_spot_diagnostic.py:218](../../tests/test_phase_9_p3_10_iter_12_blind_spot_diagnostic.py#L218) | `self.assertTrue(callable(orchestrator.run_target_seeking_orchestrated_system_run))` — pure import-and-existence check. Does not invoke. |
| [tests/test_phase_9_p3_33_remediation_commit5.py:11-12](../../tests/test_phase_9_p3_33_remediation_commit5.py#L11-L12) | Reference inside the file's module docstring documenting a call chain that involves these symbols. Tests in the file inspect `inspect.getsource(...)` of three helper functions to confirm their `C4 audit` comments are intact. Does not invoke the orchestrator. |

### Disposition

**Zero fixture updates required.** The Commit 3 consumer-side gate
wiring will not break any existing test under the suite as it
stands today. The Adjustment B end-to-end test in Commit 3 will
be the FIRST test in the suite to actually invoke the orchestrator
entry path — and it does so deliberately to verify the
ContractViolation propagation.

**Test-update workload for Commit 3:** none beyond writing the
new tests the spec calls for. No "Commit 3a / 3b" test-churn
split needed.

---

## PI2. Flag 8(a) `planning_run_id` tightening — production-caller safety

**Question:** the spec's Flag 8(a) tightens `planning_run_id` from
`Optional[str]` to `str = Field(min_length=1)`. Are any legitimate
production callers passing `None` or `""` today? If yes, the
tightening would convert a silently-skipped persist into a 500
HTTP response — needs re-decision on 8(a) before Commit 1a.

### Method

Trace the `planning_run_id` argument value backward from the
orchestrator entry through:

1. `_run_unified_post_grid_system_run` at
   [intake_consult.py:6962](../../python/api_handlers/intake_consult.py#L6962).
2. `_run_planning_system_for_draft_unified` at
   [intake_consult.py:7039](../../python/api_handlers/intake_consult.py#L7039).
3. `prepare_initial_grid_for_draft` at
   [post_intake_initial_grid/runner.py:30+](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30).
4. The HTTP entry point at
   [intake_consult.py:7261+](../../python/api_handlers/intake_consult.py#L7261).

### Result — production callers cannot reach the gate with empty planning_run_id

The decisive fact is at **runner.py:83-85**:

```python
active_planning_run_id = str(active_planning_run.get("planning_run_id") or "").strip()
if not active_planning_run_id:
  raise RuntimeError("planning_run_start_failed")
```

`prepare_initial_grid_for_draft` raises `RuntimeError("planning_run_start_failed")`
at the top of the function if the lifecycle-start handshake does
not produce a non-empty `planning_run_id`. The bundle return at
[runner.py:1830](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1830)
therefore always carries a non-empty `planning_run_id`. The two
API-layer wrappers do `str(initial_grid_state.get("planning_run_id") or "").strip()`
at [intake_consult.py:7102](../../python/api_handlers/intake_consult.py#L7102),
which preserves the non-empty guarantee.

### What the tightening still catches

The tightening is a **pure defense-in-depth** check. It catches
any future call path that bypasses the runner — replay tooling,
test harnesses, refactors that invoke the orchestrator directly,
etc. — and would otherwise silently skip the persist layer at
[orchestrator.py:3609](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L3609).

The runner-level RuntimeError at line 83-85 and the contract-level
ContractViolation at the gate are two checks against the same
invariant ("planning_run_id is required by the time we enter the
solver"). They live at different boundaries:

- Runner gate: raised before the initial-grid build runs.
- Contract gate: raised before the orchestrator body executes.

Both must hold. A refactor that moves work between these two
boundaries should preserve both. Per the directive, the principled
disposition is keep both.

### Disposition

**Flag 8(a) tightening stays as recommended.** No production caller
breaks. The contract-level check is additional defense-in-depth on
top of the runner-level check; the two gates protect the same
invariant at adjacent boundaries.

---

## Pre-implementation summary

- **Test-impact for Commit 3: zero fixture updates** beyond the
  new tests the spec calls for. The 12-15 Commit 3 tests target
  is unchanged.
- **Flag 8(a) tightening: production-safe.** Runner-level
  RuntimeError at runner.py:83-85 guarantees no production path
  reaches the orchestrator with an empty `planning_run_id` today.
  Contract-level check is the defense-in-depth complement.

Both PIs resolved with no spec changes. Proceeding to Commit 1a.
