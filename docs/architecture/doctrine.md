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
7. **Machinery fail-fasts.** Every handler has the following six machinery
   invariants that hard-stop with a named diagnostic if the iteration
   infrastructure itself malfunctions (added in iter P3.12):
   - **Round count drift** — loop's local round counter disagrees with
     actual number of GPT calls made.
   - **Budget decoupling violation** — a GPT call inside the session is
     issued without `counts_against_run_budget=False` (iter 17 contract).
   - **State corruption between rounds** — `input_items` / `history` /
     `verified_commit_candidate` shape malformed at round entry.
   - **Authority violation** — handler authored a lever outside its
     declared lever set (e.g., funding handler writes to `expenses::
     Payroll`). Silent skip of out-of-authority IDs is the Pattern 3
     anti-pattern; this guard converts it to a loud diagnostic.
   - **Output malformation** — handler returns RESOLVED with empty
     authored changes, or EXHAUSTED with no diagnostic.
   - **Best-effort selection drift** — best-effort record selected at
     hard cap is actually all-resolved (should have been picked up as
     the verified commit candidate).
   These are distinct from the handler's `EXHAUSTED` status (which is
   the planned hard-fail when the handler can't resolve the business
   problem within its budget). See §5b for the conceptual distinction
   between validators and machinery fail-fasts.

A handler that lacks any of these seven properties is mis-shaped.

---

## 5b. Two Fail Types: Validators vs Machinery Fail-Fasts

Two distinct fail mechanisms exist in this system. Both are required;
both serve different purposes. Conflating them is an architectural
error.

### Type 1 — Validators (Checks)

**Purpose:** detect when **business-logic output** doesn't satisfy
contractual requirements. Examples: payroll/revenue ratio out of
band, balance sheet doesn't reconcile, mapping-formula mismatch,
stage-ramp profitability path violated.

**Behavior:** produce structured violations. Trigger adaptation —
either handler engagement (Python-first + handler-on-failure) or
GPT iteration (iterative authoring with feedback loop).

**Recovery:** **expected.** The system tries again with corrections.
Validators firing during normal operation is fine; that's the
adaptation loop working. They may fire dozens of times per run
across all iterative processes.

**Location:** anywhere in the codebase — validators live near the
operations they check.

### Type 2 — Machinery Fail-Fasts

**Purpose:** detect when the **iteration/handler infrastructure itself**
has broken. Examples: round counter drift, state corruption between
rounds, budget commingling violations, handler authoring levers
outside its declared authority, translator unmatched code,
session-internal-state malformed, policy-mirror drift between
Python and SQL.

**Behavior:** hard-stop the run with a named operation code and
specific diagnostic. NO retry. NO recovery. NO silent fallback.

**Recovery:** **none.** The machinery is broken; surface it loudly
so an engineer can fix it. If machinery fail-fasts silently
recovered, the iteration system would rot invisibly while
appearing to work — runs would complete but adaptation would be
silently degraded.

**Location:** alongside the machinery they protect, but raising
through the centralized `PostIntakePreconditionFailed` machinery in
[fail_fast/common.py](../../python/client_intake_and_finmo/fail_fast/common.py)
so the named operations form a discoverable inventory of "things
that should never happen but if they do, here's exactly what broke."

### The key principle

Validators are about being **wrong** about business logic.
Machinery fail-fasts are about being **broken** in the infrastructure.

Both must exist. Validators without machinery fail-fasts =
adaptation works until the day the machinery silently rots and no
one notices. Machinery fail-fasts without validators = system
can't adapt to business edge cases; just hard-fails.

### Examples from iter 19 + P3.11 + P3.12

**Validators (Type 1):**
- `payroll_headcount_target_payroll_percent_of_revenue_out_of_policy_range`
- `cash_buffer_violations` (post-pass cash strategy validation)
- `stage_ramp_contract_invalid` (realism rejection)
- `balance_sheet_driver_formula_failed`

**Machinery fail-fasts (Type 2):**
- `payroll_lever_not_applied_before_gate` (iter 19 Stage 3 — gate
  contract-lever invariant)
- `payroll_validator_translator_unmatched_code` (iter P3.11)
- `payroll_iterative_refinement_round_count_drift` (iter P3.11)
- `funding_handler_authority_violation` (iter P3.12)
- `funding_handler_round_count_drift` (iter P3.12)
- `stage_ramp_handler_budget_decoupling_violation` (iter P3.12)
- `payroll_tier_bounds_mirror_drift` (iter P3.12 — Python↔SQL drift)

The seven required machinery fail-fast categories every handler
should have:

1. **Round count drift**
2. **Budget decoupling violation**
3. **State corruption between rounds**
4. **Authority violation**
5. **Output malformation**
6. **Best-effort selection drift**
7. **Pre-gate contract-lever invariant** (extends to gates that
   reference contract-authored levers)

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
| **Payroll headcount schedule** | `estimate_payroll_headcount_schedule_with_gpt` ([schedule.py:2241+](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2241)) | Selecting OEWS occupational titles from the NAICS catalog is judgment about the operator's business model. The catalog has hundreds of candidates; choosing among them is not table lookup. Python provides tier-bound schema (iter 19 Stage 2), title-catalog filtering, wage/FTE mechanical math, and post-parse policy validators. |

### Retired (Phase 9 P3.24)

| Adaptation | Status | Note |
|---|---|---|
| Unified convergence decision | RETIRED 2026-05-18 by P3.24 Commit 3 | The `_run_unified_convergence_openai` GPT planner and the `_run_unified_post_grid_system_run` outer cycle loop were bypassed on 2026-05-08 (Phase 8 step 4) and deleted on 2026-05-18 (P3.24 Commit 3). The bypass marker at orchestrator.py:1342 (pre-P3.24) noted the legacy convergence runner was broken under current validator hardening: every fail-fast the legacy GPT loop's authority-reapplication used to suppress now fires (revenue formula validators, payroll schedule rollups, etc.). The replacement architecture is the target-seeking orchestrator (`run_target_seeking_orchestrated_system_run` at post_intake_solver/orchestrator.py:1024) plus restoration loop (`run_restoration_loop` at post_intake_target_solver/restoration_loop.py) plus GPT exhaustion handler (Site 1 + Site 2 at orchestrator.py:1977 / :2130). The iter 19 §5 analysis preserved here for record only — the architecture moved past it. See [p3_23c_unified_convergence_status.md](p3_23c_unified_convergence_status.md). |

### Deferred / not built

| Adaptation | Status | Note |
|---|---|---|
| Payroll adaptation | Deferred from iter 19 | Stage 6 was intentionally skipped per direction (payroll is fragile). The Stage 3 correction addressed the orchestration bug; payroll *authoring* stays GPT-as-source. Phase 9 P3.24 Commit 2 wired the `payroll_feasibility_repair` step from the SQL canonical sequence table into the initial-grid path — single-shot re-author on post-grid feasibility failure, no cycling. |

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
- **Silent machinery degradation.** Handler accepts internal state
  drift without raising. The iteration system appears to work but is
  actually broken — runs complete while adaptation is silently
  degraded. Every machinery invariant (§5 invariant #7, expanded in
  §5b) must fail fast. Silent skip of out-of-authority lever IDs,
  silent fallback when a translator can't match a code, silent
  acceptance of state corruption — these are all instances. The
  cure is named diagnostics + hard-stop, no recovery.
- **Cleared fail-fast diagnostics.** A fail-fast that raises with a
  rich `details=` payload, then has that payload swallowed by an
  upstream `try: ... except: ...` without re-raise, transformed into
  a generic status string that loses the structured fields, or
  cleared by a downstream revert that overwrites validator-populated
  state with a pre-pass deepcopy. Every fail-fast must produce
  diagnostic state that **survives** downstream cleanup paths.
  Anti-example: Phase 9 P3.20 Part 3 Stage 1 (commit `ee291e4`) — the
  cash post-pass orchestrator atomic-reverted
  `cash_strategy_second_pass_result` on validator failure, clearing
  the `cash_contract_failures` metadata the validator had just
  populated. Operators saw a generic "liquidity failure" at finalize
  with no record of which contract failure actually tripped the
  revert. Fix: never overwrite validator-populated state with
  pre-pass state; let the failures live alongside the proposer's
  output for downstream inspection. Related: Stage 4 audit
  (`docs/architecture/p3_20_part3_stage4_diagnostic_preservation_audit.md`)
  confirms no other instances of this pattern exist as of HEAD.
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
