# GPT-Authors-Payroll (Anchored) — Diagnosis & Scope

**Status:** FINDINGS / SCOPE ONLY. No code, no wiring. Authority for the pivot decision is Nick's.
Every claim is grounded in file:line or in captured live-run evidence.

**Decision being scoped (given):** **GPT authors payroll**, grounded in the existing producer's
revenue→budget→FTE math handed to it as **reference context**. The Python producer
(`author_round1_payroll_contract`) becomes an **anchor-calculator**, NOT the live author. We are
**not** closing the producer-integration gap by wiring `author_round1_payroll_contract` into
`/system-run`.

This doc answers the three scope questions: (1) the live flow + why it falls back to a stub, with
the captured failure; (2) whether the legacy GPT path is callable; (3) the cleanest seam for
GPT-authors-anchored.

---

## Part 1 — The live `/system-run` payroll flow and the stub fallback

### 1.1 The path to payroll authoring

`/api/intake-consult/system-run` → `_run_planning_system_for_draft` → `prepare_initial_grid_for_draft`
([post_intake_initial_grid/runner.py](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py)).
Round-1 payroll is authored by the **producer**, reached on the normal path:

- `set_payroll_schedule(contract=None)`
  ([runner.py:1197-1212](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1197-L1212))
  → `author_round1_payroll_contract`
  ([set_payroll_schedule.py:236-278](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L236-L278);
  producer at [schedule.py:2159](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2159)).
- **The producer IS reached and its contract is accepted at round-1.** If it were rejected, the
  runner fail-fasts with `FAIL_ROUND1_SET_TOOL_REJECTED`
  ([runner.py:1213-1230](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1213-L1230)),
  which is **not** what happens.

So the producer authors real payroll. The failure is **downstream**.

### 1.2 The captured failure (the actual `previous_contract_failure`)

Live run (intake-bypass, Sunny Glaze Donuts) server-log capture — the **original** error that
seeds the fallback:

```
POST_INTAKE:payroll_revenue_economic_feasibility_failed
  @quarter_grid_applied_global_payroll_revenue_feasibility:
  Payroll/revenue economics are outside the table-backed headcount policy range;
  recompute drivers instead of clipping outputs.
```

Raised by `assert_payroll_revenue_feasibility`
([schedule.py:3215-3229](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3215-L3229),
which wraps `payroll_revenue_feasibility_violations`
[schedule.py:3095](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3095)).
**Stage:** `quarter_grid_applied_global_payroll_revenue_feasibility` — i.e. it fires **after**
quarter-grid generation reshapes revenue, not at round-1 authoring.

**Why it fires (inference, consistent with producer behavior):** the producer sizes payroll to the
class-band **midpoint** against **round-1** revenue, then subtracts fixed **key-person** payroll.
For a small business (Sunny Glaze: one owner ~mid-five-figures on small early revenue), the fixed
owner cost pushes payroll/revenue **above the band** in low-revenue quarters; and the check runs
against the **post-quarter-grid** revenue, which can differ from the round-1 revenue the producer
sized against. Either way the global feasibility check fails. **This same check will gate a GPT
author** (Part 3.4).

### 1.3 The fallback to the stub

The feasibility failure routes into the repair path, which is now a **dead stub**:

1. The failure is caught and routed to `route_payroll_feasibility_to_handler_c`
   ([feasibility_repair.py:107-187](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L107-L187)).
2. That calls `estimate_payroll_headcount_schedule_with_gpt`
   ([feasibility_repair.py:165](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L165)).
3. **`estimate_payroll_headcount_schedule_with_gpt` is a stub** — the GPT loop was deleted; it
   returns `build_pending_payroll_stub(previous_contract_failure=...)`
   ([schedule.py:2433](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2433),
   delegating to [lookup.py:939-981](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L939-L981)).
   The feasibility failure is stamped into the stub's `python_proposal_diagnostic.previous_contract_failure`.
4. The stub is re-applied via `apply_payroll_schedule_to_state`
   ([feasibility_repair.py:58-104](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L58-L104))
   → `apply_payroll_headcount_payload_to_model_input` → validation FAILS because the stub has empty
   enums + forbidden `python_proposal_diagnostic` text fields:
   `payroll_headcount_schedule_validation_failed@payroll_headcount_model_input_application`
   ([validator lookup.py:1076-1193](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L1076-L1193)).
5. Run dies.

**Verdict for Q1:** the producer authoring step IS reached and succeeds; the run dies in the
**feasibility-repair fallback**, which is a dead stub. The `previous_contract_failure` originates
from the **global payroll/revenue feasibility check after quarter-grid** (1.2). This is a
pre-existing gap (confirmed: identical failure at 98151d1 with Part E stashed).

---

## Part 2 — Is the legacy GPT authoring path callable?

**No. The GPT payroll-authoring machinery is fully removed; only a stub shim remains.**

- `estimate_payroll_headcount_schedule_with_gpt`
  ([schedule.py:2433](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2433))
  **does not call GPT.** Its docstring states *"The GPT iteration loop is GONE
  (tool_calling_session.py deleted)"*; its body asserts a sequence gate and returns
  `build_pending_payroll_stub`. Callers: `feasibility_repair.py:165` (the repair path above) and
  legacy controller callers behind the gate.
- The deleted machinery is enumerated in-code
  ([schedule.py:2419-2430](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2419-L2430)):
  the iterative-refinement loop, the feedback-packet builder, the per-round GPT call counter, and
  `tool_calling_session.py` itself — all gone. No `openai`/tool-calling call authors payroll
  anywhere in `post_intake_headcount/`.
- The **amalgamated responder** makes real GPT calls but exposes only
  `confirm_proposal / veto_proposal / choose_option / other_proposal`
  ([responder.py:75-152](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L75-L152),
  `tool_choice: required`). It **critiques** Python proposals; it does **not author** a payroll
  contract.

**What survives intact and is reusable for a GPT author:**

| Asset | file:line | Use for the pivot |
|---|---|---|
| `payroll_headcount_schedule` contract schema + per-field `prompt_required_instruction` | [post_intake_mapping.py:2048-2160](../../python/client_intake_and_finmo/post_intake_mapping.py#L2048-L2160) | the schema GPT authors against (grid + enums + scalars + rationale) |
| `validate_payroll_headcount_contract_payload` + builder | [schedule.py:1843](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1843), [schedule.py:2013](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2013) | validate + build whatever GPT authors (unchanged) |
| `set_payroll_schedule(contract=<dict>)` accept path | [set_payroll_schedule.py:231-409](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L231-L409) | the entry that already takes a GPT-authored contract, validates + builds it |
| `author_round1_payroll_contract` (the producer) | [schedule.py:2159](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2159) | repurpose as the **anchor-calculator** (Part 3) |
| Context builders: `_revenue_driver_context_from_model_input`, `_oews_title_catalog_for_business`, `_intake_implied_operating_intensity`, `_payroll_capacity_grid_for_gpt`, `headcount_payroll_revenue_sanity_bounds` | schedule.py / lookup.py | the per-quarter revenue, OEWS catalog, intensity signal, capacity grid, and policy bands to feed GPT |

**Verdict for Q2:** legacy GPT authoring is **fully removed** (dead stub). But the **schema,
validator, builder, accept-path, and all context builders are intact** — a GPT author is a
build-the-call problem, not a rebuild-the-substrate problem.

---

## Part 3 — Cleanest seam for GPT-authors-anchored

### 3.1 (a) Where GPT authors in the live path — reuse `set_payroll_schedule(contract=...)`

`set_payroll_schedule` already has a **`contract != None`** path that validates + builds a supplied
contract ([set_payroll_schedule.py:231-409](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L231-L409)).
That is the GPT-authoring seam: GPT produces a `payroll_headcount_schedule` contract, the tool
validates + builds it exactly as today. **No new validate/build substrate.** What's missing is the
**GPT call that produces the contract** — there is no authoring loop today (Part 2). The thin new
piece is a single payroll-authoring GPT call (structured output against the intact schema, Part 2),
whose result is handed to `set_payroll_schedule(contract=<gpt_dict>)`. Round-1 wiring then changes
from `contract=None` (producer) to: compute anchor → GPT authors → `set_payroll_schedule(contract=...)`.

### 3.2 (b) Hand GPT the producer's anchor as reference — repurpose `author_round1_payroll_contract`

The producer already computes, per quarter, exactly the anchor GPT needs
([schedule.py:2159+](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2159)):
own revenue × band-midpoint = **payroll budget**; minus fixed **key-person** payroll =
**supporting budget**; ÷ OEWS wages = **implied supporting FTE**; plus the **tot_emp mix**. The
seam is to have it **emit** these as a reference object (it already computes them internally)
rather than emit a final contract:

```
anchor = {
  per_quarter: { revenue, payroll_budget(=rev×midpoint), key_people_payroll,
                 supporting_budget, implied_supporting_fte_total },
  labor_intensity_class, target_payroll_percent_of_revenue(=midpoint),
  suggested_oews_mix: [{occ_title, tot_emp_weight, base_wage}],
}
```

Surface that in the GPT authoring prompt as **non-binding reference** ("here is the
revenue-grounded payroll budget and the FTE it implies; author the grid grounded in it"). GPT then
chooses titles/FTE/intensity **anchored** to real revenue economics instead of freehand-guessing —
the D1/D4 grounding from
[payroll_schedule_revenue_grounding_research.md](payroll_schedule_revenue_grounding_research.md),
delivered as context to a GPT author rather than as a deterministic output.

### 3.3 The repair path must route to the GPT author, not the dead stub

`route_payroll_feasibility_to_handler_c`
([feasibility_repair.py:107-187](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L107-L187))
is **designed** to re-author on feasibility failure with `previous_contract_failure` feedback — but
it calls the dead stub (Part 1.3). The pivot points this at the **same GPT author** (3.1), passing
the feasibility failure **and** a **refreshed anchor** computed against the **post-quarter-grid**
revenue. This is the natural retry loop and directly fixes the live failure (the run dies precisely
because this path is a stub).

### 3.4 The non-negotiable constraint the anchor must respect (from Part 1.2)

The failure fires at `quarter_grid_applied_global_payroll_revenue_feasibility` — **after** revenue
reshape, and it is a **hard fail** ("recompute drivers instead of clipping"). So:

- The anchor handed to GPT (and to the repair) must be computed against the **revenue the
  feasibility check uses** (post-quarter-grid), not only round-1 revenue — otherwise a GPT author,
  like the producer, will size against stale revenue and fail the same check.
- Fixed **key-person** payroll can push payroll/revenue **out of band** in low-revenue quarters
  regardless of who authors. The anchor must surface this (e.g. the per-quarter band headroom after
  key-person cost) so GPT can react (lower supporting FTE early, or flag the structural infeasibility)
  rather than producing a contract that the global check rejects. A GPT author does not escape the
  feasibility gate; the anchor is what lets it satisfy it.

### 3.5 Seam summary

| Need | Seam (reuse) | New work |
|---|---|---|
| GPT authors in live path | `set_payroll_schedule(contract=<gpt>)` accept path | one structured GPT authoring call vs. the intact schema |
| GPT grounded in revenue anchor | `author_round1_payroll_contract` → emit anchor object | repurpose to return the anchor (already computed) + add it to the GPT prompt context |
| Round-1 wiring | runner round-1 (`set_payroll_schedule`) | swap `contract=None` (producer) → anchor → GPT → `contract=<gpt>` |
| Feasibility retry | `route_payroll_feasibility_to_handler_c` | route to the GPT author (not the stub) + refreshed post-quarter-grid anchor |
| Validate / build / freeze capacity | validator + builder + Part E loop-break (committed `d58b897`) | none — capacity already stays the revenue anchor |

---

## Honest flags

- **The producer is not "broken"** — it authors a valid contract that the global feasibility check
  later rejects for Sunny Glaze (key-person-cost vs. small early revenue, against post-quarter-grid
  revenue). A GPT author faces the **same** gate; the anchor is the mechanism for satisfying it, not
  a bypass.
- **A GPT-authoring loop must be built** — none exists (Part 2). The lightest form is a single
  structured-output authoring call feeding `set_payroll_schedule(contract=...)`, reusing the intact
  schema/validator/builder; a full multi-round tool-calling session is heavier and not required to
  start.
- **The anchor's revenue basis is the crux** — computing it against round-1 revenue (as the
  producer does today) is what lets the post-quarter-grid feasibility check fail. The pivot's value
  depends on anchoring (and re-anchoring in the repair) against the revenue the check actually uses.
- **Part E already removed the capacity loop** — capacity stays the revenue anchor regardless of who
  authors payroll, so GPT authoring does not reintroduce the loop.
- **Scope honored:** findings only; no producer wired into `/system-run`; no code changed.
