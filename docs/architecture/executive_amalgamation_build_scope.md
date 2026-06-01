# Executive / Amalgamation Build — Scope Pass

**Status:** SCOPE / DESIGN ONLY. No code, no implementation, no act-recommendation. A
verified map of what the Manager toolkit gives an Executive to drive, what the design
documents intend, the concrete built-vs-not gap, a proposed build sequence, and where the
revenue-grounding requirements attach. Every codebase claim is grounded in file:line.
Assumptions are marked **[ASSUMPTION]**; documented intent is marked **[DOCUMENTED]**.

**Terms (kept straight per the brief).**
- **Amalgamation** = combining post-intake state into the **Mirror**.
- **Executive** = the GPT session that reads the Mirror and contributes judgment to plan moves.
- NOT **adaptation** (the realism/restructure invariant), which is a directive *inside* the Mirror.

---

## Headline finding (read this first)

The brief frames the forward path as *"the Executive session (GPT reads the Mirror, **proposes
moves via set_\* tools**, authors the full plan incl. payroll)."* The verified codebase implements
something **narrower and already substantially built**, and the difference is the single most
important thing to settle before any code:

1. **The machinery is built and wired into the live runner**, not greenfield. `build_mirror`,
   `evaluate_plan`, all four `set_*` round-1 calls, the `SessionDriver` state machine, the
   production OpenAI `responder`, and the `session_factory` are all present and invoked from
   [runner.py:1814-1882](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1814-L1882).

2. **The GPT "Executive" role as built is confirm / veto / choose / other — not free authoring.**
   Python (`restructure_proposer.propose_for_tier`) computes the move; GPT only renders a
   structured judgment via four response tools
   ([responder.py:75-152](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L75-L152),
   system prompt [responder.py:159-170](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L159-L170)).
   This is the *"Python proposes structure; GPT critiques structure"* doctrine working as
   designed — it is **not** "GPT proposes moves via set_\* tools." The `set_*` tools are called
   by **Python** in round-1; the `revise_*` tools are called by the **cascade**. GPT never calls
   a tool to author; it judges a Python-authored proposal. **[DOCUMENTED]** — driver docstring
   "The driver does NOT call GPT directly… receives ProposalResponse records via a `responder`
   callback" ([session_driver.py:14-18](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L14-L18)).

3. **Payroll round-1 is a structurally-valid *pending stub* — real payroll authoring exists
   nowhere yet.** `set_payroll_schedule(contract=None)` calls `build_pending_payroll_stub`
   ([set_payroll_schedule.py:266-273](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L266-L273)),
   not a real producer. The cascade can only *revise* an existing payroll contract; it cannot
   author one from the stub. So "payroll authoring becomes a real GPT activity only once the
   amalgamated session lands" ([schedule.py:2200-2207](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2200-L2207))
   describes a step that **is the principal thing still to build**.

The rest of this doc is the verified detail behind those three points.

---

## Part 1 — Current state: what the Manager toolkit gives an Executive to drive

### 1.1 The Mirror

**Assembled by `build_mirror`**
([mirror.py:206-365](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L206-L365)),
invoked from the live runner **after** round-1 authoring
([runner.py:1852-1859](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1852-L1859)).

**What it amalgamates** — the `Mirror` dataclass has six fields
([mirror.py:84-89](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L84-L89)):

| Field | Source | Content |
|---|---|---|
| `invariants` | static, [mirror.py:49-62](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L49-L62) | realism / viability / **adaptation** directives (string per key) |
| `authority` | static, [mirror.py:64-68](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L64-L68) | "You may revise any value Q1 onward… NOT modify Stub 0…" |
| `business_facts` | runner draft columns | name/address/stage/NAICS etc. |
| `plan_state` | round-1 sections, [runner.py:1840-1850](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1840-L1850) | per-section authored payloads keyed `stage_ramp` / `payroll` / `capex_rd_balance_seed` / `balance_sheet` / `drivers` |
| `bands` | cohort-band DB table, loaded in `build_mirror` | per-section min/target/max lever envelopes |
| `validation_state` | `set_validation_state` projection of `EvaluatePlanResult`, [mirror.py:91-146](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L91-L146) | bounded (cap 12) failing-check + lever-margin snapshot |

**Shape the Executive reads.** Not an open canvas — *"GPT does not see an open canvas. It sees
one decision at a time: the current step, the standards that apply, the lever headroom available,
the validation state of the plan as it stands, and what the last few moves did to that state"*
([mirror.py:1-11](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L1-L11))
**[DOCUMENTED]**. In practice the Executive sees a *rendered slice* of the Mirror per proposal —
`render_mirror_for_proposal` emits the proposed change, the band context, business facts, and the
current standards-check state
([responder.py:181-326](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L181-L326)).
The full `Mirror.to_dict()` is the boundary surface (Contract 7 / Boundary 3,
[amalgamated_session_contract.py:401-443](../../python/client_intake_and_finmo/post_intake_contracts/amalgamated_session_contract.py#L401-L443)).

**Refresh semantics.** The Mirror is read-only for rendering; only two setters mutate it in-session:
`set_plan_state_section` after each accepted `revise_*`
([mirror.py:148-164](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L148-L164),
wired [session_factory.py:339-340](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L339-L340))
and `set_validation_state` after each `evaluate_plan`
([session_factory.py:346-347](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L346-L347)).

### 1.2 `evaluate_plan`

Defined at
[evaluate_plan.py:449-471](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L449-L471);
returns an `EvaluatePlanResult`
([evaluation_types.py:104-134](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluation_types.py#L104-L134)).

- **Two strictness modes** ([evaluate_plan.py:1-27](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L1-L27)):
  `mini_finmo` (lighter viability+stage-ramp set) while round-1 authoring is incomplete;
  `full_acceptance_gate` (16-check gate) once structurally complete. **The live wiring forces
  `structural_completeness=True`** ([session_factory.py:221](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L221)) —
  i.e. the session always runs the full gate. **[Flag]** that hard-codes the strict path and
  bypasses the documented mode switch; worth confirming it is intentional.
- **Checks** are classified by `FailureMode`
  ([evaluation_types.py:16-35](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluation_types.py#L16-L35);
  registry [evaluate_plan.py:68-96](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L68-L96)):
  VIABILITY / GROWTH / CAPACITY / BAND / COHERENCE / META. Payroll is implicated by
  `fixed_cost_burden_reduced_or_scaled_by_q11` ([evaluate_plan.py:74](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L74)).
- **Cash checks are filtered out** ([evaluate_plan.py:53-58](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L53-L58),
  rationale [:18-26](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L18-L26)) — cash pass runs after the session.
- **Returns**: `all_pass`, per-check `CheckResult` (with `distance_to_feasibility`,
  `implicated_sections`), `lever_margins` (band headroom for the proposer), `trajectory`,
  `worst_failing_check` / `worst_failing_distance`
  ([evaluate_plan.py:566-578](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L566-L578)).
- **Caller**: wrapped by `_build_evaluate_plan_fn`
  ([session_factory.py:197-228](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L197-L228)),
  invoked by `SessionDriver._evaluate`
  ([session_driver.py:820-895](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L820-L895)),
  re-reading `mirror.plan_state` each round.

### 1.3 The `set_*` tools (round-1 authoring) and the `revise_*` tools (cascade)

Round-1 authoring is **Python calling each `set_*` tool with `contract=None`** — the REPLACE
pattern that supersedes the legacy `_execute_sequence_step` authoring
([runner.py:1814-1824](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1814-L1824)).
Verified call sites in the runner:

| Tool | Defined | Round-1 call | Round-1 result | Verified state |
|---|---|---|---|---|
| `set_capex_rd_balance_seed` | [tool:328](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_capex_rd_balance_seed.py#L328) | [runner.py:862](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L862) | **real** deterministic proposer (maint capex %, R&D applicability, B/S seed) | authored |
| `set_stage_ramp_contract` | [tool:207](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_stage_ramp_contract.py#L207) | [runner.py:1036](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1036) | **real** deterministic builder (20-quarter grid) | authored |
| `set_payroll_schedule` | [tool:161](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L161) | [runner.py:1197](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1197) | **pending stub** via `build_pending_payroll_stub` ([tool:266-273](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L266-L273)) | **DEFERRED / not authored** |
| `set_drivers` | [tool:145](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_drivers.py#L145) | not round-1 ([runner.py:1242-1245](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1242-L1245)) | `anchors=None` → `amalgamated_session_pending`; cascade authors via `revise_drivers` | deferred-to-cascade |

The cascade mutates sections through `revise_*` tools, dispatched by `proposal.section`
([session_factory.py:87-168](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L87-L168)):
`drivers→revise_drivers`, `stage_ramp→revise_stage_ramp_contract`,
`payroll→revise_payroll_schedule`, `balance_sheet/capex_rd→revise_capex_rd_balance_seed`.
`operating_model` levers have **no** `revise_*` tool — the driver logs but cannot apply
([session_factory.py:78-84](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L78-L84)).

**Confirmed round-1 / payroll-deferral facts:**
- The runner's own comment ([runner.py:1240-1245](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1240-L1245))
  states drivers are not a round-1 section and the cascade authors them.
- **Comment drift to flag:** the runner block at
  [runner.py:1186-1193](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1186-L1193)
  claims `set_payroll_schedule(contract=None)` "internally invokes
  `estimate_payroll_headcount_schedule_with_gpt` (Handler C) to author the contract." That is
  **stale** — the iter-11 change rerouted the `contract=None` path to `build_pending_payroll_stub`
  ([set_payroll_schedule.py:236-273](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L236-L273);
  helper [lookup.py:939](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L939)).
  Commit `1ff58a6` ("Round-1 payroll stub: decouple set_payroll_schedule from the legacy
  sequence-controller gate… NexGen E2E iter 11") is the change; the runner comment was not updated.

---

## Part 2 — Intended Executive-session design (documented vs assumed)

### 2.1 Two design lineages — and they disagree about GPT's role

There are **two** design documents, written at different times, describing different GPT roles.
This is the crux of the gap and must be reconciled by Nick before building.

**Lineage A — the amalgamation memo (`set_*` authoring).** **[DOCUMENTED]**
`docs/architecture/p3_33_amalgamation_design.md` describes "one amalgamated GPT session that holds
a comprehensive mirror… **authors every surface** in a single coherent context bounded by
Python-computed bands, can revise prior commits…" (memo §intro). Round-1 is GPT-driven:
"For each step it **calls the section's authoring tool with proposed values**; the tool validates
against bands + contract schema and returns accept/violation" (memo §3, ramp→capex→payroll→drivers).
Rounds 2+: "GPT calls `evaluate_plan`… GPT then **revises** the implicated section(s) via revision
tools and re-evaluates." Completion: "GPT signals completion by calling `finalize_authoring` once
`evaluate_plan` reports all-pass" (memo §1.4). *In this lineage GPT proposes via the tools — the
brief's framing.*

**Lineage B — the restructure protocol spec (`Python proposes / GPT judges`).** **[DOCUMENTED]**
`docs/architecture/p3_33_restructure_protocol_spec.md`: *"Python is the manager. Owns the process…
GPT is the executive. **Brings judgment to ambiguous calls**… The deterministic solver is the line
worker… GPT never sees the line; only the manager's report"* (spec §1.1-1.3). The state machine is
`ROUND_1_AUTHORING → EVALUATE → DISPATCH → CASCADE → FLOOR`
([session_driver.py:20-31](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L20-L31)),
and within the cascade GPT only confirms/vetoes/chooses a **Python-computed** proposal.

**The built code implements Lineage B.** Round-1 authoring is Python `set_*(contract=None)`
deterministic builders (Part 1.3); the cascade computes proposals in `restructure_proposer` and
the responder exposes only confirm/veto/choose/other
([responder.py:75-152](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L75-L152)).
**There is no code path where GPT calls a `set_*`/`revise_*` tool with its own proposed values.**
The Lineage-A "GPT authors via tools" surface is **not built**.

### 2.2 The intended loop (built form), and termination

`SessionDriver.run` ([session_driver.py:254-302](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L254-L302)):
evaluate → if META failing, halt+floor → if `all_pass`, terminate RESOLVED → else pick worst
failing mode (priority order) → walk that mode's cascade tiers (each tier: Python proposes,
responder judges, accepted proposals apply via `revise_*` and re-evaluate) → progress check →
on 2× no-progress or budget exhaustion, floor-all and exit. Iteration is driven by per-mode
cascade tiers + a tool-call budget (default 35,
[session_driver.py:167](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L167));
termination states at [:86-91](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L86-L91)).
`finalize_authoring` requires `all_pass=True`
([session_driver.py:1206-1236](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L1206-L1236)).
**[DOCUMENTED]**

### 2.3 Where payroll authoring lands

`schedule.py:2200-2207` anchors it: authoring authority "belongs to the amalgamated GPT session
via `post_intake_amalgamated.tools.set_payroll_schedule`… until then this orchestrator entry
returns a structurally-valid empty payroll payload." **[DOCUMENTED]** Verified that the "until
then" is still the live state — the `contract=None` path returns the stub (Part 1.3).

---

## Part 3 — The gap: built vs not-built

**Built and wired (verified):**
- `build_mirror` + Contract-7 boundary enforcement; assembled post-round-1 in the runner
  ([runner.py:1852-1859](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1852-L1859)).
- `evaluate_plan` (both modes) + `EvaluatePlanResult` + `FailureMode` classification.
- Round-1 deterministic authoring for stage_ramp and capex/R&D/balance-seed
  ([runner.py:862](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L862),
  [:1036](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1036)).
- `SessionDriver` state machine, cascade walk, floor primitives, oscillation/bound-relaxation
  guards, diagnostics, fail-fast.
- The four `revise_*` tools + dispatch
  ([session_factory.py:87-168](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L87-L168)).
- The **production responder is a real OpenAI call** (`gpt-5.1`, Chat Completions, `tool_choice:
  required`) ([responder.py:333-350](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L333-L350),
  [:405-433](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L405-L433)).
- Factory + audit-wrapped run, wired into the live runner
  ([runner.py:1865-1882](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1865-L1882)).
- E2E confirmed to run up to deferred payroll via the intake-bypass harness
  ([Test Files/run_intake_bypass.py](../../Test%20Files/run_intake_bypass.py)).

**Not built (the actual remaining work):**

1. **A real payroll round-1 producer.** Today `set_payroll_schedule(contract=None)` → pending
   stub ([set_payroll_schedule.py:266-273](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L266-L273)).
   The cascade's `revise_payroll_schedule` can only *patch* an existing contract — it cannot
   author one from an empty stub. **Nothing produces a real payroll schedule anywhere.** This is
   the headline gap and the thing the brief's "authors the full plan incl. payroll" is really
   asking for.

2. **A decision on GPT's role for the unbuilt surfaces (Lineage A vs B).** If payroll (and
   drivers) should be GPT-*authored* (Lineage A), that authoring surface does not exist and would
   be new. If they should be Python-deterministically authored and GPT-*judged* (Lineage B, what
   the rest of the system does and what the user's "Python proposes; GPT critiques" doctrine
   says), then the work is a Python payroll producer + letting the existing cascade/responder
   judge it. **[ASSUMPTION]** that Lineage B is the intended convergence, on the strength of the
   built code + the standing doctrine — but this is exactly the call to confirm.

3. **GPT judgment is gated on `OPENAI_API_KEY`.** With no key the responder returns a synthetic
   veto and the floor authors everything deterministically
   ([responder.py:468-469](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L468-L469)).
   So "the loop runs" today even with zero GPT contribution. Proving the *Executive* (not just the
   floor) requires a keyed run and a check that GPT's confirm/veto actually moves outcomes.

4. **`structural_completeness=True` is hard-coded** at
   [session_factory.py:221](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L221),
   so the documented mini_finmo→full-gate switch (memo §1.3) never engages in the live path.
   Confirm intended.

5. **No `revise_operating_model`** — price/utilization/capacity cascade tiers (V3/V4/V5/G2-G4/
   C1/C2) log but cannot apply ([session_factory.py:78-84](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L78-L84)).
   A gap for any mode that needs to pull those levers.

---

## Part 4 — Proposed build sequence (minimal slice → full)

Ordering reflects dependencies; each slice is independently verifiable. **[ASSUMPTION]** — this is
a suggested sequence, not a selected plan.

**Slice 0 — Settle the role question (no code).** Confirm Lineage B (Python authors round-1
deterministically; GPT judges via the existing responder) is the convergence, or that Lineage A
(GPT authors via tools) is wanted instead. Everything below assumes B; A would require a new GPT
authoring surface and re-scoping.

**Slice 1 — Real payroll round-1 producer (smallest end-to-end proof).** Replace the
`build_pending_payroll_stub` path so `set_payroll_schedule(contract=None)` returns a real,
band-valid, deterministically-authored payroll contract (the "Python proposes" half), keeping the
tool's existing validate→build path
([set_payroll_schedule.py:316+](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L316)).
Proof: an intake-bypass run reaches `build_mirror` with a non-empty `payroll` plan_state and the
`payroll`-implicated check (`fixed_cost_burden_…`) evaluates against real numbers. This is the
single smallest change that turns "runs up to the deferred payroll" into "authors payroll." Update
the stale runner comment ([runner.py:1186-1193](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1186-L1193))
as part of the same change (per the "remove/convert legacy, don't route around it" rule).

**Slice 2 — Prove the Executive (GPT) actually contributes.** Run keyed (`OPENAI_API_KEY` set) on
a fixture and confirm a confirm/veto/choose on a payroll-implicated tier changes the committed
plan vs. the synthetic-veto/floor path. Proof: divergent `restructuring_log` rows
(`AMALGAMATED_GPT_CONFIRMED` vs `DETERMINISTIC_FLOOR`).

**Slice 3 — Close the cascade's payroll revision loop.** Confirm `revise_payroll_schedule` patches
the now-real contract correctly under each payroll-touching cascade tier; add a payroll floor
primitive if mode exhaustion can strand payroll out of band.

**Slice 4 — Full plan.** Bring drivers authoring to parity (today cascade-authored via
`revise_drivers`); decide on `revise_operating_model`; revisit the hard-coded
`structural_completeness`.

Dependency note: Slice 1 strictly precedes 2-4 (no real payroll → nothing downstream to judge or
revise).

---

## Part 5 — Where revenue-grounding attaches (attach points only)

From `payroll_schedule_revenue_grounding_research.md`, the substantive levers were **D1**
(own-revenue payroll/headcount anchor), **D4** (revenue-derived required-capacity context), **D2**
(staff-to-revenue instruction), and the **doctrine reconciliation** ("revenue is downstream of
FTE" wording). In the Executive build these attach as follows — **identifying** the seams, not
designing them:

- **D1 + D4 (own-revenue anchor / required-capacity) → the new payroll producer (Slice 1).**
  Because round-1 payroll is authored by Python (Lineage B), the revenue-grounding inputs belong
  in that producer, not in a GPT prompt. The producer already receives `model_input_json`,
  `finmo_json`, and `stage_ramp_contract` at the `set_payroll_schedule` boundary
  ([runner.py:1197-1212](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1197-L1212);
  signature [set_payroll_schedule.py:161](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L161)) —
  i.e. the per-quarter revenue trajectory the research says is "already in the room." This is the
  single attach point that makes the research's preferred options own-data-grounded by
  construction.

- **D2 (staff-to-revenue instruction) → the responder system prompt + the proposer rationale.**
  GPT's judgment text is framed by the system prompt
  ([responder.py:159-170](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L159-L170))
  and the per-proposal rationale rendered by `render_mirror_for_proposal`
  ([responder.py:181-247](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L181-L247)).
  A "does this staffing fit the revenue plan?" judgment instruction attaches there. Note the role
  inversion vs. the research: GPT *critiques* revenue-fit rather than *authoring* to revenue.

- **D3 / D5 (tighten/relocate the band check) → `evaluate_plan` + bands.** The payroll/revenue
  feasibility check and class bands live in the standards layer; the Executive consumes them via
  `evaluate_plan`'s payroll-implicated checks ([evaluate_plan.py:74](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L74))
  and the per-section `bands` in the Mirror. Tightening is a standards-layer change independent of
  the GPT layer (as the research already concluded).

- **Doctrine reconciliation ("revenue downstream of FTE") → the Mirror invariants/authority
  text.** The conflicting framing lives in the static directive strings
  ([mirror.py:49-68](../../python/client_intake_and_finmo/post_intake_amalgamated/mirror.py#L49-L68)) —
  specifically the `adaptation` invariant's "holistically across price, payroll, utilization…"
  wording — and in the responder system prompt. Any "staff toward revenue" message must be
  reconciled with the capacity-primary doctrine *here*, once, so the Executive does not receive
  contradictory guidance. **[ASSUMPTION]** that these two strings are the only doctrine surfaces
  the Executive reads; verify no third copy in the proposer rationale templates before wording.

---

## Part 6 — Hard-rule compliance

Scope/design only — no code, no implementation, no act-recommendation. Every codebase claim is
file:line grounded. Documented intent vs. assumption is marked throughout. The central honesty
flag is surfaced up front: the brief's "GPT proposes moves via set_\* tools, authors the full
plan" describes **Lineage A**, while the **built** system is **Lineage B** (Python proposes,
GPT judges; payroll round-1 still a pending stub) — the reconciliation of those is Slice 0 and
gates the rest. The stale runner comment at
[runner.py:1186-1193](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1186-L1193)
is flagged for correction as part of the payroll producer work.
