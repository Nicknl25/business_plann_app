# P3.33 — Restructure Protocol Specification

**Status:** Design only. HOLDS for user approval before any Phase 3 step 4 or
step 5 implementation. Companion to
[p3_33_amalgamation_design.md](p3_33_amalgamation_design.md) and to doctrine
§10.6–§10.9 (deterministic-floor / cross-surface reconciliation / preemptive
fragility / consistency-as-acceptance), which this protocol inherits and
operationalises.

**Supersedes:** §3.3 of `p3_33_amalgamation_design.md` (the "revision tools"
sketch). The free-form `restructure_from_q1` / `relax_lowest_priority_bound`
shape described there is replaced by the Python-driven cascade specified
below. Revise that section to point here once this spec is approved.

**Governs:** Phase 3 step 4 (revision tools + `restructuring_log` table),
Phase 3 step 5 (session driver + deterministic floor), and the surviving
fragments of step 6 (delete `unified_convergence` GPT loop, retire
per-handler convergence shims).

---

## 0. Reading guide

This document is long because the protocol is the architectural heart of
P3.33 and every load-bearing decision needs to be explicit. Claude implements
against §3–§13. The user reviews §1–§2 for shape and §14 for the open
decisions that still need a call.

| Section | Audience | Purpose |
|---|---|---|
| §1 — Philosophy | both | The manager/executive/line-worker frame and why this protocol differs from how multi-agent LLM systems usually fail. |
| §2 — Data shapes | both | What already exists in code and what new types the protocol introduces. Grounded in step 2 + step 3 deliverables. |
| §3 — Failure modes | both | The five operational invariants the protocol restructures around. (Cash is out of scope; cash pass runs last, untouched.) |
| §4 — Cascade architecture | implementation | How tiers, levers, and pinning awareness compose. |
| §5 — Per-mode cascades | implementation | The concrete lever sequences per failure mode. |
| §6 — Step semantics | implementation | Type A (Python proposes / GPT vetoes) vs Type B (Python presents / GPT chooses). |
| §7 — Multi-mode handling | implementation | When several invariants fail concurrently. |
| §8 — Escalation & termination | implementation | Tier advance, bound relaxation, floor handoff, termination guarantees. |
| §9 — The deterministic floor | implementation | Same protocol, unattended. |
| §10 — Audit | implementation | `restructuring_log` schema, reason-code enum, what gets recorded. |
| §11 — System integration | implementation | How the protocol talks to the mirror, `evaluate_plan`, authoring tools, cohort bands. |
| §12 — State machine | implementation | The formal process diagram. |
| §13 — Implementation plan | implementation | Step 4 and step 5 scope, acceptance criteria, LOC discipline. |
| §14 — Open questions | user | The handful of design forks where the spec branches and the user must pick. |

---

## 1. Philosophy

### 1.1 Roles: manager, executive, line-worker

The amalgamation isn't "merge multiple GPTs into one." It's "add the manager
layer that was missing." Three roles, one direction of authority.

**Python is the manager.** Owns the process. Knows the protocol. Holds the
standards. Diagnoses failure. Selects which lever is on the table at each
step. Validates the executive's calls. Tracks progress. Escalates when
stuck. Covers when the executive freezes. Has its own decision authority
for routine moves; consults the executive only for judgment calls.

**GPT is the executive.** Brings judgment to ambiguous calls. Operates
within bounds the manager defines. Does NOT own the process. Owns the
*quality of calls within the process*. Has veto power over the manager's
routine moves when this specific business has a reason the defaults
don't fit. Has decision authority at branch points where multiple paths
are equally valid and the choice is a business judgment.

**The deterministic solver is the line worker.** Given a target and
constraints, produces output. Doesn't think about whether the target is
right. Doesn't restructure. Doesn't talk to the executive. The manager
hands it instructions; it executes.

Chain of command is one-directional. Solver never talks to GPT. Python
orchestrates both. GPT never sees the line; only the manager's report.

### 1.2 Why this beats author-and-reconcile

What we left behind (multi-handler architecture):

> Multiple GPT surfaces (H4 stage-ramp, Handler C payroll, H2 drivers,
> pre-convergence scalars) each author independently against local context.
> They must agree at finalize. They agree only by luck — 19% in the K11
> batch. Patches that widened tolerances at the seams created the illusion
> of convergence while structural disagreement compounded underneath.

What this protocol does instead:

> A single executive operates against a single mirror, with the manager
> defining what decision is on the table at each step, the levers available,
> and the priority order. The executive's freedom is in the *quality of
> calls within the structure*, not in the choice of structure. Convergence
> is a property of the process, not a hope at finalize.

### 1.3 The three invariants

From the P3.33 directive, re-stated here because they constrain every
design choice:

- **Realism.** Every committed value is anchored to a cohort band. We do
  not author values that no business of this shape and scale actually
  operates at. The bands table (§2.4) is the source of truth.
- **Viability.** The committed operating plan sustains itself. EBITDA
  positive by Q11, gross margin defensible, growth feasible against
  capacity. Without this the plan is a fiction.
- **Adaptation.** The system restructures when the plan as authored is
  infeasible — it does not fail. If a restaurant needs $250K of opening
  capital to be viable, the operating plan reflects what's needed and the
  cash pass (downstream, untouched) funds it. There is no "infeasibility
  escape" code path.

These rank-order. When they conflict, **adaptation wins over realism wins
over viability**: we will restructure (giving up realism via bound
relaxation) before we accept an infeasible plan; we will accept
non-viability before we accept a non-plan. The protocol's escalation order
encodes this hierarchy.

### 1.4 What makes this protocol distinctive

Three design choices are uncommon enough to call out:

1. **The manager is a peer, not infrastructure.** Many AI orchestration
   systems treat Python as either pure plumbing (LangChain-style) or pure
   validation (let the LLM author freely, reject if invalid). Here Python
   has *first-class judgment*: it decides what step is on the table, it
   selects the lever, it picks the target, it consults the executive only
   when judgment is genuinely needed. Most steps are Python decisions with
   GPT veto; only a minority are GPT decisions with Python options. This
   inverts the usual ratio.
2. **The floor and the GPT-driven cascade share machinery.** The
   deterministic floor (§9) doesn't have its own logic; it's the same
   cascade executed unattended with Python defaults at each step where
   judgment would otherwise be requested. Convergence is guaranteed
   because Python alone can always complete the plan.
3. **Structural diagnostics, not free-form feedback.** `evaluate_plan`
   emits typed data (FailureMode, signed distance-to-feasibility,
   lever margins with pinning flags, section attribution). The protocol
   *dispatches on types*, not on prose. This is closer to a strongly-typed
   compiler pipeline than to a chat-style agent loop.

---

## 2. Data shapes (what already exists)

The protocol does not invent new state from scratch. It composes the
artefacts shipped in step 1 (bands), step 2 (mirror + `evaluate_plan`),
and step 3 (authoring tools). This section enumerates what's available so
§4 onward can refer to fields by name.

### 2.1 `FailureMode` enum (already in code, step 2)

From `post_intake_amalgamated/evaluation_types.py`:

```
CASH_INVARIANT      — present in enum but OUT OF PROTOCOL SCOPE.
                      Cash pass runs downstream and untouched. No cascade.
                      evaluate_plan skips cash checks during amalgamated session
                      per the cash-correction commit (951034b).
VIABILITY_INVARIANT — operations don't sustain (Q11 EBITDA, margin, NI traj.)
GROWTH_INVARIANT    — revenue ramp not feasible vs capacity/utilization
CAPACITY_INVARIANT  — capacity / utilization ceiling mismatched to plan
BAND_INVARIANT      — a committed lever value outside its cohort band
COHERENCE_INVARIANT — two sections disagree (stage_ramp ↔ drivers, util ↔ rev_max)
META_INVARIANT      — gate machinery (stage_reached_finalize, cascade_tier_set, …)
                      NOT restructured. META failures escalate to admin/log.
```

The protocol restructures around five modes: VIABILITY, GROWTH, CAPACITY,
BAND, COHERENCE.

### 2.2 `EvaluatePlanResult` (already in code, step 2)

Fields the protocol reads on every call:

- `all_pass: bool` — convenience top-level pass flag.
- `round_number: int` — increments per evaluate_plan call within a session.
- `structural_completeness: bool` — true once every authoring section is
  authored at least once and accepted.
- `strictness: "mini_finmo" | "full_acceptance_gate"` — light during
  round 1, full once structurally complete (Q4 in amalgamation design).
- `checks: List[CheckResult]` — every check with `passed`, `failure_mode`,
  signed `distance_to_feasibility`, `distance_units`,
  `implicated_sections`, free-form `detail`.
- `lever_margins: List[LeverMargin]` — per-lever current vs band edges
  with `pinned_min`, `pinned_max`, `outside_band` flags.
- `trajectory: List[QuarterTrajectory]` — per-quarter rev/cash/ebitda/etc.
- `worst_failing_check: Optional[str]` and `worst_failing_distance:
  Optional[float]` — quick handles for ring-buffer deltas.

This is the protocol's input vocabulary. It does not need anything more.

### 2.3 Authoring tool envelope (already in code, step 3)

Every `set_*` tool returns:

```
{
  "accepted": bool,
  "section": "stage_ramp"|"payroll"|"drivers"|"capex_rd"|"balance_sheet",
  "contract"|"payload": <validated artifact>,        # only when accepted
  "violations": [ { code, quarter_index?, field?, actual?, band_min?,
                    band_max?, delta?, units, message? }, ... ],
  "bands_echoed": { lever_id: band_dict, ... },
  "decision_source": "amalgamated_gpt_supplied" | "python_deterministic_floor",
}
```

Two input modes per tool:

- `contract=<...>` — GPT supplied an artifact; validate & accept/reject.
- `contract=None` with builder inputs — tool builds the artifact
  deterministically itself (the floor path). Already designed in.

The dual-input shape is the seam that makes §1.4 design choice 2 work:
the floor literally calls the same tools with `contract=None`.

### 2.4 Cohort bands table (step 1)

`post_intake_cohort_bands` is populated before the amalgamated session
runs. Keyed by `(draft_id, planning_run_id, section, lever_id, metric_key)`,
exposing `benchmark_min/target/max`, `robust_min/max`, `confidence_tier`,
`cohort_size`. The protocol reads bands via the `get_bands(section)` tool
and uses them as the source of truth for "in band" and "at target."

### 2.5 New artefacts this protocol introduces

- **`restructuring_log` SQL table** — §10. Per-row record of every
  restructure event with enum reason code, originating section, before/after,
  applied_by, tier, mode. Created in step 4.
- **`RestructureCascade` policy table** — §5. The cascade definitions as
  data, not code, so we can update lever priorities without recompiling.
  Pythonic literal in step 5 unless §14.4 says otherwise.
- **`ReasonCode` enum** — §10.2. Closed set of restructure reasons.
- **`SessionState` machine** — §12. Round, current cascade tier per mode,
  attempts made, last `evaluate_plan` round_number consulted.

---

## 3. The five failure modes (operational scope)

This section *defines* each mode rigorously. The cascade in §5 then *responds*
to it. The classification table itself lives in code at
`post_intake_amalgamated/evaluate_plan.py::_CHECK_REGISTRY` and is the source
of truth for which check belongs to which mode.

### 3.1 VIABILITY_INVARIANT

**Definition.** The operating plan does not produce sustainable operating
economics. Examples:

- Q11 EBITDA margin ≤ 0
- Gross margin below the cohort viability floor at any reported quarter
- Net income trajectory not improving (or improving too slowly)
- Operating margin progression inconsistent with stage

**Implicated sections (primary → secondary):** drivers (cost ratios), then
payroll (labor as % of rev), then stage_ramp (how steady-state is reached),
then capex_rd (depreciation drag and R&D opex).

**Typical cause.** Cost ratios too high relative to cohort, or payroll
sized for a larger business than this scale supports, or stage_ramp pulling
margins down too aggressively in the build phase.

### 3.2 GROWTH_INVARIANT

**Definition.** Revenue growth as authored is not feasible against the
capacity/utilization reality this plan asserts. Examples:

- Stage ramp says revenue grows 18% QoQ but utilization is already at
  cohort max and capacity is fixed
- Q12 revenue exceeds physically achievable maximum
  (price × capacity × max_util) by more than the band tolerance
- BS growth (assets, working capital) inconsistent with revenue growth

**Implicated sections:** stage_ramp, then capacity (operating_model), then
drivers (working-capital days).

**Typical cause.** Stage ramp authored aggressively without checking the
arithmetic ceiling. This was the K11 stage_ramp_revenue_path failure class.

### 3.3 CAPACITY_INVARIANT

**Definition.** Capacity and utilization values are mismatched to the
revenue plan in a way that's not a growth-ramp issue but a structural one.
Examples:

- Capacity so high relative to target revenue that utilization at Q12 is
  below the cohort viability floor (a 200-seat restaurant for $40K/year
  revenue)
- Capacity so low that even at 100% utilization with price at band-max
  revenue can't be reached
- Per-employee productivity implied by capacity and headcount is outside
  the cohort band

**Implicated sections:** operating_model (capacity, utilization, headcount),
then stage_ramp (the ramp that pretended this was feasible).

**Typical cause.** Intake-time capacity values that don't reconcile with
intake-time revenue targets. This is a Stub 0 ↔ Q1+ tension: Stub 0 is
sacred but Q1+ has authority to right-size capacity expectations.

### 3.4 BAND_INVARIANT

**Definition.** A committed lever value is *outside* its cohort band
(below `robust_min` or above `robust_max`). This should be caught at
authoring-tool time and should never appear at `evaluate_plan` time, but
can happen post-hoc when a derived quantity drifts (e.g., implied
utilization from drivers exceeds the operating_model utilization band).

**Implicated sections:** whichever section's `lever_margins` show
`outside_band=True`.

**Typical cause.** Derived quantity drift after a cross-section change.
Or: a tool accepted a value that was at-band, but a later edit elsewhere
made it cross.

### 3.5 COHERENCE_INVARIANT

**Definition.** Two sections disagree on a derived quantity that both
must compute. Examples:

- Stage_ramp asserts revenue grows X%, but drivers + operating_model imply
  it grows Y%, |X−Y| > coherence tolerance
- Util ramp in stage_ramp differs from utilization in driver-implied
  trajectory beyond tolerance
- Payroll % of revenue in payroll section differs from G&A or COGS labor
  share in drivers beyond tolerance

**Implicated sections:** the two (or more) sections in disagreement.

**Typical cause.** The K11 architecture's signature failure. The amalgamated
session reduces incidence (one author, full context) but COHERENCE can
still arise from numerical drift across many revisions; the protocol must
resolve it.

### 3.6 META_INVARIANT (out of restructure scope)

Gate-machinery checks like `stage_reached_finalize` or `cascade_tier_set`.
These are not restructurable — if they fail, something is wrong at the
infrastructure level. The protocol *records* META failures and *escalates*
(logs + halts) rather than attempting restructure. §8.5.

---

## 4. The cascade architecture

The protocol's response to any failure mode is a **cascade**: an ordered
attack on the failure, lowest-disruption lever first, with explicit
escalation when a lever doesn't help.

### 4.1 Cascade structure

A cascade is a sequence of **tiers**. Each tier has:

- A `name` (human-readable; surfaced in audit + reason codes)
- A **lever set** — one or more (section, field, direction) tuples
- A **target rule** — what value to pull the lever to (typically band
  target; sometimes band edge for bounded relaxation)
- A **step type** — Type A or Type B (§6)
- An **exhaustion rule** — when the tier is "done" without success
- An **audit reason code** (§10.2)

Tiers are *ordered by disruption*: tier 1 is the least intrusive way to
attack the failure; tier 8 is the floor. Tiers 1–6 are tuning within
bounds. Tier 7 is bound relaxation. Tier 8 is unattended floor.

### 4.2 Pinning awareness and smart entry

The protocol does not blindly start at tier 1. Before entering a cascade,
it inspects `lever_margins` for the implicated sections and **skips tiers
whose levers are pinned to their non-favorable edge**. If COGS is already
at `band_target` (or below — at the favorable extreme), tier 1 (cost-ratio
tuning) has no headroom; the protocol jumps to tier 2.

This is the "smart entry" mechanism that makes the cascade feel adaptive
rather than mechanical. The cascade *is* mechanical — what's smart is
that Python uses the diagnostic data to skip wasted attempts.

### 4.3 Lever priority within a tier

Some tiers have multiple levers (tier 1 for VIABILITY has COGS, marketing,
G&A, R&D). Within a tier, levers are tried in **priority order**:

1. **Most-out-of-band first.** The lever with the largest unfavorable
   distance from target gets the first attempt.
2. **Largest viability impact second.** Among levers within band, the
   one whose adjustment moves the worst-failing-check the most.
3. **Most headroom third.** Among equally impactful levers, the one with
   the most room to move.

This is a deterministic rule the manager executes; GPT does not pick which
lever within a tier (that would be giving the executive process authority).

### 4.4 Step semantics (preview of §6)

Each tier step is either:

- **Type A — Python proposes / GPT vetoes.** Python computes the proposed
  adjustment (lever, target value, reason code) and presents it to GPT
  with a structured veto question. GPT either confirms (Python applies the
  authoring tool call) or vetoes with a structured reason (Python records,
  advances to next tier). GPT does not pick the value.
- **Type B — Python presents options / GPT chooses.** Python computes 2–3
  candidate adjustments (e.g., raise price within band vs. push utilization
  within band) and presents them to GPT. GPT picks one or asks for a
  fourth. Python applies the picked option.

Most cascade steps are Type A. Type B is reserved for branch points where
multiple paths are equally valid and the choice is a business judgment.

### 4.5 Termination and floor handoff

A cascade terminates in one of four ways:

- **Resolved.** Latest `evaluate_plan` shows the originating mode passes;
  protocol returns control to the session driver, which checks remaining
  modes and either re-enters another cascade or proceeds to
  `finalize_authoring`.
- **Exhausted.** Tiers 1–7 attempted, no resolution. Protocol triggers
  the deterministic floor (tier 8) for the implicated sections.
- **Budget-bound.** Tool-call budget consumed before resolution. Protocol
  triggers the floor.
- **Bound-relaxation cap.** Tier 7 attempts to relax the lowest-priority
  bound; if relaxation alone doesn't yield feasibility within a small
  number of attempts (§8.4), floor.

---

## 5. Per-failure-mode cascades

This is the protocol's policy. Each cascade is specified as a table of
tiers. These tables are the **source of truth** for the protocol's
behavior; they live in a Python policy module
(`post_intake_amalgamated/protocol/cascades.py`) and are loaded by the
session driver at startup.

Notation: a tier line reads
`<tier#> · <name> · <levers> · <target> · <type> · <reason_code>`.

### 5.1 VIABILITY cascade

The most common cascade (the K9 Sunny case). Restructures operating
economics until the plan sustains itself.

| Tier | Name | Levers | Target | Type | Reason code |
|---|---|---|---|---|---|
| V1 | Cost-ratio tuning | drivers: COGS%, marketing%, G&A%, R&D% | band target | A | `VIABILITY_COST_RATIO_TUNED` |
| V2 | Stage-ramp efficiency | stage_ramp: cogs_max trajectory, marketing_max trajectory, ni_floor trajectory | band target per quarter | A | `VIABILITY_RAMP_TUNED` |
| V3 | Pricing | operating_model: unit_price | nearest band edge favorable to viability | B (premium vs value reasoning) | `VIABILITY_PRICING_ADJUSTED` |
| V4 | Utilization | operating_model: utilization_rate; stage_ramp util_floor | band target | A | `VIABILITY_UTIL_ADJUSTED` |
| V5 | Capacity | operating_model: units_per_week_capacity (down only when over-built) | sized to support target revenue at band-target util | A | `VIABILITY_CAPACITY_RESIZED` |
| V6 | Payroll restructure | payroll: class mix and FTE counts | sized to band target payroll %-of-rev | B (which class to shed) | `VIABILITY_PAYROLL_RESTRUCTURED` |
| V7 | Bound relaxation | lowest-priority cost-ratio band (R&D first, then marketing, then G&A) | relax `robust_max` by 5%, capped at 15% cumulative | A | `VIABILITY_BOUND_RELAXED` |
| V8 | Floor | all of the above, unattended, Python defaults | — | (floor) | `VIABILITY_FLOOR_APPLIED` |

**Notes on V3 vs V4:** V3 (pricing) precedes V4 (utilization) because
pricing change is a *positioning* decision (judgment) while utilization
push is a *operational* decision (mechanical). V3 is Type B because
"premium or value position" is a real business call; V4 is Type A because
"push utilization to cohort target" rarely has a business veto.

**Notes on V7:** Bound relaxation is a real authority handed to the
manager. R&D % is relaxed first because R&D in early-stage businesses
varies wildly from cohort; marketing second; G&A third (G&A is the most
universal cost-ratio benchmark and is relaxed last). COGS is *never*
relaxed because the cohort cogs band represents physical economics; if
no cogs in band yields viability, the plan needs structural change (floor).

### 5.2 GROWTH cascade

Restructures the ramp until growth is physically feasible.

| Tier | Name | Levers | Target | Type | Reason code |
|---|---|---|---|---|---|
| G1 | Ramp shape | stage_ramp: revenue_path, util_floor trajectory | reshape to plateau at physically feasible level by Q8 | A | `GROWTH_RAMP_RESHAPED` |
| G2 | Utilization ceiling raise | operating_model: utilization_rate (toward band max) | band target → band max if needed | A | `GROWTH_UTIL_RAISED` |
| G3 | Pricing | operating_model: unit_price (upward within band) | up to band max favorable to growth | B | `GROWTH_PRICING_ADJUSTED` |
| G4 | Capacity expansion | operating_model: units_per_week_capacity | sized to support target rev at band-target util | A | `GROWTH_CAPACITY_EXPANDED` |
| G5 | Target compression | target revenue path itself | compress target to physically feasible ceiling | B (does the business owner accept lower growth?) | `GROWTH_TARGET_COMPRESSED` |
| G6 | Bound relaxation | utilization band max (relax by 5%, capped 15%) | relaxed max | A | `GROWTH_BOUND_RELAXED` |
| G7 | Floor | unattended | — | (floor) | `GROWTH_FLOOR_APPLIED` |

**Notes on G5:** This is the heaviest restructure in the protocol —
compressing the target revenue trajectory itself. It's Type B because the
business owner's growth ambition is a judgment call only the executive
should weigh against arithmetic feasibility. The cascade reaches G5 only
when G1–G4 cannot make the original target work.

### 5.3 CAPACITY cascade

Resolves capacity/utilization mismatches.

| Tier | Name | Levers | Target | Type | Reason code |
|---|---|---|---|---|---|
| C1 | Utilization re-anchor | operating_model: utilization_rate | move toward cohort target | A | `CAPACITY_UTIL_REANCHORED` |
| C2 | Capacity re-size | operating_model: units_per_week_capacity | rebuild to match target revenue × cohort utilization | A | `CAPACITY_RESIZED` |
| C3 | Headcount alignment | payroll: FTE counts; operating_model: per-employee productivity | productivity in band | A | `CAPACITY_HEADCOUNT_ALIGNED` |
| C4 | Target compression | target revenue | compress | B | `CAPACITY_TARGET_COMPRESSED` |
| C5 | Bound relaxation | productivity band | relax `robust_max` by 10%, capped 25% | A | `CAPACITY_BOUND_RELAXED` |
| C6 | Floor | unattended | — | (floor) | `CAPACITY_FLOOR_APPLIED` |

**Notes on C2 over C1:** Re-anchoring utilization is preferred over
resizing capacity, because resizing capacity is a Stub-0-adjacent
restructure (capacity is partly an intake-asserted fact). The protocol
will compress utilization first to fit declared capacity, then resize
capacity to a more cohort-consistent value if utilization compression
isn't enough.

### 5.4 BAND cascade

Direct band violations — usually fast to resolve.

| Tier | Name | Levers | Target | Type | Reason code |
|---|---|---|---|---|---|
| B1 | Clip to band edge | offending lever | nearest band edge | A | `BAND_CLIPPED` |
| B2 | Rebuild section | offending section's full authoring tool with `contract=None` | rebuild from cohort defaults | A | `BAND_SECTION_REBUILT` |
| B3 | Bound relaxation | offending band (only if lever is structurally extreme for valid reasons; very rare) | relaxed | B (rare judgment call) | `BAND_BOUND_RELAXED` |
| B4 | Floor | unattended | — | (floor) | `BAND_FLOOR_APPLIED` |

**Notes:** BAND failures should be uncommon (authoring tools reject
out-of-band proposals up front). When they occur post-hoc they usually
resolve at B1 with a single clip. B3 is rare because most genuine
band-edge cases get caught and resolved earlier in the other cascades.

### 5.5 COHERENCE cascade

Cross-section disagreement. Resolution is reconciliation, not lever-pulling
in the same sense.

| Tier | Name | Action | Target | Type | Reason code |
|---|---|---|---|---|---|
| H1 | Identify anchor | pick which section is "right" (authority order) | stage_ramp > drivers > payroll > capex_rd > balance_sheet (configurable in §14.2) | A | `COHERENCE_ANCHOR_CHOSEN` |
| H2 | Recompute non-anchor | re-author non-anchor section from anchor's implied values | non-anchor's tool called with `contract=None` and anchor-derived inputs | A | `COHERENCE_RECONCILED` |
| H3 | Iterate | re-evaluate; if still incoherent, swap anchor and retry | once | A | `COHERENCE_ANCHOR_SWAPPED` |
| H4 | Bound relaxation | coherence tolerance itself | relax by 5%, capped 15% | A | `COHERENCE_TOLERANCE_RELAXED` |
| H5 | Floor | unattended | — | (floor) | `COHERENCE_FLOOR_APPLIED` |

**Notes on H1:** The authority order is a policy decision. The default
(stage_ramp first) reflects that the ramp is the planning artifact most
expressive of business intent; everything else is derived. §14.2 invites
the user to confirm or revise this order.

---

## 6. Step semantics

The protocol's interaction with GPT has exactly two shapes. Implementation
must enforce that **no third pattern emerges** — that's the rule against
free-form restructuring.

### 6.1 Type A — Python proposes, GPT vetoes

**Mechanics.**

1. Python computes a proposed adjustment: `(section, field, current_value,
   proposed_value, reason_code, rationale_text)`. Rationale is a short
   prose summary Python constructs from the diagnostic data: which check
   is failing, by how much, why this lever, why this value.
2. Python presents the proposal to GPT as a structured veto question
   (template in §6.3).
3. GPT responds with exactly one of:
   - `confirm` — Python calls the authoring tool, records to
     `restructuring_log` with `applied_by="amalgamated_gpt_confirmed"`.
   - `veto` with `reason: <text>` — Python records the veto to
     `restructuring_log` with `applied_by="amalgamated_gpt_vetoed"` and
     `tier_advance=True`, advances to the next tier.
4. After application, Python re-runs `evaluate_plan`. If the originating
   mode now passes, cascade resolved.

**When used.** Most cascade steps (rough estimate: ~70–80%).

### 6.2 Type B — Python presents options, GPT chooses

**Mechanics.**

1. Python computes 2–3 candidate adjustments. Each is a complete proposal
   shape (`section, field, target, reason_code, rationale`).
2. Python presents the options to GPT as a structured choice question
   (template in §6.3) with an `other` escape hatch.
3. GPT responds with exactly one of:
   - `choose: <option_id>` — Python applies that option, records with
     `applied_by="amalgamated_gpt_chose"` and the chosen option ID.
   - `other: <free-form alternative>` — Python validates the free-form
     proposal against bands. If in-band, accepts and records with
     `applied_by="amalgamated_gpt_other"`. If out-of-band, treats as a
     veto, records, advances tier.
4. Re-evaluate as above.

**When used.** Branch points where multiple paths are equally valid and
the business judgment is real (~20–30% of cascade steps).

### 6.3 Question templates

Both templates are short and structured. Long prompts erode quality.

**Type A template.**

```
RESTRUCTURE PROPOSAL — please confirm or veto.

Cascade: {failure_mode} / Tier {tier_id} — {tier_name}
Failing: {worst_failing_check} (currently {distance_to_feasibility}{distance_units})

Proposed change:
  Section: {section}
  Lever:   {field}
  Current: {current_value}
  Target:  {proposed_value}
  Rationale: {rationale_text}

Constraint context (band):
  min: {band_min}  target: {band_target}  max: {band_max}
  Current is {pinning_summary}.

Please respond with:
  CONFIRM  (apply this change)
  VETO: <one-sentence business reason>  (advance to next tier)

You should veto only if this specific business has a reason the cohort
default does not apply. "I'd prefer not to" is not a veto reason; the
cohort target is the realism anchor.
```

**Type B template.**

```
RESTRUCTURE CHOICE — please pick one option.

Cascade: {failure_mode} / Tier {tier_id} — {tier_name}
Failing: {worst_failing_check} (currently {distance_to_feasibility}{distance_units})

Options:
  (A) {option_a.summary}
      Section/field/target: {option_a.section}/{option_a.field}/{option_a.target}
      Trade-off: {option_a.tradeoff_text}
  (B) {option_b.summary}
      Section/field/target: {option_b.section}/{option_b.field}/{option_b.target}
      Trade-off: {option_b.tradeoff_text}
  (C) {option_c.summary} [if applicable]
      ...

Please respond with:
  CHOOSE: A|B|C
  OTHER: <section>/<field>/<value> — <one-sentence reason>

OTHER must be within-band; out-of-band proposals are treated as a veto
and the cascade advances.
```

### 6.4 Response parsing

GPT response parsing is brittle if it's free-form prose. The protocol
**requires** structured tool-call responses from GPT:

- `confirm_proposal()` (Type A confirm)
- `veto_proposal(reason: str)` (Type A veto)
- `choose_option(option_id: str)` (Type B choose)
- `other_proposal(section: str, field: str, value: float, reason: str)` (Type B other)

These are exposed in the amalgamated session's tool catalog as the only
responses GPT can give to a restructure proposal. Any other GPT output is
ignored and the proposal is re-presented (one retry; then Python treats
as veto/no-response and advances).

This is the **strictest** part of the protocol. It prevents GPT from
inventing process. Implementation in step 5.

---

## 7. Multi-mode failure handling

`evaluate_plan` will frequently return multiple failing checks across
multiple failure modes simultaneously. The protocol must have a defined
resolution order rather than ad-hoc handling.

### 7.1 Mode priority

When multiple modes have failing checks, the protocol enters cascades in
this order:

1. **BAND** — fast to resolve, clears noise. Resolving band violations
   first ensures other cascades operate on in-band state.
2. **COHERENCE** — cross-section disagreement makes other diagnoses
   unreliable; resolve before tackling operational invariants.
3. **CAPACITY** — capacity mismatches usually constrain what's possible
   in GROWTH and VIABILITY. Resolve the constraint, not the symptom.
4. **GROWTH** — once capacity is right, ramp issues are clearly visible.
5. **VIABILITY** — last because the operating economics depend on
   capacity, growth, and coherence being right. Solving viability first
   risks immediately undoing the fix when later cascades restructure
   what viability was built on.

This order is **inverse to disruption**: cheap-to-fix first, most-
disruptive last. It also encodes the dependency graph (band/coherence
clears the picture; capacity sets the frame; growth fills the frame;
viability optimises within the frame).

### 7.2 Single-mode resolution per session loop

Within one cascade run, the protocol focuses on **one mode at a time**.
After a cascade resolves its mode (or hands off to floor), `evaluate_plan`
re-runs; the session driver picks the next mode that's still failing per
§7.1 priority and enters that cascade. Repeats until `all_pass` or budget
exhausted.

This is the contrast to the multi-handler past: rather than every handler
reconciling concurrently, the manager works one problem at a time, in a
defined order, with full diagnostic state between steps.

### 7.3 "Progress" between cascades

A cascade is considered to have made progress if, after termination, the
total count of failing checks decreased OR the worst-failing-distance
improved by more than a threshold (§14.5). If a cascade terminates with
no progress, the session driver records "no_progress" and proceeds —
but tracks consecutive no-progress events. Two consecutive no-progress
cascades trigger the floor for *all remaining* failing modes (§8.6).
This prevents thrashing.

---

## 8. Escalation and termination

### 8.1 Tier advance triggers

A tier advances to the next tier when ANY of:

- The chosen lever is **pinned** to its non-favorable edge (no headroom
  to attempt the move).
- GPT **vetoes** the proposal (Type A) or chooses **other** with an
  out-of-band proposal (Type B).
- Python attempted the move and `evaluate_plan` shows the originating
  mode still fails. (One attempt per tier — tiers don't iterate.)
- The lever is the same as one attempted in the previous tier of this
  cascade (oscillation guard).

### 8.2 Single attempt per tier

Each tier gets exactly **one** application attempt. The protocol does
not iterate within a tier with progressively larger adjustments. The
rationale: if pulling COGS from 0.72 to the cohort target of 0.65
doesn't fix viability, the problem is not COGS; further adjustment of
COGS is wasted effort. Advance.

This rule keeps the protocol bounded and prevents the "infinite
adjustment within layer" failure mode common to naive cascades.

### 8.3 Bound relaxation (tier 7 across modes)

Tier 7 (or its mode-specific equivalent) is bound relaxation. The
mechanics:

- Identify the lowest-priority band relevant to the failing mode
  (priority per cascade in §5).
- Relax `robust_max` (or `robust_min`) by a fixed step (default 5%).
- Re-attempt the cascade from tier 1, restricted to levers that
  actually changed due to relaxation.
- If still failing, relax again, **capped at three relaxations** per
  band (cumulative 15%). After cap: floor.

Bound relaxation is logged with `applied_by="amalgamated_gpt_*"` or
`applied_by="deterministic_floor"`, the band name, the cumulative
relaxation amount, and the reason code (e.g. `VIABILITY_BOUND_RELAXED`).

### 8.4 Floor handoff (tier 8)

When a cascade exhausts (all tiers attempted including bound
relaxation), the protocol triggers the **deterministic floor** for that
mode (§9). The floor applies Python defaults across all levers in the
cascade and commits. The cascade's outcome is `FLOOR_APPLIED`.

### 8.5 META failures

META failures (gate machinery — stage_reached_finalize,
cascade_tier_set, etc.) are *not* restructured. They indicate a problem
at the infrastructure level. Behavior:

- Log to `restructuring_log` with `applied_by="meta_escalation"` and
  the META check name.
- Halt the protocol; return control to the session driver with a
  `META_HALTED` status.
- The session driver records the META halt in
  `post_intake_run_diagnostics` and exits the amalgamated session.
- The deterministic floor for the *non-META* state is committed.
  Downstream (cash pass, finalize, workbook) proceeds with what's
  committed.

This treats META as a "stop and notify" rather than "restructure"
condition. It prevents the protocol from trying to restructure around
a broken gate.

### 8.6 Two-cascade no-progress guard

If two consecutive cascade runs terminate with no progress
(per §7.3), the protocol triggers the floor for **all** remaining
failing modes simultaneously, records `STAGNATION_FLOOR_ALL`, and
exits.

### 8.7 Tool-call budget

Default budget: 35 tool calls per session (within the 25–40 range from
the directive). Budget is consumed by:

- Authoring-tool calls (setX, reviseX): 1 each
- evaluate_plan calls: 1 each
- get_bands consults: 1 each
- Type A/B response from GPT: counts as 1 (the response IS a tool call)

When budget reaches 5 calls remaining, the protocol enters
**budget-aware mode**: skips Type A consultations (auto-confirms Python
proposals), only consults GPT for Type B branches. When budget reaches
1 call: floor.

Budget exhaustion records `BUDGET_EXHAUSTED_FLOOR`.

### 8.8 Termination summary

The protocol terminates in exactly one of these states:

| Termination state | When | Floor invoked? | Next |
|---|---|---|---|
| `RESOLVED` | all_pass = true | no | finalize_authoring |
| `MODE_FLOOR` | a single cascade exhausted | yes (one mode) | re-evaluate, continue |
| `STAGNATION_FLOOR_ALL` | two consecutive no-progress | yes (all modes) | exit |
| `META_HALTED` | META check failed | yes (floor as-is) | exit |
| `BUDGET_EXHAUSTED_FLOOR` | budget hit zero | yes (remaining modes) | exit |

Every termination state produces a committed, in-bounds plan. There is
no exit path that produces an unresolved plan.

---

## 9. The deterministic floor

The floor is **not** a separate fallback system. It is the same cascade
machinery, run unattended with Python defaults at each Type A and
Type B step.

### 9.1 Floor mechanics

For a cascade `<mode>` whose tier `<n>` triggered floor:

1. **Replay attempted tiers** with Python applying defaults:
   - At each Type A step: Python's proposal is auto-confirmed.
   - At each Type B step: Python chooses option A (first option in
     priority order — see §5 cascade tables, options ordered
     least-disruptive first).
2. Apply each step via the authoring tool's `contract=None` builder
   path (the path designed for unattended use in step 3 tools).
3. After each step, re-run `evaluate_plan`. If the originating mode
   passes, floor succeeded for this mode.
4. If all tiers including bound relaxation fail, **apply mode-specific
   floor primitive** (§9.2).

### 9.2 Mode-specific floor primitives

When the cascade-as-floor still fails, each mode has a final primitive
guaranteed to commit *something* in bounds:

- **VIABILITY floor primitive.** Use the existing
  `apply_viability_floor` logic (K13 Fix 3): pull cost ratios to
  realistic targets, step COGS down (min 0.20) until Q11 EBITDA ≥ 0.
  Committed even if other invariants degrade. Log
  `VIABILITY_FLOOR_PRIMITIVE`.
- **GROWTH floor primitive.** Use `reconcile_revenue_to_stage_ramp`
  (K13 Fix 4): clamp driver-implied revenue QoQ growth to the band by
  scaling utilization, then price. Committed. Log
  `GROWTH_FLOOR_PRIMITIVE`.
- **CAPACITY floor primitive.** Resize capacity to support target
  revenue at cohort-target utilization, using
  `units_per_week_capacity = ceil(target_q12_revenue / (52 * price *
  cohort_util_target))`. Log `CAPACITY_FLOOR_PRIMITIVE`.
- **BAND floor primitive.** Clip every out-of-band lever to its
  nearest band edge. Log `BAND_FLOOR_PRIMITIVE`.
- **COHERENCE floor primitive.** Re-author every non-anchor section
  from the anchor's implied values (forced reconciliation, regardless
  of tolerance). Log `COHERENCE_FLOOR_PRIMITIVE`.

The primitives are **guaranteed to terminate** (each is a finite
deterministic computation). They may produce a plan that some
downstream check still fails — that's acceptable per doctrine §10.6:
the deterministic floor's contract is to produce a committed,
in-bounds, viable-in-the-floor's-sense state, not a globally optimal
plan.

### 9.3 Floor invocation budget

The floor primitives run after the cascade-as-floor exhausts.
Together they are bounded: at most one primitive invocation per mode,
no recursion, no consultation. The total floor pass is O(modes × tiers)
and completes in seconds.

### 9.4 What the floor never does

- It does not consult GPT.
- It does not invent new levers or new modes.
- It does not modify Stub 0.
- It does not skip the audit log.

---

## 10. Audit logging

Every decision flows through the audit log. This is the foundation for
later narrative reattachment and for diagnostic verification.

### 10.1 `restructuring_log` table

Created in step 4. Schema:

```sql
CREATE TABLE post_intake_restructuring_log (
  id                  BIGINT PK AUTO_INCREMENT,
  draft_id            VARCHAR(64) NOT NULL,
  planning_run_id     VARCHAR(64) NOT NULL,
  failure_mode        VARCHAR(32) NOT NULL,         -- FailureMode enum value
  cascade_tier        VARCHAR(8)  NOT NULL,         -- 'V1'..'V8', 'G1'..'G7', etc.
  cascade_tier_name   VARCHAR(64) NOT NULL,
  reason_code         VARCHAR(64) NOT NULL,         -- ReasonCode enum value
  section             VARCHAR(32) NOT NULL,
  field               VARCHAR(128) NULL,            -- lever name; null when section-level
  quarter_index       INT NULL,                     -- when per-quarter lever
  original_value      DECIMAL(18,6) NULL,
  proposed_value      DECIMAL(18,6) NULL,
  applied_value       DECIMAL(18,6) NULL,           -- equals proposed when confirmed; null when vetoed
  step_type           VARCHAR(8) NOT NULL,          -- 'A' or 'B' or 'floor'
  applied_by          VARCHAR(48) NOT NULL,         -- enum, §10.3
  veto_reason         VARCHAR(512) NULL,
  evaluate_plan_round INT NOT NULL,
  worst_check_before  VARCHAR(128) NULL,
  worst_distance_before DECIMAL(18,6) NULL,
  worst_check_after   VARCHAR(128) NULL,
  worst_distance_after  DECIMAL(18,6) NULL,
  created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY ix_draft_run (draft_id, planning_run_id),
  KEY ix_mode_tier (failure_mode, cascade_tier),
  KEY ix_reason (reason_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 10.2 `ReasonCode` enum

Closed set; lives in `post_intake_amalgamated/protocol/reason_codes.py`.
Cascade tables (§5) reference these by name; any addition is a spec
revision, not an in-line tweak.

```
# VIABILITY cascade
VIABILITY_COST_RATIO_TUNED
VIABILITY_RAMP_TUNED
VIABILITY_PRICING_ADJUSTED
VIABILITY_UTIL_ADJUSTED
VIABILITY_CAPACITY_RESIZED
VIABILITY_PAYROLL_RESTRUCTURED
VIABILITY_BOUND_RELAXED
VIABILITY_FLOOR_APPLIED
VIABILITY_FLOOR_PRIMITIVE

# GROWTH cascade
GROWTH_RAMP_RESHAPED
GROWTH_UTIL_RAISED
GROWTH_PRICING_ADJUSTED
GROWTH_CAPACITY_EXPANDED
GROWTH_TARGET_COMPRESSED
GROWTH_BOUND_RELAXED
GROWTH_FLOOR_APPLIED
GROWTH_FLOOR_PRIMITIVE

# CAPACITY cascade
CAPACITY_UTIL_REANCHORED
CAPACITY_RESIZED
CAPACITY_HEADCOUNT_ALIGNED
CAPACITY_TARGET_COMPRESSED
CAPACITY_BOUND_RELAXED
CAPACITY_FLOOR_APPLIED
CAPACITY_FLOOR_PRIMITIVE

# BAND cascade
BAND_CLIPPED
BAND_SECTION_REBUILT
BAND_BOUND_RELAXED
BAND_FLOOR_APPLIED
BAND_FLOOR_PRIMITIVE

# COHERENCE cascade
COHERENCE_ANCHOR_CHOSEN
COHERENCE_RECONCILED
COHERENCE_ANCHOR_SWAPPED
COHERENCE_TOLERANCE_RELAXED
COHERENCE_FLOOR_APPLIED
COHERENCE_FLOOR_PRIMITIVE

# Protocol meta
META_ESCALATED
STAGNATION_FLOOR_ALL
BUDGET_EXHAUSTED_FLOOR
```

### 10.3 `applied_by` enum

```
amalgamated_gpt_confirmed       — Type A confirm
amalgamated_gpt_vetoed          — Type A veto (no application; logged for audit)
amalgamated_gpt_chose           — Type B chose listed option
amalgamated_gpt_other           — Type B "other" with in-band free-form
amalgamated_gpt_other_out_band  — Type B "other" out-of-band (treated as veto)
deterministic_floor             — Floor step (auto-confirm of Python default)
floor_primitive                 — Mode-specific floor primitive
meta_escalation                 — META halt
budget_aware_auto_confirm       — Type A auto-confirmed because budget low
```

### 10.4 What gets logged

Every restructure attempt — confirmed, vetoed, applied, floor-built —
gets a row. Even vetoes are logged, with `applied_value = NULL` and the
veto reason. This is the audit ground truth for "what did the system
try and what happened."

### 10.5 Stub 0 protection

The protocol never modifies Stub 0 fields. Stub 0 = the intake-declared
structural facts: NAICS, stage, consumer_type, business_name, primary
LOB shape, and any fact tagged `stub_0_immutable` in the draft's
structured JSON. Authoring tools reject any contract that would change
Stub 0; the floor never includes Stub 0 in its lever set. There is no
log entry for Stub 0 changes because there are no Stub 0 changes.

---

## 11. System integration

### 11.1 Mirror updates

After every cascade step that modifies state (confirmed Type A,
chosen/other Type B, or floor step):

- `plan_state[section]` updated with the new contract/payload.
- `validation_state` refreshed verbatim with the latest `evaluate_plan`
  result (per directive §2 rule).
- `recent_decisions` ring buffer appended with `{tool, key_inputs_summary,
  delta_all_pass, delta_worst_distance}`.
- `bands` unchanged unless tier 7 bound relaxation occurred, in which
  case the relaxed band's `robust_*` is updated in-memory (NOT in the
  SQL table — the relaxation is run-scoped and logged in
  `restructuring_log`).

### 11.2 evaluate_plan invocation cadence

- Once at session start (round 1 floor for diagnostics).
- After every Type A confirm or Type B choose.
- After every floor step.
- Not after a veto (no state changed).
- Strictness auto-switches per Q4: `mini_finmo` while
  `structural_completeness=False`, `full_acceptance_gate` once true.

### 11.3 Authoring tool calls

Each tier in §5 corresponds to a specific authoring tool call shape.
The protocol does not invent new tool calls; it composes existing
ones with appropriate `contract` payloads (for GPT-driven steps) or
`contract=None` (for floor steps).

Worked mapping for cascade V1 (cost-ratio tuning):
- Type A proposal: Python builds `revise_drivers({field: proposed_value})`
  call payload, presents to GPT, on confirm executes
  `set_drivers(contract=<patched>)`.
- Floor variant: Python calls `set_drivers(contract=None, ...inputs...)`
  with `cost_ratio_target_override={field: cohort_target}`.

Step 4 builds the `revise_*` partial-patch variants. Step 5 builds the
session driver that composes them via the protocol.

### 11.4 Cohort bands consumption

Bands are loaded into the mirror at session start (already done in
step 2 `build_mirror`). The protocol reads them from mirror state on
every step; it does not re-query the SQL table mid-session except for
audit verification at finalize.

### 11.5 Tool-call budget interaction

Budget consumption table (§8.7) is enforced by a counter on `SessionState`
(§2.5). When the counter ticks below the budget-aware threshold (5),
Type A steps auto-confirm. When it reaches 1, the protocol invokes
the floor for all remaining modes and exits.

---

## 12. State machine

```
                    ┌──────────────────────────┐
   session start ──▶│ ROUND_1_AUTHORING        │
                    └──────────┬───────────────┘
                               │ all sections authored
                               ▼
                    ┌──────────────────────────┐
                    │ EVALUATE                  │◀─────────────────┐
                    └──────────┬───────────────┘                   │
                               │ failures classified by mode      │
                               ▼                                  │
              ┌────────────────────────────────┐                  │
              │ DISPATCH (mode priority §7.1)   │                  │
              └─────┬────────────┬─────────────┘                  │
                    │ all_pass    │ failures remain                │
                    ▼             ▼                                │
         ┌──────────────┐  ┌─────────────────────┐                 │
         │ FINALIZE     │  │ CASCADE             │                 │
         └──────────────┘  │  - smart entry      │                 │
                           │  - tier 1..7        │                 │
                           │  - bound relaxation │                 │
                           └────┬───────────┬────┘                 │
                                │ resolved   │ exhausted           │
                                │            ▼                     │
                                │     ┌──────────────┐             │
                                │     │ FLOOR (mode) │             │
                                │     └──────┬───────┘             │
                                │            │                     │
                                ▼            ▼                     │
                           ┌────────────────────┐                  │
                           │ PROGRESS_CHECK     │──────────────────┘
                           └──────┬─────────────┘
                                  │ 2× no-progress │ budget bottomed │ META
                                  ▼
                           ┌────────────────────┐
                           │ FLOOR_ALL & EXIT   │
                           └────────────────────┘
```

This is the formal process. Implementation in step 5 is a
`SessionDriver` class whose `run()` method walks this graph.

---

## 13. Implementation plan

### 13.1 Step 4 — Revision tools + restructuring_log

**Scope.**

- Create `post_intake_restructuring_log` table (DDL + ensure-table helper).
- Create `ReasonCode` enum module.
- Create `revise_*` partial-patch variants of each authoring tool:
  - `revise_stage_ramp(patch: Dict)` — patches the contract grid,
    re-validates, re-runs robust clip.
  - `revise_payroll(patch: Dict)` — patches the schedule, re-validates.
  - `revise_drivers(patch: Dict)` — patches anchors, re-interpolates.
  - `revise_capex_rd_balance_seed(patch: Dict)`.
- Create logging helpers `log_restructure(...)` that write to the
  table with all fields.
- Create the `confirm_proposal / veto_proposal / choose_option /
  other_proposal` tool stubs (functional but not yet wired into a
  session — that's step 5).

**Budget.** ≤800 LOC (memo cap); realistic estimate 500–650.

**Acceptance.** Each `revise_*` is round-trip tested: patch → re-validate
→ accept; out-of-band patch → reject with structured violation. Logging
helpers write rows correctly.

### 13.2 Step 5 — Session driver + deterministic floor + cascades

**Scope.**

- `protocol/cascades.py` — the §5 cascade tables as Python data.
- `protocol/session_driver.py` — implements the §12 state machine.
- `protocol/floor.py` — the unattended cascade walker + the §9.2
  mode-specific primitives (wrapping the existing K13 Fix 3 / Fix 4
  utilities as floor primitives, not as standalone fallbacks).
- `protocol/restructure_proposer.py` — the Python proposal builders
  per tier (computes proposed_value, rationale_text, tradeoff_text).
- Tool catalog wiring: `confirm_proposal` / `veto_proposal` /
  `choose_option` / `other_proposal` become the only acceptable GPT
  responses during a restructure step.
- Delete `unified_convergence_decision` GPT loop and any remaining
  cross-handler reconciliation shims.

**Budget.** ≤1200 LOC. The session driver is the biggest piece; the
cascades are mostly declarative. Floor reuses existing utilities.

**Acceptance.** §13.3 below.

### 13.3 Acceptance for the protocol as a whole

The protocol is acceptance-tested via Phase 4 against scenarios you
author in the bypass Excel. Specific tests we want passing:

1. **Sunny restaurant viability scenario** (K9 regression case): plan
   that fails Q11 EBITDA. Expected: VIABILITY cascade V1 (cost-ratio
   tuning) resolves at tier 1 with Python proposal confirmed by GPT.
   No floor. `restructuring_log` has one row, reason
   `VIABILITY_COST_RATIO_TUNED`.
2. **Undercapitalized restaurant** ($20K cash, needs $200K of operating
   coverage): expected: amalgamated session authors the operating plan
   correctly with no cash awareness; cash pass downstream funds the
   gap. No restructure rows for cash. Protocol may have rows for
   viability if needed, but the cash gap itself is handled outside.
3. **Airline with $0 capex**: expected: CAPACITY cascade tier C2
   (capacity resize) inappropriate because Stub 0 capacity is high;
   GROWTH/VIABILITY cascades fire instead with operating-side
   restructure. Floor possible if business is genuinely infeasible at
   the asserted scale.
4. **Service business no payroll**: expected: protocol's payroll
   levers are no-ops; cascades that would touch payroll skip those
   tiers via the smart-entry mechanism (§4.2).
5. **High-utilization product business**: expected: GROWTH cascade
   doesn't fire (already at ceiling); CAPACITY may fire to resize.
6. **Conservative growth scenario**: expected: no cascade fires;
   protocol resolves at round 1 with `all_pass`.
7. **Stagnation scenario** (deliberately constructed multi-mode
   failure with no feasible in-band resolution): expected:
   `STAGNATION_FLOOR_ALL` triggers; floor commits; plan finalizes
   with audit rows showing the stagnation.

Each verification scenario gets a curated Excel sheet (Phase 4
authoring jointly with the user). Pass criterion: scenario completes
end-to-end with the expected cascade pattern in `restructuring_log`.

### 13.4 LOC budget summary

| Step | Budget | Estimate |
|---|---|---|
| Step 4 — revise tools + log + reason codes | 800 | 500–650 |
| Step 5 — session driver + floor + cascades | 1200 | 900–1100 |
| Step 6 — `unified_convergence` deletion + sweeps | (net negative) | -300 to +100 |
| Phase 3 total remaining | ~1700 of 1710 left | ~1100–1850 |

Phase 3 total may hit the 4000 cap; if so, stop and email per
discipline. The cap was set with this protocol design assumed.

---

## 14. Open design questions for user approval

These are the forks the spec genuinely branches on. The protocol works
with any choice; the user picks.

### 14.1 Q1 — Bound-relaxation cap (tier 7)

Default in §8.3: each band can be relaxed up to 3 times, 5% each,
cumulative 15%. Alternatives: 2 × 7.5% (cap 15%, less granular), or
4 × 4% (cap 16%, more granular).

**My lean: 3 × 5%** (default). Three attempts is enough granularity to
distinguish "modest relaxation" from "give up and floor"; 5% steps are
small enough that any single relaxation is auditable as a sensible
adjustment, large enough to actually move the cascade.

### 14.2 Q2 — Coherence anchor authority order

Default in §5.5 H1: stage_ramp > drivers > payroll > capex_rd >
balance_sheet. The first-listed is the "right" section in a coherence
conflict; others are recomputed from it.

**My lean: this default**. Stage_ramp is the planning artifact most
expressive of business intent (it encodes the ramp the operator
believes in); drivers are derived; payroll is sized from operating
model + drivers; capex_rd is policy; balance_sheet is the most
derived. Re-deriving downstream artifacts from the most-intent-encoded
upstream is the standard.

### 14.3 Q3 — Step type ratio (Type A vs Type B)

The cascades in §5 default to Type A for most steps, Type B for V3
(pricing), V6 (payroll restructure), G3 (pricing), G5 (target
compression), C4 (target compression), B3 (rare). Rough ratio: 80% A,
20% B.

Alternative: more Type B (give GPT more decision authority). Or less
(make protocol nearly fully Python-led).

**My lean: the default**. Most cascade moves are clear from cohort
defaults; Type B is reserved for genuine business-judgment branches.
This keeps token cost reasonable and preserves the manager/executive
split (executive gets the calls that need judgment; manager handles
the rest).

### 14.4 Q4 — Cascades as data vs cascades as code

Default in §5: cascade tables live as Python data structures in
`protocol/cascades.py`. Alternative: store in SQL (e.g.,
`post_intake_cascade_policy_lookup`) for runtime tweaks without
deploy.

**My lean: Python data for now**, with a path to SQL later if you find
yourself wanting to tweak cascades without re-deploying. The SQL
storage path is a small refactor (~50 LOC) when you want it; doing it
now adds complexity for a flexibility we don't yet need.

### 14.5 Q5 — Progress threshold (§7.3)

Default: a cascade made "progress" if either (a) failing-check count
decreased OR (b) worst-failing-distance improved by ≥ 10% of its
pre-cascade magnitude. Two consecutive no-progress = floor all.

Alternative thresholds: 5% (more permissive, more attempts), 25%
(stricter, faster floor).

**My lean: 10%**. Generous enough that real movement counts as
progress; strict enough that "tiny tweaks that don't actually help"
get caught as stagnation.

### 14.6 Q6 — Veto reason taxonomy

Default in §6.1: GPT vetoes are free-form prose, stored as
`veto_reason VARCHAR(512)`. Alternative: enumerated veto categories
(e.g., `business_model_mismatch`, `intake_directive_specific`,
`luxury_positioning`, etc.).

**My lean: free-form prose for v1**, with a path to enum coding once
we see what veto reasons actually appear in practice. Premature
enumeration would either be wrong or restrictive.

---

## 15. What this spec does not cover

For clarity, things this protocol explicitly leaves to other layers:

- **Cash pass behavior.** Untouched. Runs after `finalize_authoring`.
  Allocates equity/debt to fund whatever operating plan the protocol
  produced. The fact that a restaurant "needs $200K" is communicated
  via the operating plan's working-capital and ramp needs; the cash
  pass funds the gap and the workbook reflects the funding allocation.
- **Narrative reattachment.** Out of scope per directive. The
  `restructuring_log` is structured to support narrative later
  (every event has enum-coded reason, before/after, tier name) but
  the narrative generation is not part of this protocol.
- **Intake-time validation.** Stub 0 is sacred; the protocol respects
  it. If intake produces a structurally impossible Stub 0 (e.g.,
  capacity 0), that's an intake-side issue, not a protocol issue.
- **Workbook generation.** Unchanged. The protocol terminates by
  handing off a committed plan to the existing finalize pipeline.

---

## 16. Acceptance checklist

Before Claude moves to step 4 implementation, this spec needs:

- [ ] User review of §1 (philosophy) and §3 (failure mode definitions)
  for shape and accuracy.
- [ ] User decisions on §14 Q1–Q6.
- [ ] Confirmation that the cascade tables in §5 reflect what the user
  wants for each mode. Anything missing? Anything ordered wrong?
- [ ] Confirmation that the verification scenarios in §13.3 cover the
  ground the user wants verified.
- [ ] Confirmation that the §11 integration points match Claude's
  step 2/3 deliverables (verified by reference to actual code).
- [ ] Confirmation that this spec supersedes §3.3 of the amalgamation
  design memo (the free-form `restructure_from_q1` sketch) and that
  Claude should update the memo accordingly when implementing.

Once these boxes tick, the directive to Claude is "build step 4 then
step 5 against this spec."

---

*End of P3.33 Restructure Protocol Specification.*
