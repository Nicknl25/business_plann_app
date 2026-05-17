# Adaptation Architecture — Doctrine

**Status:** Authoritative architectural reference for the post-intake pipeline.
**Owner:** Phase 9 P3.10 architecture pass (iter 19+).
**Read this first** when designing a new post-intake step, converting a GPT-only
step to Python-first, or arbitrating between two implementations of the same
value.

This is the source of truth that the iter 19 stage build (Stages 1-8) refers to.
If a stage instruction conflicts with this doc, the doctrine wins; if the
doctrine is silent, stop and report.

---

## 1. The Principle: Adaptation

The system **adapts** to each business's specific shape rather than applying
one-size-fits-all rules. The mechanism is:

1. **Python first.** Every post-intake process is implemented as a deterministic
   Python computation that uses intake inputs, cohort norms (NAICS-keyed bands
   and midpoints), and standard templates (stage-ramp curves, FTE allocation
   logic, etc.) to produce a complete, sound default.
2. **Validators check.** Pure-Python validators inspect the deterministic
   output for realism, coherence, and contract compliance.
3. **Handler engages on failure.** When validators trip, a *domain-specific*
   GPT-backed handler engages with explicitly-defined lever authority and a
   10-tool-call budget. It corrects Python's output and the validators rerun.
4. **Hard-fail with diagnostic.** When the handler exhausts its budget without
   resolving the failure, the system hard-fails with a diagnostic that **names
   the specific lever or field that could not be repaired** (not a generic
   "convergence failed").

**Routine GPT review is forbidden** *for operations where Python can
produce a sound default from cohort norms + intake state.* The
handler-on-failure pattern applies to these: cost ratio targets,
maintenance rate, cash funding plan, stage ramp shape.

**GPT as authoring source IS the correct pattern** for judgment-heavy
operations where Python has no rules to apply. Examples:

- **Convergence decision authoring** — which levers to move, which
  metrics to target, and the per-quarter target_values to drive the
  numeric solver toward. The decision space is too large and the
  trade-offs too business-specific for a cohort default.
- **Payroll title selection** — picking the right OEWS occupational
  titles from the NAICS catalog for the specific business model. The
  catalog has hundreds of candidates; choosing among them is judgment
  about the operator's business, not table lookup.

These are NOT handler-on-failure patterns. They're GPT-authored-from-
start with Python providing **structure around them**: bounds
(strict-mode JSON schemas), validators (post-parse coherence checks),
mechanical math (Python-computed downstream consequences of GPT's
choices). The GPT call runs every plan because the work IS judgment;
Python has nothing better to propose.

This is "adaptation" because the rule-set is not hardcoded: the cohort table
supplies bands, intake supplies the operator's stated state, Python proposes,
and the handler refines for the cases that don't fit the median template.
For judgment-heavy operations, GPT is the authoring source because there is
no rule-set to apply.

---

## 2. Roles

| Role | What it owns | What it must NOT do |
|---|---|---|
| **Python (deterministic)** | Computation, defaults from cohort midpoints, mapping-formula evaluation, validator implementations, post-pass invariant checks. **Structure** (schemas, validators, mechanical math) around GPT-authored decisions. | Pretend to be deterministic while silently falling back on hardcoded universals. Use magic numbers to mask divergence. Try to author judgment-heavy decisions for which there is no rule-set. |
| **GPT (handler form OR authoring source)** | (handler form) Judgment-heavy lever authoring inside a handler's defined authority on validator failure. (authoring source) Judgment-heavy operations where Python has no rule-set — convergence decision authoring, payroll title selection. Trade-off reasoning specific to the operator's business. | Author levers outside its defined authority. Operate without strict-mode schema bounds. Run routinely on operations where Python *could* produce a sound default from cohort norms. |
| **Validators** | Pure-Python checks that produce structured violations and trigger the responsible handler. Contract-compliance, realism, coherence. | Re-implement computation that another module already authored (use the canonical source instead — §4 Flavor 1). |
| **Hard-fail diagnostics** | Specific, named-field error messages on unrecoverable state. Surface the upstream skipped step or unfixable lever. | Be generic. "Unfixed after handler" is not acceptable — name what wasn't fixed and why. |

---

## 3. The Three Patterns

Three patterns recur across the iter 8-18 fix history. Recognize them; the fix
recipe for each is established.

### Pattern 1 — Two paths compute the same value

Symptom: two implementations of one conceptual quantity drift at the boundary
(rounding, clipping, unit conversion, definition of "operational").

Recipe: pick a Mirror Flavor from §4 and apply it. Default preference order is
Flavor 1 > 2 > 4 > 3.

Examples: iter 8 (storage clamp), iter 10 (buffer units), iter 14 (STD
forward-sim), iter 16 (ΔSTD in OCF), F7 (mapping-formula rounding order).

### Pattern 2 — GPT as routine authoring source

Symptom: a step is GPT-only, runs every plan, and fails with no Python fallback
when GPT misses (F1 maintenance_rate, _run_cash_strategy_review_openai,
_estimate_stage_ramp_contract_with_gpt, _run_unified_convergence_openai).

Recipe: build a Python-deterministic proposer that uses cohort midpoints +
intake state. The GPT call becomes a handler that engages **only when** a
validator on Python's output fails. The handler's authority is the same lever
set the original GPT call authored.

### Pattern 3 — Diagnostic blames the wrong layer

Symptom: handler engages but its lever authority does not include the lever
the gate's check references; engagement reports "could not fix X" when X is
not in its authority (F6-Pinnacle: pre-cash gate checks payroll, handler has
no payroll authority).

Recipe: the handler's authority must match the validator's check set, OR the
diagnostic must name the upstream contract owner. Two sub-fixes:
- Make the upstream lever writeback **unconditional** (not gated on a "changed"
  flag) so the lever is present when the gate runs.
- At the gate's entry point, assert every check's primary_levers are non-zero
  for businesses with non-zero contract totals; if not, raise a *specific*
  diagnostic naming the upstream skipped step (not the handler).

---

## 4. Mirror Flavors for Pattern 1

Four flavors for collapsing "two paths compute same value." Prefer the lower
number.

### Flavor 1 — Direct reference (preferred)

Both call sites import and call **one shared function**. There is no second
implementation.

- Example: iter 10 (`3339fd8`) — buffer_components math extracted to a single
  helper imported by both the cash strategy proposer and the buffer validator.
- Example shape: `compute_revenue_times_ratio(revenue, ratio) -> int` used by
  both FINMO and the mapping-formula validator (iter 19 Stage 1, F7).

When to use: whenever the two sites can both call the helper directly without
circular imports.

### Flavor 2 — Functional mirror

Two sites replicate **identical** logic and produce the same result by
construction. Used when a direct call would create a dependency cycle or when
the two sites need to remain independent for performance.

- Example: iter 14 (`2c51b05`) — STD source computed via forward simulation
  in both the FINMO build and the schedule projector, mirroring exactly.

When to use: dependency cycle blocks Flavor 1; or one side is hot-path and
must inline.

### Flavor 3 — Mini / shadow object

A simplified mirror object used for handler preview queries. The handler asks
the mirror "what would the full model look like with these lever values?"
without paying the full-model construction cost.

- Example: `mini_finmo` in
  [post_intake_gpt_exhaustion_handler/mini_finmo.py](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py)
  — handler can rehearse lever changes before committing.

When to use: handler needs trajectory preview; full-model rebuild per probe
is prohibitively expensive.

### Flavor 4 — Invariant check

Two independent computations + an assertion they agree at runtime. The
assertion is itself a validator; on disagreement, hard-fail (or trigger a
handler).

- Example: iter 16 (`39e20c0`) — balance sheet reconcile asserts
  Assets == Liabilities + Equity to ~$1 tolerance; hard-fails with a
  per-quarter diagnostic when they diverge.

When to use: the two paths are intentionally redundant for safety
(belt-and-suspenders); a divergence indicates an upstream bug, not a normal
disagreement.

---

## 5. Handler Structure

Every handler in the system has the same shape:

1. **Module location:** `python/client_intake_and_finmo/post_intake_<name>_handler/`
   with `__init__.py`, `handler.py`, `tool_calling_session.py`, `prompts.py`,
   and a `mini_finmo.py` (or analogous preview mirror) when trajectory preview
   is needed.
2. **Defined lever authority:** the handler's prompt and tool definitions
   restrict it to a specific named lever set. Authority is **explicit**; a
   handler that could author "whatever it needs" is a Pattern 3 bug waiting to
   happen.
3. **Tool-call budget:** `HARD_CAP_TOOL_CALLS = 10` per
   [tool_calling_session.py:22](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L22).
4. **Run-budget decoupling:** the handler invokes its model with
   `counts_against_run_budget=False` per iter 17 (`8dfd23a`,
   [tool_calling_session.py:539](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L539)).
   Handlers MUST NOT consume the run-wide GPT call budget — that budget is for
   the main planning flow, and exhausting it inside a handler causes the
   handler to silently truncate.
5. **Specific validator trigger:** one (or a small set of related) validators
   trigger this handler. The handler is **not** generic.
6. **Specific hard-fail diagnostic:** on budget exhaustion, the handler's
   wrapper raises an error that names the unfixable lever/field and references
   the validator that tripped. Never "unfixed after handler" without naming
   what's unfixed.

A handler that lacks any of these six properties is mis-shaped.

---

## 6. Handler Inventory

State at iter 19 close.

### Handlers (Python-first + handler-on-validator-failure)

| Handler | Module | Authority | Trigger | Status |
|---|---|---|---|---|
| **Restoration / exhaustion** | `post_intake_gpt_exhaustion_handler` | 12 PNL levers + 5 WC levers | Restoration loop exhaustion | Existing (pre-iter-19) |
| **Funding** | `post_intake_funding_handler` | Debt issuance, debt repayment, owner's capital, other equity, distributions, `cash_strategy_mode` override | `cash_buffer_violations` non-empty after cash strategy post-pass | Built in iter 19 Stage 4 (+ correction) |
| **Stage ramp** | `post_intake_stage_ramp_handler` | Stage ramp contract fields (ramp shape, target margins, capacity curve, cost ratio caps) | Stage ramp realism validator fails on deterministic Python ramp | Built in iter 19 Stage 5 |

Each row's "Authority" is the **complete** list. A handler that wants to
author a lever outside its row is mis-shaped (see Pattern 3, F6-Pinnacle).

### GPT-as-authoring-source (intentional, NOT handler-on-failure)

These operations are GPT-authored every plan by design, because the
decision space has no rule-set Python could apply. Python provides
structure (strict-mode schemas, post-parse validators, mechanical
math); GPT provides the judgment.

| Operation | Entry point | Why it stays GPT-authored |
|---|---|---|
| **Unified convergence decision** | `_run_unified_convergence_openai` ([runtime.py:2776](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L2776)) | Which levers to move, which metrics to target, the per-quarter target_values to drive the numeric solver toward — the decision space is too large and the trade-offs too business-specific for a cohort default. Python wraps GPT with strict-mode schema bounds + post-parse contract validation. |
| **Payroll headcount schedule** | `estimate_payroll_headcount_schedule_with_gpt` ([schedule.py:2241+](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2241)) | Selecting OEWS occupational titles from the NAICS catalog is judgment about the operator's business model. The catalog has hundreds of candidates; choosing among them is not table lookup. Python provides tier-bound schema (iter 19 Stage 2), title-catalog filtering, wage/FTE mechanical math, and post-parse policy validators. |

### Deferred / not built

| Adaptation | Status | Note |
|---|---|---|
| Payroll adaptation | Deferred from iter 19 | Stage 6 was intentionally skipped per direction (payroll is fragile). The Stage 3 correction addressed the orchestration bug; payroll *authoring* stays GPT-as-source. |
| "Convergence handler" | Intentionally NOT built | Original Stage 7 of the iter 19 directive proposed dropping `_run_unified_convergence_openai` and treating restoration_loop + cascade as the convergence engine. Investigation during iter 19 showed this was based on a misreading of the codebase: the cascade re-enters the same convergence runner, so removing the routine GPT call would break every plan with no recovery path. Convergence is correctly GPT-authored. |

---

## 7. Anti-Patterns (do not do these)

- **Silent fall-through.** `try: ... except: pass` or `if x is None: use_default()`
  without a logged signal. Mask bugs and starve future debugging. Replace with
  hard-fail + diagnostic.
- **Routine GPT review on operations Python can author.** A GPT call
  that runs every plan to amend a value Python could have produced
  from cohort norms + intake state. Convert to Python-first +
  handler-on-failure. (Distinct from GPT-as-authoring-source — see §6
  table — which is the correct pattern when Python has no rule-set to
  apply.)
- **Two parallel implementations** of the same conceptual value. Pick a Mirror
  Flavor from §4.
- **Magic numbers / arbitrary thresholds** to mask a divergence (e.g., bumping
  a tolerance to silence a failing test). Fix the divergence at source first;
  then add a small tolerance as belt-and-suspenders if the residue is genuine
  float noise.
- **Widening tolerance to hide divergence.** A tolerance fix without a
  corresponding source fix is technical debt; require both.
- **F6-Pinnacle pattern:** handler authority over levers that **do not match**
  the validator's check set. The handler must either be able to author every
  lever the validator checks, OR the diagnostic must name the upstream
  contract owner instead of blaming the handler.
- **Stub-0 / intake values leaking into Q1-Q20 forecast columns.** Intake
  state is the launching point, not a forecast value. The Python-deterministic
  proposer MUST produce Q1-Q20 values from cohort norms + ramp templates, not
  by carrying Stub-0 forward.

---

## 8. Key Historical Examples

Brief references with commit hashes — read the commits when applying the
matching pattern to a new site.

| Iter | Hash | What it taught |
|---|---|---|
| Iter 10 | `3339fd8` | Buffer math single source of truth (Mirror Flavor 1). |
| Iter 13 | `ff55f28` | Cash ceiling policy removal — chronic gaps can't be papered over by a hardcoded ceiling. |
| Iter 14 | `2c51b05` | STD source via forward simulation (Mirror Flavor 2). |
| Iter 15 | `3726702` | LTD double-counting + STD/LTD coherence with fail-fast. |
| Iter 16 | `39e20c0` | ΔSTD removed from OCF + balance sheet reconcile invariant check (Mirror Flavor 4). |
| Iter 17 | `8dfd23a` | Handler budget decoupling — `counts_against_run_budget=False`. |
| Iter 18 | `499d8a2` | Investigation report establishing the three patterns + four mirror flavors. |
| Iter 19 Stage 0 | `dffb013` | This document — adaptation architecture doctrine. |
| Iter 19 Stage 1 | `d8c3ec3` | F7 mapping-formula single-source helper (Mirror Flavor 1). F1 conservative-default fallback for `maintenance_rate`. |
| Iter 19 Stage 2 | `0824aff` | `target_payroll_percent_of_revenue` envelope tightening + tier-conditional `allOf`/if-then JSON schema + anti-confusion prompt. |
| Iter 19 Stage 3 | `568cbbf` + correction `2a12b19` | F6-Pinnacle: specific pre-cash gate diagnostic + unconditional payroll writeback. |
| Iter 19 Stage 4 | `898429f` + correction `b846a86` | Cash adaptation. Dropped routine GPT critic; new `post_intake_funding_handler` module with full GPT tool-calling loop wired into cash post-pass. |
| Iter 19 Stage 5 | `1721c2c` | Stage ramp adaptation. New `build_python_stage_ramp_contract` Python builder + `post_intake_stage_ramp_handler` module with full GPT tool-calling loop, wired in `intake_consult` as the new `estimate_stage_ramp_contract_with_gpt` dependency. |

When picking a recipe for a new bug, ask: *which of these does it resemble?*
The patterns recur.

---

## 9. When in Doubt

Default decisions, in priority order:

1. **Prefer deterministic over GPT.** If a value can be computed from cohort
   norms + intake state without judgment, do that.
2. **Prefer single source of truth over invariant checks.** Flavor 1 over
   Flavor 4 when the dependency graph allows it.
3. **Prefer hard-fail with diagnostic over silent recovery.** A failure that
   names what failed is more valuable than a "success" that quietly produced
   wrong output.
4. **Prefer specific diagnostics over generic ones.** Name the lever, the
   quarter, the upstream contract owner. Never "convergence failed."
5. **Reference iter examples** in §8 — the pattern probably already appears
   there with a worked fix.

If the doctrine is silent on a question, **stop and report** rather than
guessing.
