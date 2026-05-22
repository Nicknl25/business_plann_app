# P3.32 — Adaptive / Self-Healing Infrastructure Design Memo

**Status:** Design only. No implementation this iter. Companion to
[p3_32_k11_deep_four_draft_analysis.md](p3_32_k11_deep_four_draft_analysis.md),
which supplies the empirical basis (12 drafts × 3 runs; 7/37 completed;
luck-dependent passes; systemic B1/B2/B5 failures).

The user is building toward a system that **preempts** problems rather
than discovering them mid-sweep. This memo states what such a system
requires, grounded in the batch evidence and the doctrine §1 constraint
(Python-deterministic-first; GPT as authoring source, not as the
control loop).

---

## 0. What the batch proved the architecture lacks

Three independent GPT authoring surfaces decide whether a run lands:

- **H4** — stage_ramp contract (per-quarter revenue ramp + bound grid).
- **Handler C** — payroll/headcount schedule.
- **H2** — P&L drivers (price, capacity, utilization, cost ratios).

None has a **deterministic floor**: a Python-computed feasible
configuration committed when GPT fails to find one. So a run lands only
when all three independent explorations *happen* to succeed and *happen*
to agree (the H4↔H2 revenue reconciliation, fault B1). Outcome is the
product of three stochastic processes → identical inputs flip
(CareFirst 2/3, Luna 2/3, SwiftCargo's failure-mode itself varying).

**Consistency cannot be achieved by prompt tuning.** It requires
deterministic floors on each authoring surface and a deterministic
bridge between surfaces. That is the spine of the adaptive system.

---

## P5.1 — Runtime adaptation patterns (within doctrine §1)

What the system may do mid-run *without* putting GPT in the control loop:

1. **Deterministic floor on GPT non-convergence (Pattern 2 core).**
   When an authoring handler exhausts its budget without a
   validator-accepted output, a Python proposer computes an in-bounds
   feasible configuration and commits it (or seeds the next GPT turn
   with it). GPT proposes; Python guarantees a floor. Applies to H4
   (B5), Handler C (B3), and H2 (G3/no-viability-floor).

2. **Cross-surface deterministic reconciliation.** After H2 commits
   drivers, a Python step reconciles driver-implied revenue to the H4
   ramp within bounds, instead of trusting two GPT surfaces to agree
   (fault B1). This is adaptation *between* handlers, not within one.

3. **Constraint relaxation when the feasible region is provably empty.**
   If a Python feasibility check shows no in-bounds configuration can
   satisfy every constraint simultaneously, the system deterministically
   relaxes the lowest-priority bound (by a declared priority order) and
   records the relaxation — rather than letting GPT thrash to a timeout.

4. **Handler re-invocation with enriched context** (already partially
   present via K1 F5/F7): on a structured violation, re-invoke the
   canonical handler with the precise violation + repair direction,
   bounded by a re-invocation cap.

5. **Latency-aware turn budgeting** (fault B2): when an OpenAI turn
   approaches the read-timeout, the system should degrade to a smaller
   context / Python proposal rather than burning the full 3× retry
   budget on a doomed 140 s wait.

---

## P5.2 — Self-healing patterns (canonical repair paths)

When a violation is detected, the repair path should be **declarative
and per-violation**, not ad-hoc:

- **Validator-with-handler-routing:** each invariant declares its
  canonical repair handler (K1 F5 is one instance). A registry maps
  `violation_code → (handler, max_attempts, deterministic_floor_fn)`.
- **Floor-backed handlers:** every handler in that registry must have a
  `deterministic_floor_fn` so routing always terminates in a committed,
  in-bounds state — never in exhaustion-without-output (the B3/B5
  failures).
- **Idempotent re-application:** repairs must be safe to re-run (K1 F6
  resync invariant) so a heal step can't corrupt coherent state.

The L-4 trace sink already records, per call, the violation set and the
runtime status (distance-to-feasibility); the heal layer consumes that
same signal.

---

## P5.3 — Preemptive detection patterns (recognize fragility before failure)

The L-4 instrumentation (this iter) is the substrate. Built now and used
in this investigation:

- **Distance-to-feasibility** — `record_runtime_status` emits the count
  and identity of failing checks per probe. A run hovering at
  distance 2 (e.g. Sunny's persistent `rev_max` + `ni_floor`) is
  flagged fragile *before* finalize rejects it.
- **Convergence-trajectory analysis** — H2 probe-over-probe: is
  distance monotonically decreasing, or oscillating (Sunny calls 6→9)?
  Oscillation predicts a best-effort no-all_pass landing → B1.
- **Constraint-margin tracking** — committed values vs each bound; a
  draft operating *at* a bound (zero margin) is fragile by definition.
- **Latency-margin tracking** — Handler C turn latency vs read-timeout
  (the C5 profile: 32 s against a 45 s ceiling = B2 risk) flags
  timeout-prone runs preemptively.
- **Cross-run consistency check** — same-source variance (Part A)
  surfaces luck-dependence as a first-class metric, not an anecdote.

A preemptive controller reads these signals mid-run and triggers the
P5.1 adaptations (floor, reconcile, relax) *before* the run reaches a
failing terminal gate.

---

## P5.4 — Doctrine evolution (proposed §10.6 onward)

- **§10.6 — Deterministic floor invariant.** Every GPT authoring
  surface MUST have a Python deterministic floor that produces a
  validator-accepted output when GPT does not. No run may terminate in
  "handler exhausted without output." (Closes B3/B5; the structural
  cause of luck-dependence.)
- **§10.7 — Cross-surface reconciliation invariant.** Where two GPT
  surfaces author values the validator cross-checks (H4 revenue ramp ↔
  H2 driver-implied revenue), a deterministic Python reconciliation MUST
  bridge them; agreement may not be left to chance. (Closes B1.)
- **§10.8 — Preemptive fragility metrics.** Handlers MUST emit
  distance-to-feasibility, constraint margin, and latency margin during
  execution (L-4 substrate). Fragility is detected from these, not from
  terminal failure.
- **§10.9 — Consistency as an acceptance property.** A draft is
  "passing" only if it passes deterministically (or N/N under repeat).
  A 2/3 outcome is a FAILING draft with a latent fault, not a pass.

---

## Implementation sequencing (subsequent iters)

1. **G-B2** latency tolerance (config) — unblocks runs to reveal true
   fault rates.
2. **§10.6 floors** on H4, Handler C, H2 (Pattern 2) — converts luck to
   guarantee; closes B3/B5/G3.
3. **§10.7 reconciliation** (B1) — closes the dominant fault.
4. **§10.8 preemptive controller** — consumes L-4 signals to adapt
   mid-run.
5. Re-run the 12×3 batch; target N/N completion as the §10.9 acceptance
   bar.

The L-4 instrumentation shipped this iter is the foundation for steps
3–5: the signals the preemptive controller needs are already being
persisted per call.
