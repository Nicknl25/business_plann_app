# P3.32 K9 — Sunny Glaze Donuts regression investigation memo

**Status:** STOP CONDITION investigation per the directive. NO FIX
proposed. Awaiting user direction.
**Draft:** Sunny Glaze Donuts (`6d37c6b98ace41ee9c91dd5fbf68b83e`)
**Failure type:** V-1 acceptance gate regression (was 16/16
GENUINE_PASS pre-K9; now 13/16 acceptance_gate_failed post-K9).
**V-4 is NOT regressed** — V-4 still PASSES at $2.00 max_abs / 0.0076%
relative, well under the $50 / 0.01% thresholds. The regression is
ENTIRELY at the acceptance-gate K4 realism layer, not at the
financial-model reconciliation layer.
**Migration commit:** `e5b6c33`
phase_9_p3_32_k9_handler_c_tool_calling_migration_stage_b.
**Investigation run:** new draft `870ee804dbb04bbf8fcb92f20e2164b4`
cloned from the persisted source on 2026-05-21 01:58, single
attempt, ran on intake-stable HEAD post-K9 commit.

---

## §1 Which draft failed and exact failure mode

Sunny Glaze Donuts (NAICS 311811 commercial bakery, turnaround
planning mode, pnl_path scope) failed three of the sixteen
acceptance-gate checks at the post-handler verdict.

**Failed checks (op codes):**

1. `realism_gate_no_hard_fail_violations` — FAIL.
   One hard-fail violation:
   - `metric_key`: `ebitda_positive_by_q11`
   - `actual_value`: -0.0016840723320764328 (i.e. -0.17%)
   - `effective_min`: 0.0
   - `band_source`: `universal_viability_doctrine`
   Sunny's EBITDA margin at Q11 is -0.17%; the universal
   viability gate requires it ≥ 0%. Sunny missed the gate by
   17 basis points.

2. `net_income_trajectory_viable` — FAIL.
   Detail:
   - `q11_ni_margin`: -0.002 (i.e. -0.2%)
   - `q5_ni_margin`: -0.2623 (i.e. -26.2%)
   - `q5_to_q11_delta`: 0.2603 (loss recovery)
   - `min_required_delta`: 0.02
   - `min_required_q11_margin`: 0.0
   The Q5-to-Q11 recovery exceeded its minimum (0.2603 vs 0.02),
   so the trajectory IS improving. But Q11 NI margin landed at
   -0.2% instead of ≥0%, so the check hard-fails on the
   absolute level even though the delta is healthy.

3. `viability_timeline_landed` — FAIL.
   This is a roll-up: `ebitda_positive_by_q11` (one of the six
   viability-timeline metrics) hard-failed, so the timeline as a
   whole did not land.

**Pipeline stage:** post-handler acceptance gate
(`acceptance_verdict.passed=False`, `acceptance_score=13/16`).

**Handler trace:**
- `handler_fired`: True
- `handler_scope`: pnl_path
- `handler_status`: **landed_best_effort_no_all_pass**
- `tool_calls_used`: 4
- The H2 GPT exhaustion handler ran for the full 4-call initial
  budget without producing a verified-commit candidate.
- This is the SAME failure shape CareFirst exhibited pre-F6
  (`landed_best_effort_no_all_pass` at 4 tool calls); CareFirst
  resolved post-F6 when payroll re-sync aligned the state mini-
  FINMO was probing against the post-commit FINMO build.

**System-level result:**
- `error`: `acceptance_gate_failed`
- `detail`: `run_did_not_meet_acceptance_criteria`
- HTTP 500 from `/api/intake-consult/system-run`
- `auto_email`: triggered with workbook attached (the automatic
  email-on-failure pathway, not the K9 verification email).

---

## §2 Pre-migration behavior for this draft (P3.28 baseline)

From `docs/architecture/p3_28_sweep_results.csv` (the prior
sweep's persisted baseline):

| Field | Pre-K9 (P3.28) |
|-------|----------------|
| outcome | `GENUINE_PASS` |
| V-1 acceptance | `16/16` |
| handler_status | `landed_best_effort_no_all_pass` (sweep recorded; see notes) |
| tool_calls_used | 2 |
| V-4 max_abs | `0.0` cached (V-4 actually $8.38 per p3_32_v4_baseline.csv) |
| Runtime | 209s |
| Planning mode | `turnaround` |
| Cash strategy | `balanced` |
| Business stage | `operating` |

Note: the P3.28 sweep recorded
`handler_status=landed_best_effort_no_all_pass` (handler fired,
ran 2 tool calls, didn't reach `all_pass`) but the **acceptance
gate at 16/16** still passed because the realism-gate hard-fails
were not present in that pre-K9 run. The acceptance gate is
separate from the handler's internal `all_pass` flag — handler
landing as best-effort can still produce an acceptance-gate-16/16
plan if the gate's K4 realism checks happen to pass on the
best-effort drivers. Pre-K9 they did. Post-K9 they do not.

**The session-context message asserted Sunny was
GENUINE_PASS recent.** That assertion was about runs sometime
between K1 F7 (commit `794bf5d`) and K9 (commit `e5b6c33`). No
record of those runs is in `p3_32_sweep_results.csv` (only
Anderson & Blake, CareFirst, and Skyward have post-K1 rows). The
session-context claim is therefore not directly verified by
artifact, but it is consistent with the P3.28 baseline outcome.

---

## §3 What changed between pre-K9 and post-K9 execution paths

Handler C produced a STRUCTURALLY DIFFERENT payroll
configuration for the same business.

| Field | Pre-K9 (P3.28 archived workbook) | Post-K9 (K9 run) | Δ |
|-------|----------------------------------|------------------|---|
| `labor_intensity_class` | **medium** | **high** | ↑ class |
| `wage_positioning_tier` | **floor** | **market** | ↑ tier |
| `wage_positioning_multiplier` | **1.05** | **1.10** | ↑ 5% |
| `capacity_units_per_supporting_fte` | **20214.13** | **16230.53** | **↓ 20%** |
| `target_payroll_percent_of_revenue` | **0.45** | **0.40** | ↓ 5pp |
| `tool_calls_used` (H2 handler) | 2 | 4 | ↑ effort |

Source for pre-K9: cells in the `Payroll Schedule` sheet of
[docs/architecture/p3_28_sweep_workbooks/6d37c6b98ace41ee9c91dd5fbf68b83e.xlsx](../../docs/architecture/p3_28_sweep_workbooks/6d37c6b98ace41ee9c91dd5fbf68b83e.xlsx)
rows 7-12. Source for post-K9: the run report at
[_logs_5050_k9_v1/05-21-2026 -- 870ee804dbb04bbf8fcb92f20e2164b4.txt](../../_logs_5050_k9_v1/05-21-2026%20--%20870ee804dbb04bbf8fcb92f20e2164b4.txt)
embedded payroll_headcount_schedule JSON.

**Operational interpretation:**

- 2.5 FTE × 20,214 units/FTE = **50,535** supported capacity (pre-K9)
- 2.5 FTE × 16,230 units/FTE = **40,576** supported capacity (post-K9)

That's a **20% reduction in supported revenue capacity**.

Combined with the labor intensity shift (medium → high), the
implied payroll dollars per unit of revenue is higher post-K9.
For a commercial bakery the "high" class operating model
(payroll/revenue band [0.16, 0.70]) is structurally more
expensive than the "medium" class ([0.10, 0.55]). The
exhaustion handler (H2) then has to find PNL driver levers that
hit positive EBITDA Q11 under this heavier payroll burden. Four
tool calls were not enough to find a viable combination.

---

## §4 Why H2's PNL drivers cannot recover

H2's authority is the 7 PNL drivers (revenue triple +
COGS/Marketing/SGA/R&D %) plus 5 WC drivers. Payroll is held
constant at Handler C's authored values during H2's iteration
(per K1 F1+F2 — exhaustion handler explicitly excludes
expenses::Payroll).

When Handler C produces a heavier payroll trajectory than
pre-K9, H2's only remaining levers to push EBITDA back positive
at Q11 are:
- Higher revenue (price, capacity, utilization)
- Lower non-payroll expense ratios (COGS%, Marketing%, SGA%,
  R&D%)

For Sunny (donut shop turnaround), the COGS band is policy-
constrained and the revenue ramp is policy-constrained. The
remaining headroom in Marketing/SGA/R&D is limited. H2 ran 4
tool calls and could not close the gap; it landed at
best_effort with Q11 EBITDA = -0.17%.

---

## §5 Hypothesis for which migration aspect caused the regression

The K9 design memo (D3) explicitly REMOVED two prompt elements
that, in retrospect, were anchoring GPT to specific class
choices:

1. **The "first choose ... labor_intensity_class, wage_positioning_tier"
   pinning framing** (audit P5). Pre-K9
   [schedule.py:2544](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2544)
   said "First choose capacity_labor_model, labor_intensity_class,
   wage_positioning_tier, wage_positioning_multiplier,
   target_payroll_percent_of_revenue, and
   capacity_units_per_supporting_fte..." K9 removed this language
   (per the design memo § D3, "What gets REMOVED from the current
   prompt"). The new K9 SYSTEM_PROMPT
   ([tool_calling_session.py:445-485](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py#L445-L485))
   says only "Class and target are equally mutable. ... You may
   call the three tools in any order any number of times."

2. **The per-class band example "for medium intensity the band is
   0.10..0.55"** (audit L1). Pre-K9
   [schedule.py:2566](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2566)
   named medium specifically as the example class. K9 removed this
   in favor of Tool 1 (`get_payroll_revenue_sanity_bounds`) which
   surfaces all four classes uniformly.

**Hypothesis:** the pre-K9 prompt's "first choose" framing plus
the medium-class example anchored GPT toward medium for businesses
where multiple classes are operationally plausible (a donut shop
could justify medium OR high). With the K9 prompt's open-ended
framing and uniform class presentation, GPT picked high for
Sunny — which IS within-policy but produces a heavier payroll
burden than the operating model needs.

**This is the same architectural property that LET Skyward
converge.** Pre-K9 Skyward was stuck on class=high with target
that high's band rejected; K9 opened the class up. For Skyward,
opening the class up was the cure. For Sunny, opening the class
up moved GPT from a viable medium-class plan to a non-viable
high-class plan.

**The migration was doctrinally clean** (no machinery violations,
no bypass of Mirror Flavor 1 invariants, no upstream state
drift). The regression is a CONSEQUENCE of the prompt's
intentional behavior change — making class choice more flexible.
The pre-K9 anchoring was an implicit bias toward medium that
benefitted Sunny by accident.

---

## §6 Specific file:line citations

| Surface | Pre-K9 | Post-K9 |
|---------|--------|---------|
| "first choose" framing | (deleted) was at `schedule.py:2544` | not present |
| medium-class example | (deleted) was at `schedule.py:2566` | not present |
| GPT prompt for class choice | (single long task_instruction in schedule.py) | [tool_calling_session.py:445-485 (SYSTEM_PROMPT)](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py#L445-L485) and `_build_initial_user_prompt` at [tool_calling_session.py:488-545](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py#L488-L545) |
| Tool 1 schema (replaces prose paraphrase) | n/a | [tool_calling_session.py:137-168](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py#L137-L168) |
| Tool 2 schema (K8 enrichment relocated) | n/a | [tool_calling_session.py:171-189](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py#L171-L189) |
| Tool 3 propose schema | (was schedule.py payload_base text.format.json_schema; deleted) | [tool_calling_session.py:192-220](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py#L192-L220) |
| Sunny payroll pre-K9 | `docs/architecture/p3_28_sweep_workbooks/6d37c6b98ace41ee9c91dd5fbf68b83e.xlsx` Payroll Schedule rows 7-12 | run report `_logs_5050_k9_v1/05-21-2026 -- 870ee804dbb04bbf8fcb92f20e2164b4.txt` (embedded payroll_headcount_schedule JSON) |
| H2 exhaustion handler authority | [post_intake_gpt_exhaustion_handler/handler.py GPT_AUTHORED_LEVER_IDS](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py) (excludes Payroll, per K1 F1+F2 — UNCHANGED) | same — UNCHANGED |
| Mirror Flavor 1 invariant | [schedule.py:assert_payroll_headcount_model_input_applied](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py) + assert_finmo_payroll_matches_headcount_schedule | UNCHANGED |
| K1 F6 re-sync invariant | [orchestrator.py three-surface invariant block](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py) | UNCHANGED |
| H2 tool budget | [post_intake_gpt_exhaustion_handler/tool_calling_session.py:50-52](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L50-L52) (INITIAL_TOOL_CALL_BUDGET=5, EXTENSION=5, HARD_CAP=10) | UNCHANGED |

The H2 exhaustion handler ran 4 of its 10 tool-call budget,
which is BELOW the extension-trigger threshold (5). Either H2
voluntarily stopped iterating before extension OR the session
ended on `gpt_stopped_calling_tool`. Without per-call trace
visibility (which the L-4 instrumentation gap previously
identified in the Skyward investigation also covers), the exact
reason for H2 stopping at 4 cannot be confirmed from current
artifacts.

---

## §7 V-4 status

V-4 reconciliation PASSED on the post-K9 Sunny workbook:
- `max_abs`: $2.00
- `max_rel`: 0.000076 (0.0076%)
- Both well under the doctrine thresholds ($50 absolute /
  0.01% relative).

The model_input → FINMO trajectory is internally consistent. The
Mirror Flavor 1 three-surface invariant (F6) holds. The failure
is purely at the K4 acceptance-gate realism layer, not at any
state-alignment or reconciliation surface.

---

## §8 What this regression does NOT indicate

- **NOT a machinery violation.** No `PostIntakePreconditionFailed`
  fired. No K1 F1-F7 invariant tripped. No F6 mirror invariant
  tripped. The pipeline completed normally; the run ended at the
  acceptance-gate verdict step (which is the expected
  termination point for an in-policy but acceptance-failing
  plan).
- **NOT a Tool 3 validator-chain bug.** Handler C produced a
  contract that passed Layers A.1 + A.2 + A.3 (otherwise
  Handler C itself would have hard-failed with
  `payroll_tool_calling_session_exhausted`, which did not fire).
- **NOT a Mirror Flavor 1 violation.** V-4 reconciliation is at
  $2.00 max_abs, in float-noise range.
- **NOT a K9 over-LOC architectural defect.** Surfaces touched
  are exactly as planned in the design memo D1-D6; no extra
  files were modified.

---

## §9 What this regression DOES indicate

- The K9 prompt restructure changed GPT's class-selection
  behavior on borderline businesses. For Sunny this moved GPT
  from a viable in-policy plan (medium class) to a non-viable
  in-policy plan (high class). For Skyward the SAME
  architectural property was the cure (moved GPT from a stuck
  rejected pattern to a converged accepted pattern).
- The post-K9 Sunny plan is INSIDE the contract validator chain
  but OUTSIDE the K4 universal-viability acceptance gate.
  Handler C does not see the K4 acceptance gate; it only sees
  Layers A.1 + A.2 + A.3 (its own validator chain). The K4 gate
  is the responsibility of the H2 exhaustion handler's all_pass
  flag — and H2 landed best-effort without all_pass.
- This is doctrinally a CareFirst-pre-F6-class failure pattern:
  handler lands best-effort at the gate, gate fails K4
  realism check, plan does not commit. CareFirst-pre-F6 was
  resolved by closing a payroll alignment leak (F6) so the
  handler's mini-FINMO probe operated on canonical state. The
  Sunny case is different — no alignment leak — but the
  end-state shape is the same.

---

## §10 NO PROPOSED FIX

Per the directive:
> If a previously-passing draft fails on first run after
> migration: DO NOT FIX. This is critical.

This memo describes what happened and where to look. No fix is
proposed. The remaining V2 drafts (CareFirst, Anderson & Blake)
HAVE NOT BEEN RUN per the same directive:

> STOP after the failing draft.

Awaiting user direction. Possible directions the user may
choose (not a recommendation — listed for transparency only):

a. Roll back K9. The `pre_k9_archive` branch at commit
   `794bf5d` is on origin specifically for this case.

b. Re-introduce some pre-K9 anchoring language (e.g. an example
   citing multiple class bands instead of just medium, or a
   "consider the simplest class that fits" hint) without
   re-introducing the "revise only named fields" rule or the
   K8 burial that Skyward needed K9 to fix.

c. Investigate whether Handler C's K9 prompt + tool surface
   should expose Sunny's operating model more directly
   (currently the SYSTEM_PROMPT and initial user prompt include
   payroll_decision_options but not the operating model
   summary in a form that biases class selection toward the
   business's actual labor intensity profile).

d. Investigate whether H2 should have run more than 4 tool
   calls before stopping (the per-call trace would clarify
   whether H2 chose to stop or hit a session-level error).

e. Other directions the user identifies.

The investigation is a deliverable; the next decision is the
user's.
