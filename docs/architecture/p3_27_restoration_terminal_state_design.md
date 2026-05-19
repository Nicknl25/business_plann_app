# P3.27 — Restoration loop terminal state design

**Scope:** Read-only investigation. No fixes.

**Goal:** Determine whether `RestorationStatus.ITERATING_STILL` is a
meaningful distinct terminal state or an artifact that should be
collapsed into `EXHAUSTED`.

**Source:** [restoration_loop.py](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py)
(branch `intake-stable`, HEAD at this read).

---

## Q1 — Exact terminal-state entry conditions

Each terminal state is produced by exactly one `return RestorationResult(...)`
site in `run_restoration_loop`. The four return sites and their guards:

### LANDED — [restoration_loop.py:1159-1168](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1159-L1168)

Guard: [restoration_loop.py:1109](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1109) *and*
forward-looking classifier returns `None` at
[restoration_loop.py:1128-1137](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1128-L1137).

Conditions, AND-joined:

1. `all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS)`
   — all 6 trajectory checks pass on `build_finmo(model_input)` after
   the pass's 3-target sweep
   ([restoration_loop.py:73-83](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L73-L83)).
2. `_classify_forecast_exhaustion(...)` returns `(None, [])` — the
   realism validator's `hard_fail_violations` contains no entries whose
   primary_levers are all GPT-authorable
   ([restoration_loop.py:956-959](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L956-L959)).

### EXHAUSTED (forecast-driven, on the viability-passed branch) — [restoration_loop.py:1138-1157](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1138-L1157)

Same outer guard as LANDED (all 6 viability checks pass), but
`_classify_forecast_exhaustion` returns a non-None scope, meaning the
post-restoration FINMO would hard-fail at least one GPT-authorable
realism band check.

### EXHAUSTED (formal) — [restoration_loop.py:1170-1179](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1170-L1179) + [restoration_loop.py:1242-1253](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1242-L1253)

```
formal_exhaustion = bool(all_drivers) and all(
  lid in drivers_at_bounds_summary for lid in all_drivers
)
```

— *every* lever across all 3 targets' `driver_bounds` keys is recorded
as bound-pinned in `drivers_at_bounds_summary` (rolled forward across
all targets attempted so far). This is the original doctrine
definition: "every operating driver in every target's driver list is
pinned at its bound" ([restoration_loop.py:21-25 docstring](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L21-L25)).

### EXHAUSTED (semantic) — [restoration_loop.py:1181-1202](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1181-L1202) + [restoration_loop.py:1242-1253](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1242-L1253)

```
targets_attempted_count = len([t for t in pass_diag.targets_attempted
  if t.status in ("bound_pinned", "converged", "max_inner_iterations_reached")])
semantic_exhaustion = (
  bool(targets_attempted_count)
  and (len(targets_bound_pinned) + len(targets_converged)
       + len(targets_max_inner_iters)) >= targets_attempted_count
  and (len(targets_bound_pinned) + len(targets_max_inner_iters)) >= 1
  and not all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS)
)
```

— added in P3.5 [`3f22d3a`](https://github.com/) to cover "every target
returned a terminal solver status this pass and at least one was
bound-pinned or hit max inner iters; yet viability still fails." Added
because formal exhaustion (every lever across all 3 targets pinned)
almost never fires in practice — a single un-pinned lever on a single
target defeats it. P3.26 F-2 added `targets_max_inner_iters` to the
count.

### ITERATING_STILL — [restoration_loop.py:1284-1295](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1284-L1295)

The fall-through return: the `for outer_pass in range(1, MAX_OUTER_PASSES + 1):`
loop exited without `return`-ing LANDED or EXHAUSTED on any pass.
Means: 5 outer passes ran, every pass found `final_viability` failing
*and* failed to satisfy *either* `formal_exhaustion` *or*
`semantic_exhaustion`.

### FAILED — [restoration_loop.py:1067-1073](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1067-L1073)

`CashPassLeverViolation` raised by an inner `solve_for_target`. Defensive
— `_driver_bounds_for_target` already excludes cash-pass-owned levers
at line 714. Effectively dead in the steady state.

---

## Q2 — Semantic distinction: what does ITERATING_STILL mean that EXHAUSTED doesn't?

In doctrine terms, the four exit conditions partition the loop's
outcomes thus:

| Status            | Viability landed? | Deterministic algebra status |
| ----------------- | ----------------- | ---------------------------- |
| LANDED            | YES               | No GPT-authorable forecast failure (clean exit) |
| EXHAUSTED (fc)    | YES               | Forecast hard-fails — needs Handler / GPT |
| EXHAUSTED (formal)| NO                | Every lever across all targets pinned at bound |
| EXHAUSTED (sem.)  | NO                | Every target returned a terminal solver status; at least one pinned/max-iter |
| ITERATING_STILL   | NO                | At least one target on at least one pass returned a NON-terminal status (no bound-pin, no convergence, no max-inner-iters) |

So the strict semantic claim ITERATING_STILL makes is:

> "I ran my 5-pass budget, never reached viability, and at no pass did
> the deterministic algebra fully terminate. There is at least one
> target whose solver returned a status outside
> `{converged, bound_pinned, max_inner_iterations_reached}` —
> typically `targets_attempted` entries that were skipped with
> `no_driver_bounds_resolved`, or entries the solver returned with
> some intermediate state."

In the original design intent ([restoration_loop.py:10-30 module docstring](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L10-L30)):

- LANDED = condition (a): "every viability trajectory check passes."
- EXHAUSTED = condition (b): "every operating driver across all 4
  targets is pinned at its bound in the needed direction (true
  exhaustion)."
- Worst-case worked through both: "4 targets × 10 inner × 5 outer =
  200 iterations." After that, the docstring's verdict is "lesser
  conditions … MUST iterate further. Per-driver bound diagnostics are
  returned so the user can identify whether the cohort tolerances are
  too tight, the operator's intake has structural issues, or stage
  shift is needed."

ITERATING_STILL is the encoding of that "lesser condition" remainder —
a *diagnostic exit*, not a *progress-blocking exit*. Original intent
was: surface diagnostics for the human, do not silently route the case
on as if the algebra had finished.

**Where the distinction has weakened over time:**

- P3.5 (`3f22d3a`) added the semantic_exhaustion branch, which absorbs
  most of what used to fall to ITERATING_STILL.
- P3.7 (`8a36ed0`) added forward-looking exhaustion classification,
  shifting EXHAUSTED from "no levers move" to "no GPT-authorable
  realism progress is possible".
- P3.26 Commit 1 F-3 populated `scope` + `failing_metrics` on the
  ITERATING_STILL return, and F-1 broadened the orchestrator's Site 1
  trigger to engage Handler / Site 1 GPT exhaustion handler on
  `ITERATING_STILL` with non-empty `failing_metrics`
  ([orchestrator.py:1977-1987](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977-L1987)).

After P3.26 Commit 1, the handler-firing decision becomes:

```
EXHAUSTED           → handler fires (existing behavior)
ITERATING_STILL + failing_metrics non-empty → handler fires (P3.26 F-1)
ITERATING_STILL + failing_metrics empty     → handler skipped (P3.26 F-3 design)
LANDED                                       → handler skipped
```

Under this rule, ITERATING_STILL with non-empty `failing_metrics` is
functionally indistinguishable from EXHAUSTED at the orchestrator's
routing layer — both route to the same Site 1 handler with the same
payload (scope + failing_metrics + restoration_result).

The distinction that *remains* meaningful:

1. The diagnostic narrative differs. EXHAUSTED encodes "deterministic
   authority exhausted." ITERATING_STILL encodes "ran out of pass
   budget." A human reading the doctrine-style reason field would
   reach for different remedies: more passes (raise MAX_OUTER_PASSES,
   add an inner-iter budget) vs. different remedies (widen cohort
   bands, shift stage, accept handler escalation).
2. `formal_exhaustion`'s `drivers_at_bounds_summary` is a richer
   diagnostic on the EXHAUSTED path (it tells you *which* levers
   pinned in *which direction*). The ITERATING_STILL path's same
   field tells you what's pinned *so far* — equally rich, but its
   meaning differs (snapshot mid-iteration vs. terminal state).

**Net:** ITERATING_STILL is semantically distinct in *intent* (budget
exhaustion vs. authority exhaustion). Under the post-P3.26-Commit-1
routing rule, the *operational consequence* (which handler fires with
what payload) is identical on the non-empty `failing_metrics` branch.
The empty `failing_metrics` branch is the one differentiator that
matters operationally — it skips the handler. (See Q5 — that branch
never fires in practice for the cases we've inspected; the classifier
will populate `failing_metrics` whenever the post-restore FINMO
hard-fails a GPT-authorable band check.)

---

## Q3 — Original design intent (git history)

```
cfcc3eeb  2026-05-09  phase_9_p3_target_solver_loop
```

The `RestorationStatus` enum was introduced in `cfcc3eeb` with all four
values (LANDED, EXHAUSTED, ITERATING_STILL, FAILED) simultaneously.
ITERATING_STILL was not an afterthought — it shipped on day one of the
restoration loop's existence, alongside the module docstring whose
"iteration discipline" section explicitly contrasts the LANDED and
EXHAUSTED clean-exit conditions with "lesser conditions … MUST iterate
further."

Subsequent commits and their effect on the terminal-state contract:

| Commit     | Date       | Effect on ITERATING_STILL                                  |
| ---------- | ---------- | ---------------------------------------------------------- |
| `cfcc3eeb` | 2026-05-09 | Introduced. Distinct terminal state from the start.        |
| `3f22d3a`  | 2026-05-10 | P3.5 added `semantic_exhaustion` — siphoned cases that used to fall to ITERATING_STILL into EXHAUSTED. |
| `8a36ed0`  | 2026-05-?? | P3.7 added forward-looking classifier — added a new EXHAUSTED entry path (forecast-driven on the viability-passed branch). |
| `26d2002`  | 2026-05-?? | P3.24 Commit 1 (later reverted) — first attempt to broaden orchestrator trigger. |
| `1f0170d`  | 2026-05-18 | P3.26 Commit 1 — F-1 + F-2 + F-3 redesign: ITERATING_STILL populates scope + failing_metrics; orchestrator engages handler on ITERATING_STILL + non-empty failing_metrics. |

Direction-of-change is consistent: every revision has *narrowed* the
operational gap between ITERATING_STILL and EXHAUSTED — first by
expanding EXHAUSTED's entry surface (P3.5, P3.7), then by routing
ITERATING_STILL through the same handler as EXHAUSTED (P3.26 Commit 1).

The state has progressively become more vestigial.

---

## Q4 — Collapse scope estimate

If the user decides ITERATING_STILL is no longer load-bearing and
should be collapsed into EXHAUSTED (with the diagnostic narrative
distinction preserved via `reason` text), the change footprint:

**Code (~20 LOC of churn):**

1. [restoration_loop.py:120-124](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L120-L124) —
   remove `ITERATING_STILL` enum member (or leave as alias for back-compat).
2. [restoration_loop.py:1284-1295](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1284-L1295) —
   change `status=RestorationStatus.ITERATING_STILL` → `EXHAUSTED`, keep
   the existing `reason="max_outer_passes_reached_without_landed_or_exhausted"`
   text and `scope` / `failing_metrics` population. The forecast
   classifier already runs on this path (P3.26 F-3), so the payload is
   ready.
3. [orchestrator.py:1977-1987](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1977-L1987) —
   simplify `_should_engage_handler` back to a single condition
   `status == EXHAUSTED`. Drop the `ITERATING_STILL + failing_metrics`
   disjunct.

**Tests (~30 LOC):**

- [test_phase_9_p3_26.py](../../tests/test_phase_9_p3_26.py) — F-1 +
  F-3 test cases that exercise `ITERATING_STILL` would need to be
  rewritten to assert the collapsed `EXHAUSTED` return. The
  `test_iterating_still_with_empty_failing_metrics_skips` case becomes
  the most interesting question: under the collapsed design, does
  EXHAUSTED with empty `failing_metrics` still skip the handler? If
  yes, the test trivially survives. If no (collapse means handler
  fires on every EXHAUSTED regardless of failing_metrics), this case
  needs a redesign decision.

**Docs (~5 references):**

- [p3_26_verification_results.md](./p3_26_verification_results.md),
  [p3_10_critical_operations_audit.md](../phase_9_p3_10_critical_operations_audit.md),
  [p3_5_consultant_conflict_audit.md](../phase_9_p3_5_consultant_conflict_audit.md),
  [p3_e2e_report.md](../phase_9_p3_e2e_report.md) — all reference the
  state. Mention as historical (Phase 9 P3.27 collapse) and move on.

**Persisted state:** No SQL `intake_consult_drafts` columns or audit
logs store `restoration_status` as a discriminator outside the
diagnostic JSON; the change is doctrinal not schema. JSON diagnostics
will start emitting `status: "exhausted"` where they used to emit
`status: "iterating_still"`, but no consumer downstream branches on
the string (Site 1 handler reads `failing_metrics` + `scope`, not
status string).

**Total estimated scope:** ~50 LOC across code + tests, ~5 doc
references. One commit, no migration. Below the 150 LOC cap.

**One subtlety to flag before collapsing:** the diagnostic split
between "ran out of pass budget" and "exhausted authority" matters for
the *operator-facing* diagnostic — it tells the user whether to
loosen cohort bands or raise the pass budget. If we collapse, the
distinction needs to be preserved in `reason` text and surfaced in
the audit report. P3.27's recommendation should call this out as a
non-functional but stakeholder-facing requirement of the collapse.

---

## Q5 — Today's NexGen: actual return path and pre-Commit-1 handler firing

**Today's path (intake-stable HEAD at 1ad56ec, including P3.26 Commit 1):**

From [`p3_26_nexgen_regression_investigation.md`](./p3_26_nexgen_regression_investigation.md)
§3 — both yesterday (commit `dca4fae`, before P3.26 Commit 1) and
today, NexGen's restoration loop exits via the **EXHAUSTED (semantic)**
branch at [restoration_loop.py:1242-1253](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1242-L1253),
not via ITERATING_STILL.

Evidence quoted from that memo §3:

- Yesterday's `restoration_diagnostics` payload showed
  `status: "exhausted"` with `reason` beginning
  `"every_target_returned_bound_pinned_in_latest_pass …"` — the
  semantic_exhaustion reason string at
  [restoration_loop.py:1221-1226](../../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L1221-L1226).
- Today's restoration_diagnostics under HEAD show identical
  `status: "exhausted"` + same reason prefix. The path is unchanged.

**Pre-Commit-1 handler firing:** Yes, the handler fired on yesterday's
green baseline (`dca4fae`) — because both days the path is EXHAUSTED,
and the orchestrator's pre-Commit-1 trigger already engaged on
EXHAUSTED. P3.26 Commit 1's F-1 broadening (adding ITERATING_STILL +
failing_metrics as a second trigger condition) is **path-incidental
for NexGen** — NexGen never takes the ITERATING_STILL path.

This is the same conclusion P3.26 NexGen investigation reached in §5:
the verification memo's "Commit 1 broadened the trigger" hypothesis is
not the cause of today's NexGen regression. The cause is GPT
non-determinism in handler revenue-driver authoring + handler doesn't
consult `stage_ramp_contract.quarter_ramp_grid.rev_max` QoQ caps, both
of which existed yesterday with the same code paths.

**Implication for the redesign decision:**

If the user reverts P3.26 Commit 1, NexGen's handler will still fire
via EXHAUSTED — so the revert does *not* fix NexGen's revenue-driver
problem. The revert would protect the cases (Anderson & Blake et al.)
that needed F-1 + F-3 to route to the handler at all, at the cost of
leaving NexGen's stage_ramp_contract gap unfixed.

If instead the user keeps P3.26 Commit 1 *and* addresses NexGen
separately (e.g. by giving the handler `stage_ramp_contract` awareness
or by adding `quarter_ramp_grid.rev_max` enforcement to a
post-handler validator), both classes of failure are addressed without
giving up the P3.26 trigger broadening.

---

## Recommendation surface (for user)

Two coherent options, not pre-decided:

**Option A — Revert P3.26 Commit 1 + redesign:** Roll back the F-1 / F-2
/ F-3 trigger broadening and address NexGen's stage_ramp_contract gap
inside the handler module or downstream of it. Loses the
ITERATING_STILL routing for Anderson & Blake-class cases. NexGen is
not fixed by the revert alone.

**Option B — Keep P3.26 Commit 1 + address NexGen separately:** Treat
ITERATING_STILL routing as the right doctrinal posture (which the
git-history direction-of-change supports) and address NexGen via
either (i) handler consults stage_ramp_contract or (ii) post-handler
band validator. NexGen and Anderson & Blake fixed without giving up
the trigger broadening.

**Optional follow-on for either option:** the analysis in Q2-Q4
suggests ITERATING_STILL itself is largely vestigial after P3.26. A
P3.28-class collapse (~50 LOC) would simplify the orchestrator's
trigger logic and the test surface. Not blocking on either option;
just available.

User direction required before any code changes.
