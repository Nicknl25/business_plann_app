# P3.33 — Post-Intake Amalgamation Design Memo

**Status:** Design only. HOLDS for user approval before any Phase 3
implementation. Companion to the P3.33 directive and to
[p3_32_adaptive_self_healing_design.md](p3_32_adaptive_self_healing_design.md)
(§10.6–§10.9 deterministic-floor / reconciliation / fragility / consistency
doctrine, which this design inherits).

**Thesis.** Today multiple GPT *authoring* sessions (H4 stage-ramp, Handler C
payroll, H2 driver/exhaustion anchors, plus the per-step scalar GPT calls)
each see local context and must produce outputs that agree at finalize. They
agree only by luck (K11: 19% completion). This memo replaces those
independent authoring sessions with **one amalgamated GPT session** that holds
a comprehensive mirror of plan state, authors every surface in a single
coherent context bounded by Python-computed bands, can revise prior commits,
and is backstopped by a Python deterministic floor. The deterministic solver,
adaptation cascade, and cash pass are **not** GPT and do not change.

---

## 0. Scope — what amalgamates, what does not

The post-intake pipeline is driven by a SQL **sequence table**
(`post_intake_process_sequence_lookup`) the orchestrator
(`post_intake_solver/orchestrator.py`) walks. Its steps split cleanly:

| Sequence step | Today | After amalgamation |
|---|---|---|
| `maintenance_capex_percent` (GPT) | separate GPT call | **amalgamated GPT tool** |
| `r_and_d_applicability` (GPT) | separate GPT call | **amalgamated GPT tool** |
| `balance_sheet_contextual_seed` (GPT) | separate GPT call | **amalgamated GPT tool** |
| `stage_ramp_contract` (GPT = "H4") | separate GPT session | **amalgamated GPT tool** |
| `payroll_headcount_schedule` (GPT = "Handler C") | separate GPT session | **amalgamated GPT tool** |
| `unified_convergence_decision` (GPT) | separate GPT session, ≤10 calls | **amalgamated GPT revision rounds** |
| post-cascade exhaustion anchors ("H2") | separate GPT session | **amalgamated GPT revision rounds** |
| `cash_strategy_review` (GPT) | separate GPT session | **stays separate** (directive: cash pass untouched) |
| solver / target-seeking / cascade / path-stamp / restoration | deterministic | **unchanged** |
| `quarter_grid_generation`, FINMO, finalize, workbook | deterministic | **unchanged** |

So: **the GPT authoring surfaces collapse into one session; the deterministic
spine (solver, cascade, cash pass, finalize, workbook) is preserved.** This is
consistent with the directive's PRESERVED list and with doctrine §1
(Python-deterministic-first).

The amalgamated session runs **in place of the pre_convergence + initial_grid
GPT steps and the convergence/exhaustion GPT loop** — i.e. it authors the full
opening configuration and then revises it under validator feedback until the
deterministic finalize accepts (or the floor commits).

---

## 1. Amalgamated GPT session flow

### 1.1 Session start (mirror construction)
On entry the orchestrator builds the **initial mirror** (§2) from the draft's
structured intake JSON + the freshly built baseline `model_input`/FINMO +
resolved bands (§4) + the sequence table (§5). The session opens with a system
prompt stating the three invariants (realism, viability, adaptation), the
authority it holds (may revise any Q1-onward value; Stub 0 immutable), and the
tool catalog (§3).

### 1.2 Round 1 — sequence-driven authoring
The GPT is handed the **round-1 sequence** (from
`post_intake_process_sequence_lookup`, the authoring steps in `step_order`):
ramp contract → maintenance capex / R&D / balance-sheet seed → payroll →
drivers. For each step it calls the section's authoring tool with proposed
values; the tool validates against bands + contract schema and returns
accept/violation + the relevant bands inline (§3). GPT proceeds in sequence
order but is not forced to one call per step — it may consult a `check_*` tool
first.

### 1.3 Rounds 2+ — revision until coherent
After round 1, GPT calls `evaluate_plan` (wraps the deterministic
trajectory/viability check, `mini_finmo.compute_trajectory_from_anchors` + the
16-check acceptance preview). The result is the mirror's validation state:
which invariants pass/fail, per-quarter distance-to-feasibility, and which
section each violation implicates. GPT then **revises** the implicated section(s)
via revision tools (§3.3) and re-evaluates. This loop is the amalgamated
replacement for both the H2 exhaustion handler and the `unified_convergence`
GPT loop.

### 1.4 Completion
GPT signals completion by calling `finalize_authoring` once `evaluate_plan`
reports all-pass. Control returns to the deterministic orchestrator
(target-seeking solver → cascade → cash pass → finalize → workbook), exactly as
today. GPT does **not** run the solver; it authors the configuration the solver
then fits and the cash pass funds.

### 1.5 Deterministic floor activation
The Python floor (§7) activates when **any** of:
- the tool-call budget (target 25–40, hard cap configurable) is exhausted
  without an all-pass `evaluate_plan`;
- GPT calls `finalize_authoring` but the deterministic finalize/acceptance gate
  rejects;
- a GPT turn exceeds the latency ceiling repeatedly (B2), degrading to floor.

The floor computes an in-bounds configuration per surface (reusing the existing
robust-bound, viability-floor, and revenue-reconciliation logic, §7) and commits
it, so no run terminates in "authoring exhausted without output" (§10.6).

---

## 2. The mirror

The mirror is the single context object handed to GPT and refreshed in each
tool response. It is **compact** (the K12.1 compaction principle carries over):
summaries and deltas, not full history.

| Mirror section | Contents | Source |
|---|---|---|
| `invariants` | the three invariants + authority statement | static |
| `business_facts` | NAICS, stage, consumer_type, scale anchors, start date | `operating_model_json` + draft flat cols (`build_shared_context`) |
| `plan_state` | committed values across all sections: ramp grid, payroll grid, drivers, capex/R&D, balance-sheet seed | live `model_input` + section commits |
| `sequence_position` | current step, remaining round-1 steps, round number | `post_intake_process_sequence_lookup` |
| `bands` | per-section constraint envelopes (min/target/max per lever) | bands table (§4) |
| `validation_state` | per-invariant pass/fail **with specifics**: failing checks, per-quarter distance-to-feasibility, constraint margins, implicated section | `evaluate_plan` (wraps `mini_finmo` viability + acceptance-gate preview) |
| `recent_decisions` | last N tool calls + their effect on validation_state (not full transcript) | session ring buffer |
| `budget` | tool calls used / remaining; latency margin | session + L-4 runtime status |

**Token budget.** Typical draft mirror ≈ comparable to today's largest single
handler context (Handler C compacted ≈ a few KB of JSON). Worst case (20-quarter
grids across ramp + payroll + drivers, full bands) is larger; the mirror keeps
grids as compact arrays and bands as min/target/max triples, and `recent_decisions`
is capped at N. A precise token estimate is produced during Phase 3 step 1
against the Sunny Glaze and Skyward baselines (the bypass runner makes this cheap
to measure). **Open question Q3 (§11):** target N and hard token ceiling.

---

## 3. Tool design

Every tool **wraps existing functionality** — the logic stays, the orchestration
changes. Tools return their result **plus the relevant bands inline**, so GPT
sees constraints next to outcomes rather than as separate context.

### 3.1 Read / consult tools (read-only)
| Tool | Wraps | Returns |
|---|---|---|
| `get_bands(section)` | `cohort_band_resolver.resolve_cohort_band` + bands table (§4) | min/target/max per lever for the section |
| `get_stage_ramp_bounds_per_quarter()` | existing H2 consult tool | per-quarter rev/cogs/marketing/rd/ga/ni/util bounds |
| `get_payroll_sanity_bounds(labor_class)` | Handler C tool | per-class payroll %-of-revenue bounds |
| `find_classes_accepting_target_payroll_pct(pct)` | Handler C tool | accepting/rejecting classes |
| `evaluate_plan()` | `mini_finmo.compute_trajectory_from_anchors` + acceptance-gate preview | viability checks (5 universal + 7 stage-ramp coherence), per-quarter distances, all_pass |

### 3.2 Authoring tools (band/contract-checked, write to section state)
| Tool | Wraps | Authority |
|---|---|---|
| `set_stage_ramp_contract(grid)` | H4 builder + `post_intake_gpt_contract` validation | writes ramp grid |
| `set_payroll_schedule(contract)` | Handler C `build_payroll_headcount_payload_from_contract` + validator | writes payroll grid |
| `set_drivers(anchors)` | H2 `_write_gpt_authored_per_quarter_values` | writes P&L/WC driver anchors |
| `set_capex_rd_balance_seed(values)` | the three pre_convergence scalar GPT steps | writes capex %, R&D toggle, BS seed |

Each authoring tool validates against the band envelope + the contract schema
(`post_intake_gpt_contract_lookup`) and returns `accepted | violations[]` with
the bands echoed. A rejected call does not mutate state.

### 3.3 Revision tools (the adaptation spine — critical)
GPT must be able to **revise**, not only add. Revision is what makes
restructuring possible.
| Tool | Effect |
|---|---|
| `revise_section(section, patch)` | apply a partial update to an already-committed section; re-validate that section against bands |
| `restructure_from_q1(field, value, reason_code)` | modify an intake-derived Q1-onward assumption (e.g. add capex an airline lacked, raise price, cut headcount); **writes a `restructuring_log` row (§6)**; never touches Stub 0 |
| `relax_lowest_priority_bound(reason_code)` | when `evaluate_plan` shows a provably empty feasible region, deterministically relax the lowest-priority bound by declared priority order and record it (§10.7/P5.1-3) |
| `finalize_authoring()` | declare done; allowed only when `evaluate_plan.all_pass` |

`restructure_from_q1` and `relax_lowest_priority_bound` carry **enum reason
codes** (not prose), satisfying the directive's "numbers only for now" audit
requirement.

---

## 4. Band table (SQL) — NEW

Today bands are computed in-memory per run by `cohort_band_resolver.py` from
`industry_metrics_edgar` / `industry_metrics_alpha` and **not persisted**. The
amalgamated GPT needs bands available as inline tool responses and the run needs
them auditable, so we materialize them.

**Table `post_intake_cohort_bands`:**
```
draft_id            VARCHAR(64)   -- run scope
planning_run_id     VARCHAR(64)
section             VARCHAR(64)   -- 'stage_ramp' | 'payroll' | 'drivers' | 'capex_rd' | 'balance_sheet'
lever_id            VARCHAR(128)  -- joins post_intak_mapping_lookup lever semantics
metric_key          VARCHAR(128)
benchmark_min       DECIMAL(18,6)
benchmark_target    DECIMAL(18,6)
benchmark_max       DECIMAL(18,6)
robust_min          DECIMAL(18,6) -- after robust-bound clip to canonical envelope (K13 Fix 2)
robust_max          DECIMAL(18,6)
naics_level_used    TINYINT       -- 6..2
cohort_size         INT
firm_count          INT
confidence_tier     VARCHAR(16)   -- high|medium|low
cohort_table        VARCHAR(16)   -- edgar|alpha
resolved_at         DATETIME
PRIMARY KEY (draft_id, planning_run_id, section, lever_id, metric_key)
```

**Populated** during the solver, **before** the amalgamated GPT runs (in
`prepare_initial_grid_for_draft`, right after baseline `model_input`), by calling
the existing resolver for each lever and applying the existing
`robust_bound_stage_ramp_contract` clip. The `get_bands` / authoring tools query
this table. This converts the existing in-memory computation into a persisted,
auditable artifact — it does not replace the resolver logic, it stores its output.

---

## 5. Sequence table — EXISTING, lightly updated

`post_intake_process_sequence_lookup` already encodes phases, `step_order`,
`executor_function`, `contract_name`, `required_context_keys_json`,
`produced_output_keys_json`, `output_storage_json`. The amalgamated session
**reuses** it:

- The authoring steps (`stage_ramp_contract`, `payroll_headcount_schedule`,
  `maintenance_capex_percent`, `r_and_d_applicability`,
  `balance_sheet_contextual_seed`, `unified_convergence_decision`) get a new
  column `authoring_owner = 'amalgamated_gpt'` (vs `deterministic`).
- A new `round` field (1 = round-1 authoring order; NULL = revision-eligible
  any round) tells the session which steps form the round-1 sequence.
- The orchestrator, instead of invoking each step's separate GPT
  `executor_function`, hands the amalgamated session the ordered authoring steps
  and lets it drive; deterministic steps keep their `executor_function`.

GPT receives the round-1 sequence as part of the initial mirror
(`sequence_position`), not as a separate tool call.

**No second/competing sequence table is created** (doctrine: no conflicting
code paths). The existing one is updated in place.

---

## 6. Restructuring audit (SQL) — NEW

No `restructuring_log` exists today. Create one; numbers/enums only (narrative
later, per directive).

**Table `post_intake_restructuring_log`:**
```
id                BIGINT PK AUTO_INCREMENT
draft_id          VARCHAR(64) NOT NULL
planning_run_id   VARCHAR(64) NOT NULL
field_modified    VARCHAR(128) NOT NULL   -- canonical lever_id / model_input field
quarter_index     INT NULL                -- NULL = scalar / all-quarter
original_value    DECIMAL(18,6) NULL
restructured_value DECIMAL(18,6) NULL
reason_code       VARCHAR(48) NOT NULL     -- enum: VIABILITY_FLOOR, EMPTY_FEASIBLE_REGION,
                                           --   UNDERCAPITALIZED, MISSING_CAPEX, OVER_STAFFED,
                                           --   REVENUE_RECONCILE, BOUND_RELAXED, ...
applied_by        VARCHAR(32) NOT NULL     -- 'amalgamated_gpt' | 'deterministic_floor'
created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
KEY ix_draft_run (draft_id, planning_run_id)
```
Written by `restructure_from_q1`, `relax_lowest_priority_bound`, and the
deterministic floor whenever it changes an intake-derived Q1-onward value. Stub 0
is never logged because it is never modified.

---

## 7. Deterministic floor for the amalgamated GPT

Activation: §1.5. The floor **reuses the logic that already exists**, now as a
single Python pass instead of three handler-local fallbacks:

1. **Stage ramp** → `robust_bound_stage_ramp_contract` (K13 Fix 2): clip every
   ramp field to the canonical economic envelope; re-validate; commit.
2. **Drivers / viability** → `apply_viability_floor` (K13 Fix 3): pull each
   per-quarter cost ratio down to its realistic target, then step COGS down
   (min 0.20) until Q11 EBITDA ≥ 0.
3. **Revenue coherence** → `reconcile_revenue_to_stage_ramp` (K13 Fix 4 / §10.7):
   clamp driver-implied revenue QoQ growth to the ramp band by scaling
   utilization then price.
4. **Payroll** → deterministic class/FTE selection from
   `find_classes_accepting_target_payroll_pct` at the band target.
5. **Restructuring when still infeasible** → if no in-bounds config satisfies
   all invariants, relax the lowest-priority bound by declared priority order,
   log it (§6), retry. This is Python doing the restructuring GPT couldn't.

Every floor write that changes an intake-derived value logs to §6 with
`applied_by='deterministic_floor'`. The floor always terminates in a committed,
in-bounds, viable state (§10.2, §10.6).

---

## 8. Python's role throughout

Doctrine §1 is preserved and Python's role **expands**:
- **Before GPT:** build baseline `model_input`/FINMO; resolve + persist bands
  (§4); load sequence; construct mirror.
- **During GPT (every tool call):** validate authoring against bands + contract
  schema; run `evaluate_plan` (deterministic `mini_finmo` trajectory + viability
  + acceptance preview); compute distance-to-feasibility and constraint margins
  for the mirror; enforce that Stub 0 is untouched; record L-4 traces.
- **Between GPT and finalize:** the unchanged deterministic solver / cascade /
  cash pass / finalize / workbook.
- **On exhaustion:** the deterministic floor (§7).

GPT supplies judgment (holistic authoring + restructuring choices); Python
supplies every guarantee (bounds, viability math, floor, audit).

---

## 9. Legacy code deletion / conversion plan

Acceptance criterion: **no conflicting code paths, no dead code, no shims.**

### CONVERT (logic → tool implementation; original moved, not duplicated)
| From | To tool |
|---|---|
| `mini_finmo.compute_trajectory_from_anchors`, `_eval_viability_checks` | `evaluate_plan` |
| H2 `_write_gpt_authored_per_quarter_values`, `interpolate_three_anchors` | `set_drivers` |
| H4 stage-ramp builder + `robust_bound_stage_ramp_contract` | `set_stage_ramp_contract` + floor |
| Handler C `build_payroll_headcount_payload_from_contract`, validators, class lookups | `set_payroll_schedule`, `get_payroll_sanity_bounds`, `find_classes_accepting_target_payroll_pct` |
| `cohort_band_resolver.resolve_cohort_band` | bands populator (§4) + `get_bands` |
| K13 Fix 3 `apply_viability_floor`, Fix 4 `reconcile_revenue_to_stage_ramp` | deterministic floor (§7) |
| the three pre_convergence scalar GPT estimators | `set_capex_rd_balance_seed` |

### DELETE (orchestration no longer needed)
- `post_intake_gpt_exhaustion_handler/tool_calling_session.py` — session loop,
  budget/extension, best-effort selection (H2 orchestration).
- `post_intake_headcount/tool_calling_session.py` — Handler C session loop.
- `post_intake_stage_ramp_handler/` session loop + validator-failure engagement.
- `post_intake_funding_handler/` GPT session **iff** funding folds into the
  amalgamated session — **Open question Q2 (§11)** (it is adjacent to cash pass,
  which stays separate).
- The `unified_convergence_decision` GPT loop in `post_intake_convergence`.
- Cross-handler reconciliation glue that existed only to make separate handlers
  agree.
- Per-handler exception types superseded by amalgamated error handling.
- Any partially-built K12 Fix 1b / Fix 3 / Fix 4 scaffolding that was halted.

### KEPT UNCHANGED
Solver (`post_intake_initial_grid/runner.py`), `finmo_bridge.py` + FINMO, cash
pass entirely, workbook generation, **L-4 instrumentation**
(`post_intake_handler_traces` — diagnoses the new architecture too; handler
identifiers gain `amalgamated_gpt`), all intake-side code, all `data_pull`
scripts, the acceptance gate (`post_intake_acceptance/gate.py`), `post_intak_mapping_lookup`,
`post_intake_cash_policy_lookup`, `post_intake_planning_mode_policy_lookup`.

After each Phase 3 commit: grep for dead references (imports, calls, tests,
doctrine §10.5 wording) and remove them in the same commit.

---

## 10. Worked example — Sunny Glaze Donuts

**Intake (Stub 0, immutable):** NAICS 311811, operating bakery, 1 product
(donut), capacity 1200/wk, util 0.75, price ~$2, payroll ~$183k, the K9
regression case (Q11 EBITDA −0.17%).

**Round 1 (sequence-driven):**
1. `get_bands('stage_ramp')` → cogs_max/marketing_max/util bands for 311811
   cohort. `set_stage_ramp_contract(grid)` → accepted within bands.
2. `set_capex_rd_balance_seed(...)` → maintenance capex %, R&D off, BS seed.
3. `get_payroll_sanity_bounds('medium')` → payroll %-of-rev band;
   `set_payroll_schedule(...)` → accepted.
4. `set_drivers(anchors)` → P&L/WC anchors within bands.

**Rounds 2+:** `evaluate_plan()` → fails `ebitda_positive_by_q11` (the K9 fault),
distance shown per quarter, section implicated = drivers. GPT calls
`revise_section('drivers', {cogs_q11: ↓})` within the cogs band, re-evaluates →
gross margin now supports recovery, Q11 EBITDA ≥ 0, all_pass. Calls
`finalize_authoring()`. No restructuring needed → `restructuring_log` empty.

**Restructuring variant — Sunny Glaze with $0 cash override (bypass scenario):**
`evaluate_plan` → `cash_legitimate_q1_q10` fails (negative cash, no debt). GPT
calls `restructure_from_q1('initial_equity', 30000, reason_code=UNDERCAPITALIZED)`
→ logs a row; re-evaluates → cash legitimate; the downstream cash pass funds the
restructured opening. If GPT exhausts budget first, the deterministic floor
relaxes/seeds the same opening and logs it with `applied_by='deterministic_floor'`.

**Restructuring variant — airline (Skyward) with $0 capex:**
`evaluate_plan` → balance-sheet/feasibility fail (an airline cannot operate with
zero PPE). GPT `restructure_from_q1('current_capex', <band-derived>, reason_code=MISSING_CAPEX)`
→ logs, re-evaluates, lands. Same floor backstop.

**Final state:** committed `model_input` flows into the unchanged deterministic
solver → cascade → cash pass → finalize → 16-check acceptance gate → workbook,
exactly as today.

---

## 11. Open questions for approval (HOLD)

1. **Q1 — Sequence reuse vs. rebuild.** I propose **reusing** the existing
   `post_intake_process_sequence_lookup` (add `authoring_owner` + `round`
   columns) rather than authoring a new sequence table. Confirm? (Avoids a
   second source of truth.)
2. **Q2 — Funding handler.** Does `post_intake_funding_handler` fold into the
   amalgamated session, or stay adjacent to the (untouched) cash pass? It sits on
   the cash boundary the directive says not to touch. My lean: **leave it with
   cash pass** for now, revisit in Phase 5. Confirm?
3. **Q3 — Budget & mirror ceiling.** Target 25–40 tool calls (directive) with a
   hard cap, and a mirror token ceiling I'll measure on Sunny Glaze/Skyward in
   Phase 3 step 1. Any preferred hard caps?
4. **Q4 — `evaluate_plan` strictness.** Should `evaluate_plan` expose the full
   16-check acceptance gate every round (heavier, more honest) or the lighter
   `mini_finmo` viability set in early rounds and the full gate near finalize? My
   lean: **light early, full near finalize** to save tokens/latency. Confirm?

These four are the only forks where the design genuinely branches; everything
else follows from the directive + the code facts above.

---

## 12. Phase 3 sequencing (on approval)

1. Bands table (§4) + populator; `get_bands` tool. (commit)
2. Mirror builder (§2) + `evaluate_plan` tool wrapping `mini_finmo`. (commit;
   measure tokens here.)
3. Authoring tools (§3.2) wrapping H4/Handler C/H2 logic; delete their session
   loops. (commits, per surface)
4. Revision tools (§3.3) + `restructuring_log` (§6). (commit)
5. Session driver consuming the sequence (§5) + deterministic floor (§7). (commit)
6. Delete `unified_convergence` GPT loop + cross-handler glue; dead-reference
   sweep. (commit)
7. Doctrine §10.5 reworded for the amalgamated architecture (no duplicate entry).

Each commit ≤800 LOC, suite green, push + email. Total cap 4000 LOC; stop and
email if exceeded. Phase 4 verifies via the Phase 1 bypass runner (3/3 per
§10.9).
