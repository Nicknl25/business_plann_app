# planning_mode Investigation + Stage Derivation (research / scope)

**Status:** research + scope. **No code.** Every claim grounded `file:line`. Finance concepts
labeled *(general knowledge)*.

Companion to [fix_1_viability_standard_spec.md](fix_1_viability_standard_spec.md). Resolves two
things the spec deferred: (1) what `planning_mode` is and whether the new standard supersedes it,
and (2) how to derive lifecycle **stage** from business age instead of the nullable intake
`business_stage`.

---

## 1. WHAT IS `planning_mode` — full map

### 1.1 What it is
`planning_mode` is the existing **profitability-FLOOR system**: per-quarter net-/EBITDA-margin
floors keyed by **mode × stage × quarter-band**. The data lives in
`post_intake_planning_mode_policy_lookup`
([post_intake_mapping.py:28](../../python/client_intake_and_finmo/post_intake_mapping.py#L28); DDL
[:4928-4967](../../python/client_intake_and_finmo/post_intake_mapping.py#L4928-L4967); default rows
[:4795-4926](../../python/client_intake_and_finmo/post_intake_mapping.py#L4795-L4926)). Each row
carries `profitability_floor_q1_q4 / _q5_q10 / _q11_q20` plus stage-specific variants
`_startup / _early / _operational / _mature`
([:4807-4821](../../python/client_intake_and_finmo/post_intake_mapping.py#L4807-L4821)).
The doctrine comment states the design: "Q11 floor ≥ 0.0 for EVERY (mode, stage); stage shifts
WHEN inside Q1-Q11 the floor binds, not WHETHER"
([:4799-4803](../../python/client_intake_and_finmo/post_intake_mapping.py#L4799-L4803)).

### 1.2 ALL modes (full list — and which are live)
The policy table defines **5 modes**:
`rebalance` ([:4806](../../python/client_intake_and_finmo/post_intake_mapping.py#L4806)),
`turnaround` ([:4830](../../python/client_intake_and_finmo/post_intake_mapping.py#L4830)),
`normalize` ([:4854](../../python/client_intake_and_finmo/post_intake_mapping.py#L4854)),
`growth_investment` ([:4878](../../python/client_intake_and_finmo/post_intake_mapping.py#L4878)),
`preservation` ([:4902](../../python/client_intake_and_finmo/post_intake_mapping.py#L4902)).

**But only 3 are reachable.** The validity set is
`_POST_INTAKE_PLANNING_MODES = {"turnaround", "normalize", "rebalance"}`
([post_intake_mapping.py:49](../../python/client_intake_and_finmo/post_intake_mapping.py#L49)), and
the classifier emits only those three (§1.3). `growth_investment` and `preservation` are
**defined-but-dead** — present in the table, never selected. (Flag: dead config to clean up or
wire deliberately.)

### 1.3 HOW a plan's mode is SELECTED — deterministic Python heuristic (NOT GPT, NOT user)
- Sequence step `planning_mode_determination` → executor `determine_planning_mode`
  ([post_intake_mapping.py:726-747](../../python/client_intake_and_finmo/post_intake_mapping.py#L726-L747);
  output stored at `planning_run_json.planning_mode`,
  [:747](../../python/client_intake_and_finmo/post_intake_mapping.py#L747)).
- The producer is pure Python: `determine_planning_mode`
  ([quarter_grid.py:443-483](../../python/client_intake_and_finmo/quarter_grid.py#L443-L483)) →
  `classify_planning_mode` ([quarter_grid.py:411-440](../../python/client_intake_and_finmo/quarter_grid.py#L411-L440)):
  - `ebitda_margin > 0.30` (or `reality_normalization_strategy` preferred) → **normalize**
    ([:423-427](../../python/client_intake_and_finmo/quarter_grid.py#L423-L427))
  - `severity == "severe"` or `ebitda < 0` → **turnaround**
    ([:428-436](../../python/client_intake_and_finmo/quarter_grid.py#L428-L436))
  - else → **rebalance** ([:437-440](../../python/client_intake_and_finmo/quarter_grid.py#L437-L440))
- `resolve_planning_mode` normalizes unknown values to `turnaround`
  ([quarter_grid.py:381-385](../../python/client_intake_and_finmo/quarter_grid.py#L381-L385));
  `available_planning_modes` unions defaults + prompt-library `*.md` files
  ([quarter_grid.py:368-378](../../python/client_intake_and_finmo/quarter_grid.py#L368-L378)).
- **No GPT call and no user field sets the mode** — it is derived from baseline financials +
  diagnosis. (This matters: the new standard can re-derive or replace this cleanly without
  unwinding a user input.)

### 1.4 EVERY consumer of `planning_mode` / `planning_mode_policy` (what breaks if dropped)

| Consumer | What it does | file:line |
|---|---|---|
| **Realism gate profitability floor** | `_planning_mode_policy` → `post_intake_planning_mode_policy_for`; `_profitability_floor_for_quarter` picks q1_q4/q5_q10/q11_q20 and raises the effective band floor on `ebitda_margin` / `net_income_margin` / `operating_margin_percent`; `tolerated_issue_codes` downgrades hard-fail→warn | [validator.py:394-401](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L394-L401), [:323-340](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L323-L340), [:988-994](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L988-L994), [:462-464](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L462-L464) |
| **`stage_planning_ramp_policy`** | builds `validator_rules`, `profitability_postures`, `stage_rules`, `explicit_distress_context` from the mode row | def [post_intake_mapping.py:2759](../../python/client_intake_and_finmo/post_intake_mapping.py#L2759); reads policy [:2876](../../python/client_intake_and_finmo/post_intake_mapping.py#L2876); distress flag [:2812-2815](../../python/client_intake_and_finmo/post_intake_mapping.py#L2812-L2815) |
| **Quarter-grid stage governance** | `_stage_governance_context` calls the ramp policy and emits the binding governance context to the quarter-grid GPT | [quarter_grid.py:912-942](../../python/client_intake_and_finmo/quarter_grid.py#L912-L942) |
| **Stage-ramp contract authoring** | `_stage_family_ni_floors` / `_stage_family_q_postures` derive the per-quarter ni-floor + posture arrays from the policy | [post_intake_contracts/runner.py:670](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L670), [:1650-1690](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1650-L1690), [:1959](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1959), [:2138](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2138) |
| **Prompt selection** | `planning_mode_prompt_file` loads `{mode}.md` for the quarter-grid GPT | [quarter_grid.py:388-393](../../python/client_intake_and_finmo/quarter_grid.py#L388-L393), [:476](../../python/client_intake_and_finmo/quarter_grid.py#L476) |
| **GPT context rows** | `planning_mode` / `planning_mode_context` fed to GPT as business-world context | [post_intake_mapping.py:2333](../../python/client_intake_and_finmo/post_intake_mapping.py#L2333), [:2551](../../python/client_intake_and_finmo/post_intake_mapping.py#L2551) |

**So `planning_mode` does two distinct jobs:** (a) a **numeric FLOOR function** (the
`profitability_floor_q*` enforcement in the realism gate + ramp-contract floors), and (b) a
**posture signal** (`explicit_distress_context`, prompt selection, GPT context) that tells the
authoring engine *what the business is trying to do*. The code already names this split:
`stage_is_reality_limiter` vs `planning_mode_is_operating_posture`
([quarter_grid.py:931-932](../../python/client_intake_and_finmo/quarter_grid.py#L931-L932)).

### 1.5 RECOMMENDATION — supersede the FLOOR job, KEEP the POSTURE job
- **Supersede the floor function.** The new cohort+trajectory standard
  ([spec](fix_1_viability_standard_spec.md)) replaces what `profitability_floor_q*` does, and does
  it more principledly: hand-set per-quarter net-margin floors → **cohort-percentile level +
  convergence-by-deadline + EBITDA breakeven/cumulative gates**. Once the standard is live, the
  `profitability_floor_q*` columns are redundant as the *enforcement* mechanism (they are the very
  point-check ramp-thresholds Fix #1 is replacing).
- **Retain the POSTURE dimension — specifically `turnaround`/distress.** Posture is not a floor;
  it is context about the firm's *situation* that should legitimately **loosen the new standard's
  bars** *(general knowledge: a genuine turnaround should be judged on rate-of-improvement, not
  held to a healthy-firm convergence deadline)*. Feed it in via the already-computed
  `explicit_distress_context` ([post_intake_mapping.py:2812-2815](../../python/client_intake_and_finmo/post_intake_mapping.py#L2812-L2815)):
  - **Gate A** (EBITDA breakeven by business-Q10): extend the deadline / widen the grace window
    when distress posture is set.
  - **Convergence bar** (Tier 1): accept a lower target percentile (or slope-only credit) under a
    turnaround posture.
- **Net:** keep `planning_mode` as a **posture input to the new standard**, retire its
  `profitability_floor_q*` role. Crucially, **stage and posture become two separate axes**: stage
  = lifecycle reality (derived from age, §3); posture = operating intent (`planning_mode`,
  esp. turnaround). The spec's `startup/mature/turnaround` list conflated them — turnaround is a
  posture, not a stage. This doc corrects that.
- **Migration caution:** because the realism floor and the ramp-contract floors both read this
  policy (§1.4), dropping the columns must be sequenced with the new gates going live, or the
  realism gate loses its profitability floor with nothing replacing it. (Carry as a build note,
  not a decision here.)

---

## 2. BUSINESS AGE from start_date — CONFIRMED computed today

**Yes — business age is already computed** (in **months**), not merely used to label quarters.
- `_whole_months_between(start_date, end_date)`
  ([quarter_grid.py:849-853](../../python/client_intake_and_finmo/quarter_grid.py#L849-L853)).
- Called in `_stage_governance_context` against `datetime.utcnow().date()` and stored as
  `business_age_months_at_run`
  ([quarter_grid.py:881](../../python/client_intake_and_finmo/quarter_grid.py#L881),
  [:891](../../python/client_intake_and_finmo/quarter_grid.py#L891),
  [:928](../../python/client_intake_and_finmo/quarter_grid.py#L928)).
- `start_date` resolution order: `facts.start_date` → `facts.business_start_date` →
  `ops.business_start_date` → `ops.start_date`
  ([quarter_grid.py:875-879](../../python/client_intake_and_finmo/quarter_grid.py#L875-L879)).
  `business_start_date` is required at intake and parsed by `parse_business_start_date`
  ([intake_submission.py:22-24](../../python/client_intake_and_finmo/intake_submission.py#L22-L24));
  finmo independently parses it via `_parse_start_date`
  ([finmo_model.py:23-32](../../python/financial_model_engine/finmo_model.py#L23-L32)) to build the
  projection quarter calendar.

**Quarters-elapsed** is not stored as a separate field, but is **trivially derivable** from the
existing months value: `age_quarters = business_age_months_at_run // 3` (or the analogous
date-diff in quarters). The raw material for Gate A's age-anchoring and §3's stage derivation is
already present.

---

## 3. STAGE DERIVATION from age (resolves the nullable field + taxonomy mismatch)

### 3.1 The taxonomy mismatch (why this needs resolving)
There are **four** overlapping stage taxonomies in the code today:

| Source | Labels | file:line |
|---|---|---|
| Profitability floors | startup / early / operational / **mature** (4) | [post_intake_mapping.py:4810-4821](../../python/client_intake_and_finmo/post_intake_mapping.py#L4810-L4821) |
| `_stage_family` | startup / early / operational (3 — **no mature**) | [quarter_grid.py:856-862](../../python/client_intake_and_finmo/quarter_grid.py#L856-L862) |
| Age fallback in `_stage_governance_context` | pre-revenue / early-stage / operating (3) | [quarter_grid.py:885-890](../../python/client_intake_and_finmo/quarter_grid.py#L885-L890) |
| Cohort resolver cap-category tokens | growth-scaling / mature-operational-established / early-startup | [cohort_band_resolver.py:225-238](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L225-L238) |

Two concrete defects fall out: (a) `_stage_family` **never returns "mature"**
([quarter_grid.py:862](../../python/client_intake_and_finmo/quarter_grid.py#L862) defaults to
`operational`), so the floor table's `_mature` columns are unreachable through that path; and
(b) the current age fallback collapses everything older than **365 days** to `operating`
([quarter_grid.py:887-890](../../python/client_intake_and_finmo/quarter_grid.py#L887-L890)), so it
cannot distinguish a 2-year firm from a 20-year firm.

Also note the current logic **prefers the nullable explicit `business_stage` first**
([quarter_grid.py:882-884](../../python/client_intake_and_finmo/quarter_grid.py#L882-L884)) and only
falls back to age — the exact dependency Nick's decision removes.

### 3.2 Decision (locked) and proposed mapping
**Derive stage from business age (always present, §2); do NOT depend on the nullable intake
`business_stage`. Use the 4-stage floors taxonomy startup / early / operational / mature**
(turnaround is a posture, not a stage — §1.5).

**Proposed age → stage thresholds** *(general knowledge: SMB lifecycle — year-1 survival, the
1–3yr "young firm" risk window per Census BDS, 3–7yr established, 7yr+ steady-state)*:

| Stage | Business age | Quarters elapsed | Rationale |
|---|---|---|---|
| **startup** | < 12 months | age_q < 4 | first operating year; pre-/early-revenue |
| **early** | 12 – < 36 months | 4 ≤ age_q < 12 | growth / young-firm risk window |
| **operational** | 36 – < 84 months | 12 ≤ age_q < 28 | established, past the survival cliff |
| **mature** | ≥ 84 months | age_q ≥ 28 | steady-state |

`age_q = business_age_months_at_run // 3` ([quarter_grid.py:928](../../python/client_intake_and_finmo/quarter_grid.py#L928)).
A future-dated `start_date` (start > today) maps to **startup** (pre-revenue), preserving the
existing pre-revenue handling ([quarter_grid.py:885-886](../../python/client_intake_and_finmo/quarter_grid.py#L885-L886)).

### 3.3 Consistency check across the three consumers
The proposed mapping is designed to make all consumers agree:
- **Floors** ([post_intake_mapping.py:4810-4821](../../python/client_intake_and_finmo/post_intake_mapping.py#L4810-L4821)):
  already have all four labels — the mapping makes **`mature` reachable** for the first time.
- **`_stage_family`** ([quarter_grid.py:856-862](../../python/client_intake_and_finmo/quarter_grid.py#L856-L862)):
  must be extended to **emit `mature`** (today caps at `operational`) so the derived stage flows
  through unchanged. (Build note, not done here.)
- **Cohort resolver** ([cohort_band_resolver.py:225-238](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L225-L238)):
  map startup/early → its early/startup cap-category set; operational/mature → its
  mature/operational/established set. The four derived labels all have a home in the existing
  token groups.
- **New viability standard** ([spec §4](fix_1_viability_standard_spec.md)): consumes the same four
  labels for Tier-1 stage weighting; Gate A's deadline of **business-quarter-10 (~30 months)**
  lands inside the **early** band — consistent with "a firm should reach EBITDA breakeven by the
  end of its early stage."

### 3.4 What changes (scope, not code)
1. Replace the explicit-stage-first logic ([quarter_grid.py:882-890](../../python/client_intake_and_finmo/quarter_grid.py#L882-L890))
   with the age-derived 4-band mapping (§3.2), dropping the nullable `business_stage` dependency.
2. Extend `_stage_family` to return `mature` ([quarter_grid.py:856-862](../../python/client_intake_and_finmo/quarter_grid.py#L856-L862)).
3. Confirm the cohort resolver token map covers all four derived labels
   ([cohort_band_resolver.py:225-238](../../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L225-L238)).

---

## 4. SUMMARY

- **`planning_mode`** is a deterministic-Python-selected (not GPT/user) profitability-FLOOR
  system with 5 table modes but only 3 live (`turnaround`/`normalize`/`rebalance`;
  `growth_investment`/`preservation` are dead). Its consumers are the realism profitability floor,
  the stage-ramp policy/contract floors, prompt selection, and GPT context.
- **Recommendation:** the new standard **supersedes the floor function**; **keep the posture
  dimension** (especially `turnaround`/`explicit_distress_context`) and feed it into the new
  standard to loosen **Gate A** and the **convergence bar** for genuine turnarounds. Stage
  (lifecycle) and posture (`planning_mode`) become two separate axes.
- **Business age is already computed** (months, `business_age_months_at_run`,
  [quarter_grid.py:891,928](../../python/client_intake_and_finmo/quarter_grid.py#L891)); quarters
  are a trivial `// 3`.
- **Stage derivation:** derive from age in the 4-stage floors taxonomy
  (startup < 12mo / early 12–36mo / operational 36–84mo / mature ≥ 84mo), drop the nullable
  `business_stage`, and reconcile `_stage_family` (add `mature`) + the cohort resolver token map so
  the floors, the resolver, and the new standard all speak one taxonomy.
