# Phase 9 P3.5 — Phase 3 Consultant / Solver-Loop Architecture Conflict Audit

**Audit date:** 2026-05-10
**Triggered by:** Sunny v3 system run on commit d506e89 returning
`cascade_landed_tier: 0`, `plan_confidence: high_no_adaptation`,
`restoration_loop.status: iterating_still`, Q11 EBITDA = -0.51, with the
new GPT exhaustion handler short-circuited at Call 1 by
`python_proposer_only_budget_exhausted`.

**Scope:** Diagnostic only. NO code changes proposed in this audit. The
fix path is captured at the end as a recommendation; commit + apply
decisions are deferred to the user.

---

## TL;DR

The Phase 9 P3.5 commits did not change the pipeline ordering, did not
add Phase 3 consultant invocations, and did not modify the cascade or
restoration loop. They modified `_gpt_critic_io.py` in two ways:

1. **Removed the `seed` parameter from the OpenAI Responses API
   payload** (commit 9fa5b08). The Responses API rejects `seed` with
   HTTP 400 (`unknown_parameter`), confirmed live against
   `https://api.openai.com/v1/responses` today. Before this fix every
   call routed through `call_gpt_with_schema_or_fallback` got HTTP 400
   and returned `python_proposer_only_critic_http_error`.
2. **Raised the per-run GPT call budget cap from 4 to 8** (commit
   fdb782d / 9fa5b08).

The seed parameter was present in the payload at every prior commit
(73b71ee, 272c0a2, 4a09142, etc.). Because the Responses API rejects
it, **every Phase 3 consultant call in those prior commits returned
the python-proposer-only fallback**. Phase 3 consultants were
*structurally dormant* — they were on the call graph, made HTTP
requests, and recorded fallback decision_sources, but they never
produced GPT-amended output. The `envelope_payload` and
`targets_payload` consumed downstream were always the deterministic
Python defaults.

Removing `seed` flipped them on. The 16/16 ExpressLogix passes in
73b71ee, 272c0a2, and 4a09142 happened with consultants dormant — i.e.
in the architectural state the user designed (deterministic algebra
owns operating-driver adaptation; GPT confined to intake / cash
strategy / path engine ramps / new exhaustion handler).

After the seed fix, three Phase 3 consultants now actively make
per-scope GPT calls (per-lever / per-metric / per-conflict) before
the cascade and restoration loop run, and amend bands and targets
that downstream pre-flight + cascade + post-cascade target-seeking
passes consume to write to model_input. **That is GPT in the solver
loop, which violates the architecture.**

---

## Investigation 1 — Phase 3 consultants: pipeline position, writes,
and downstream readers

Three consultants live in the post-intake solver path:

### 1. `consultant_band_shaping.py` — `calibrate_driver_movement_envelope_with_gpt`

**Pipeline position:** orchestrator.py:917 — runs after
`assemble_driver_movement_envelope` builds the deterministic Python
envelope from NAICS bands + applicability + mapping bounds.
Invoked once; iterates internally per applicable, non-schedule-locked
lever.

**Per-call scope:** one GPT call per lever_id with
`decision_source = "driver_movement_envelope_calibration"`.
For Sunny (NAICS 311811) the deterministic assembler produces 26
drivers, of which 19 are applicable + non-schedule-locked. **Up to 19
GPT calls per draft from this consultant**, plus retry-on-fallback
overhead.

**Writes:** AMENDS `envelope_payload.drivers[lever_id]` in place. For
each amended lever the consultant overwrites `min_allowed`,
`max_allowed`, `default_value`, and (when the lever has a declared
applicability rule) `applicable`. Stamps
`provenance.calibration_source = "gpt_calibrated"` and stashes the
Python default under `provenance.python_default`.
Code: consultant_band_shaping.py:155-189 (`_apply_amendment`).

**Downstream readers:**
- `_run_target_seeking_pass(pass_label="pre_flight", envelope_payload=...)` —
  orchestrator.py:1036-1048. The pre-flight pass uses the envelope to
  bound driver movements and writes those movements to model_input
  through `apply_lever_callable`.
- `run_adaptation_cascade(envelope_payload=envelope_payload_post, …)` —
  orchestrator.py:1218-1234. The cascade uses the envelope to determine
  what tier to land at and whether driver bounds permit movement to
  satisfy targets.
- `_run_target_seeking_pass(pass_label="post_cascade", …)` inside
  `_run_post_cascade_completion`. Reads `envelope_payload_post` again
  and writes more driver movements to model_input.
- `_hard_fail_violations_from_assertion` uses
  `envelope_payload_post`'s drivers list to evaluate hard fails.

### 2. `consultant_target_shaping.py` — `calibrate_finmo_output_targets_with_gpt`

**Pipeline position:** orchestrator.py:956-963 — runs after
`assemble_finmo_output_targets` builds the deterministic targets
payload from NAICS metric bands. Invoked once; iterates internally
per metric.

**Per-call scope:** one GPT call per metric_key with
`decision_source = "finmo_output_target_calibration"`.
For Sunny, `assemble_finmo_output_targets` produces **33 target
metrics**. **Up to 33 GPT calls per draft from this consultant**.

**Writes:** AMENDS `targets_payload.metrics[metric_key]` in place.
For each amended metric the consultant overwrites `target_min`,
`target_target`, `target_max`. Stamps
`provenance.calibration_source = "gpt_calibrated"`.
Code: consultant_target_shaping.py:114-152 (`_apply_metric_amendment`).

**Downstream readers:**
- `_run_target_seeking_pass(targets_payload=…)` — both pre-flight and
  post-cascade passes. The target-seeking loop drives drivers toward
  `target_target` within `[target_min, target_max]`, writing per-quarter
  values to model_input via `apply_lever_callable`.
- `_hard_fail_violations_from_assertion(targets_payload=…)` — used at
  orchestrator.py:1103-1107 to determine whether the post-flight repair
  pass / cascade fires.
- `run_adaptation_cascade(targets_payload=targets_payload_post, …)` —
  the cascade uses target bands to decide what tier action (walk back,
  widen, etc.) to apply.
- **Realism gate** — `validate_industry_realism_bands` reads
  `solver_input_targets_payload` (extracted from
  `model_input.solver_input[FINMO_OUTPUT_TARGET_KEY]`) and prefers
  Phase 3 calibrated bands over NAICS baselines. Phase 3 amendments
  here propagate directly to the gate's pass/fail evaluation.

### 3. `consultant_conflict_adjudication.py` — `adjudicate_intake_vs_band_conflicts_with_gpt`

**Pipeline position:** orchestrator.py:932-942 — runs after band shaping,
when intake-implied values for some levers have fallen outside the
calibrated band. Invoked once; iterates internally per detected
conflict.

**Per-call scope:** one GPT call per conflict, with three legal
decisions: `keep_intake` (widen the band to include intake),
`keep_band` (intake value is implausible — use band default for Q1+),
`split` (Q0 stays at intake, Q1+ uses band default).
**Variable count per draft** — typically 3-10 conflicts depending on
how far operator intake is from cohort medians.

**Writes:** AMENDS `envelope_payload.drivers[lever_id]` in place
based on the decision. `keep_intake` widens the band;
`keep_band` / `split` adjust the Q0/Q1+ provenance hint without
changing the band itself. Stamps
`provenance.calibration_source = "gpt_calibrated"`.

**Downstream readers:** same as band shaping — every place that reads
`envelope_payload`.

### Summary table

| Consultant | Iterates over | Sunny per-draft calls | Writes to | Read by |
|---|---|---|---|---|
| band_shaping | applicable, non-schedule-locked drivers | up to 19 | `envelope_payload.drivers[lever_id]` (`min/max/default/applicable`) | pre-flight, cascade, post-cascade target-seeking |
| target_shaping | every output target metric | up to 33 | `targets_payload.metrics[metric_key]` (`target_min/target/max`) | pre-flight, cascade, post-cascade target-seeking, realism gate |
| conflict_adjudication | detected intake-vs-band conflicts | ~3-10 | `envelope_payload.drivers[lever_id]` (band widen + provenance) | same as band_shaping |

**None of the three writes directly to `model_input`.** They write to
the calibration payloads (`envelope_payload`, `targets_payload`).
Those payloads are the inputs to passes that DO write to model_input
(pre-flight target seeking, cascade, post-cascade target seeking).

The architectural concern in the user's framing is exact: the
deterministic solver loop reads payloads that GPT just amended — so
GPT's per-scope decisions shape what the deterministic algebra is
permitted to do, before it runs. The "deterministic algebra owns
all operating-driver adaptation" rule is observed only when the
consultants are dormant.

---

## Investigation 2 — Did the seed fix change pipeline ordering or
just unmask existing calls?

**Conclusion: just unmask.** The Phase 9 P3.5 commits did not move,
add, or remove any consultant-invocation site.

Concrete evidence — `git diff 4a09142..HEAD`:

| File | Change |
|---|---|
| `python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/__init__.py` (new) | New module, 41 lines. |
| `…/handler.py` (new) | New module, 440 lines. |
| `…/handler_runtime.py` (new) | New module, 344 lines. |
| `…/iteration_runtime.py` (new) | New module, 488 lines. |
| `…/prompts.py` (new) | New module, 261 lines. |
| `…/validators.py` (new) | New module, 125 lines. |
| `post_intake_realism/validator.py` | +32 lines: per-draft `_muted_realism_metrics` plumbing. New behavior. No removals. |
| `post_intake_solver/_gpt_critic_io.py` | -3 / +25 lines net. Removed `seed` parameter. Raised `_GPT_CALL_BUDGET_PER_RUN` from 4 to 8. |
| `post_intake_solver/orchestrator.py` | +64 lines: appended a new branch INSIDE the existing try/except after the restoration loop. The new branch fires only when `restoration_result.status == RestorationStatus.EXHAUSTED`. |
| `scripts/notify_push_email.py` (new) | Email helper, 59 lines. |

The `orchestrator.py` change appended one new branch inside the
existing try/except. It did not move any of the Phase 3 consultant
call sites (orchestrator.py:917, 932, 956 — all unchanged from
4a09142). It did not move the pre-flight pass, the cascade, the path
stamp pass, the restoration loop, the cash strategy, or the realism
gate. The branch I added catches `RestorationStatus.EXHAUSTED` and
nothing else; restoration loop's behavior on the same model_input is
identical to 4a09142.

The `_gpt_critic_io.py` change is the only behavioral change to the
pipeline. The `seed` removal flips the consultants from "dormant
fallback" to "active GPT amendment". Live confirmation against
`https://api.openai.com/v1/responses` today returned status=400 with
`{"error": {"message": "Unknown parameter: 'seed'.", "type":
"invalid_request_error", "param": "seed", "code": "unknown_parameter"}}`
when the payload included `seed: 1729`. Removing the param succeeds.

---

## Investigation 3 — Were Phase 3 consultants silent in the prior
16/16 ExpressLogix passes (73b71ee, 272c0a2, 4a09142)?

**Yes.** Each of those commits had `"seed": _PHASE_3_CONSULTANT_SEED`
in the Responses API payload at `_gpt_critic_io.py`. Confirmed via:

```bash
$ for c in 73b71ee 272c0a2 4a09142; do
    git show $c:python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py \
      | grep -E '"seed":'
  done
```

Every commit returned `"seed": _PHASE_3_CONSULTANT_SEED,`. With the
Responses API rejecting that parameter (verified live), every Phase 3
consultant call in those commits got status=400 and returned
`python_proposer_only_critic_http_error`. The amendments never
applied. Bands and targets stayed at the deterministic Python
defaults across all three consultants.

Those 16/16 passes therefore happened with the architecture the user
designed: deterministic algebra owning operating-driver adaptation,
no GPT in the solver loop, GPT confined to (a) intake, (b) cash
strategy review, (c) path engine ramps, and (d) — when present in
later commits — the exhaustion handler.

---

## Investigation 4 — Quantification of Phase 3 per-draft GPT call
count after seed fix

Per-consultant call pattern (Sunny, NAICS 311811):

- band_shaping: iterates 19 applicable, non-schedule-locked drivers. **19 GPT calls** (no retry; the consultant either accepts, amends, or rejects per lever).
- target_shaping: iterates 33 target metrics. **33 GPT calls**.
- conflict_adjudication: iterates per detected intake-vs-band conflict.
  Conflict count is data-dependent; a typical Sunny / Express style
  draft generates ~3-10 conflicts. **3-10 GPT calls** (use 5 as a
  midpoint estimate).

**Phase 3 total per Sunny draft: ~57 GPT calls.** Plus cash strategy
review (1-3) and any other GPT touchpoints. Order of magnitude: ~60.

The pre-fix budget cap was `_GPT_CALL_BUDGET_PER_RUN = 4`. The Phase
9 P3.5 bump moved it to 8. **Both numbers are far below the actual
post-seed-fix consultant call demand.** The 4-call cap was correct
for the pre-fix world (where every consultant call returned a fallback
without consuming budget meaningfully) and the directive's
"4 batches of GPT calls" mental model. After the seed fix, the 4-call
intent collides with the per-scope iteration pattern.

This is why my Sunny v3 trace shows the exhaustion handler firing
Call 1 with `decision_source: "python_proposer_only_budget_exhausted"`
— the 8-call cap was consumed by the Phase 3 consultants before the
handler ran.

---

## Architectural framing

The user's stated architecture:

> Deterministic algebra owns all operating-driver adaptation
> (cost-priority tiering, target-driven, no GPT). GPT lives at intake,
> cash strategy, path engine ramps, and the new exhaustion handler.

This matches what `post_intake_target_solver/__init__.py` already
documents:

> The solver itself is deterministic algebra — it does NOT consume
> any GPT calls. The 4-call GPT cap from Phase H is preserved by:
>   - Cash strategy review (post-restoration) — unchanged
>   - Path engine ramp generation — consumed but not invoked here
>   - Intake / narrative — untouched
>   - The new solver's allocation + iteration logic — pure
>     deterministic Python.

Phase 3 consultants are NOT in that list. They predate this
architecture (they were authored under "Phase 3 / 5.2"). The seed bug
masked their continued presence on the call graph; the deterministic
restoration loop authored under Phase 9 P3 was always the intended
authority. Removing the seed bug exposed the pre-existing
architectural drift.

---

## Likely fix paths (proposed, NOT applied)

Three viable paths. The user decides.

### A. Retire Phase 3 consultants entirely

Remove the three consultant invocations from
`orchestrator.py:917, 932, 956`. Delete `consultant_band_shaping.py`,
`consultant_target_shaping.py`, `consultant_conflict_adjudication.py`,
and any references in `__init__.py` exports. The deterministic
Python proposers (`assemble_driver_movement_envelope`,
`assemble_finmo_output_targets`) become the sole source of bands and
targets. Solver-loop architecture is restored.

**Pros:** matches the architecture exactly. Removes ~3000 lines of
GPT amendment / validation / context-resolver code that's no longer
the chosen path. Frees GPT budget for the exhaustion handler and
other intentional GPT touchpoints. Restores the "16/16 with
consultants dormant" baseline.

**Cons:** the consultants were authored to address specific failure
modes that the deterministic Python proposers couldn't handle. The
phase_3 GPT amendments are also referenced in `phase_3_calibrated`
band-source provenance throughout the codebase and the realism gate
prefers them when present. Removal needs:
- audit of every site that branches on `calibration_source ==
  "gpt_calibrated"` or `"phase_3_calibrated"`;
- decide whether to keep the `python_default` provenance shape and
  just freeze it permanently.

### B. Scope Phase 3 consultants to a feature flag (default OFF)

Wrap the three orchestrator invocations behind a single env or
settings flag (e.g. `PHASE_3_CONSULTANTS_ENABLED`). Default OFF.
Solver-loop architecture is the default; Phase 3 amendments are
opt-in for experimentation only.

**Pros:** preserves the consultant code for future re-architecture.
Cheap to implement (one branch each).

**Cons:** adds a feature flag to maintain. The dead-code dimension
the user has already flagged remains.

### C. Properly integrate Phase 3 consultants into the solver-loop
architecture

If Phase 3 consultants are genuinely needed, redesign their
integration so they don't compete with the deterministic solver:
- batch the per-lever / per-metric / per-conflict calls into a
  small number of bulk calls (1 per consultant), reducing budget
  consumption from ~60 to ~3;
- run them ONLY at the cohort-shaping layer (e.g., shape NAICS bands
  per business profile once, cache by NAICS×stage×revenue bucket)
  rather than per-draft live;
- explicitly position them in the "GPT lives at" doctrine list so
  the architecture is intentional.

**Pros:** retains the value of GPT-shaped bands when justified.

**Cons:** highest engineering cost. Caching layer + bulk-call refactor
+ doctrine update. Doesn't fit a P3.5 fix scope.

---

## Recommendation

The user's framing and the prior 16/16 pass evidence both point to
**Path A** (retire the three consultants) as the cleanest architecture-
aligned fix. The consultants' value-add was masked by the seed bug
across the entire window during which the doctrine was set; removing
them returns the system to its tested-working state and frees the
GPT budget for the exhaustion handler.

If the user wants to preserve the option to re-introduce Phase 3
consultants under a different design later, **Path B** captures that
optionality at low cost.

**Path C** is appropriate only if Phase 3 amendments are independently
justified by data — which would require a separate eval comparing
deterministic-only vs GPT-amended outcomes, which we don't have today.

---

## Audit trail / artifacts referenced

- Sunny v3 system run (today): draft `cfde971c74f4447fa225ede5ad9b5ac9`,
  Q11 EBITDA -0.51, restoration_loop status `iterating_still`,
  exhaustion handler short-circuited at Call 1
  (`python_proposer_only_budget_exhausted`).
- Live OpenAI Responses API check (today): status=400
  `{"error": {"code": "unknown_parameter", "param": "seed"}}` for
  payload including `seed: 1729`.
- `git show 4a09142:python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py`:
  contains `"seed": _PHASE_3_CONSULTANT_SEED,` in the payload — confirms
  Phase 3 consultants returned HTTP-error fallbacks at that commit.
- `git show 73b71ee:…` and `git show 272c0a2:…`: same — seed was
  always present in pre-P3.5 commits.
- Lever / metric counts for Sunny (NAICS 311811):
  `assemble_driver_movement_envelope` returns 26 drivers (19
  applicable + non-schedule-locked); `assemble_finmo_output_targets`
  returns 33 metrics.
