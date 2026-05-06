# Post-Intake Master Diagnostic (2026-05-05)

**Scope:** Read-only diagnostic dive of the post-intake pipeline. Maps what the runtime actually does today vs. what the Golden Rule architecture says it should do, then ranks the stitch/brittleness/realism problems and prescribes specific table-backed fixes.

**Sources used:**
- [context/Golden Rule to Live By.md](Golden Rule to Live By.md)
- [context/post_intake_golden_baseline_f949316.md](post_intake_golden_baseline_f949316.md)
- [context/system_overview_update_4.25.26.md](system_overview_update_4.25.26.md), §"Industry Baseline Lookup System"
- Live code under `python/api_handlers/intake_consult.py` and `python/client_intake_and_finmo/post_intake_*` plus `quarter_grid.py`, `finmo_bridge.py`, `numeric_solver.py`
- SQL DDLs in [post_intake_mapping.py](../python/client_intake_and_finmo/post_intake_mapping.py) for `post_intake_process_sequence_lookup`, `post_intake_process_context_lookup`, `post_intake_gpt_contract_lookup`, `post_intake_cash_policy_lookup`

**Key context:** Two clean E2Es passed on 2026-05-05 (NexGen Software, ValueMart Superstores). The structural skeleton is mostly in place. The audit below targets *realism, determinism, and elimination of stitching* — not foundation work.

---

## Part 1. What the Pipeline Actually Does Today

### 1.1 Top-level flow (orchestration)

`POST /api/post_intake_consult_system_run` → `post_intake_consult_system_run_handler` ([intake_consult.py:6886](../python/api_handlers/intake_consult.py#L6886)) → `_run_planning_system_for_draft_unified` ([intake_consult.py:6708](../python/api_handlers/intake_consult.py#L6708)) splits work into two halves:

**Pre-grid initialization** — `prepare_initial_grid_for_draft` ([post_intake_initial_grid/runner.py:30](../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L30))
1. `post_intake_initialize_validation` (sequence step) — runtime table integrity, contract/context schema validity, payroll contract shape, balance-sheet driver sample.
2. `compute_marketing_model_json` (Census/CBP-derived).
3. `estimate_maintenance_capex_percent_with_gpt` — GPT call #1.
4. `estimate_r_and_d_applicability_with_gpt` — GPT call #2.
5. `estimate_balance_sheet_contextual_seed_with_gpt` — GPT call #3.
6. `estimate_stage_ramp_contract_with_gpt` — GPT call #4.
7. `estimate_payroll_headcount_schedule_with_gpt` + apply — GPT call #5.
8. `determine_planning_mode` + `generate_live_quarter_grid_plan` (`call_quarter_grid_openai`) + `apply_live_quarter_grid_plan` — GPT call #6.

**Post-grid system run** — `_run_unified_post_grid_system_run`
9. Unified convergence loop (GPT call #7 per cycle, plus verification GPT #8 per cycle), bounded by `max_attempts`/`timeout_seconds` from `post_intake_process_sequence_lookup` for step `unified_convergence_decision`.
10. Cash pass — deterministic phase sequence from `cash_phase_sequence_json` in `post_intake_cash_policy_lookup`, with `cash_strategy_review` GPT call (#9) and an optional second-pass GPT call.
11. `post_intake_finalize_validation` — runtime table integrity, mapping-formula reconciliation, horizon Q1-Q20, revenue=Capacity×Price×Util, payroll/headcount, debt schedule, balance-sheet drivers, cash-phase trace.
12. Excel workbook export.

The sequence controller (`PostIntakeSequenceController`, [post_intake_sequence.py:196](../python/client_intake_and_finmo/post_intake_sequence.py#L196)) wraps each step: it loads `step_context` from `post_intake_process_sequence_lookup` + `post_intake_process_context_lookup`, pushes an active-context contextvar, and asserts no downstream step mutates a `final_for_stage` output.

### 1.2 Where structural authority lives today

| Concern | Authority | Status |
|---|---|---|
| Process order, parent/child, required context, produced outputs, recompute triggers | `post_intake_process_sequence_lookup` | ✓ table-backed (69 active rows) |
| Required runtime context per step | `post_intake_process_context_lookup` (335 rows) | ✓ table-backed |
| GPT field schema, min/max, enum, normalization, horizon | `post_intake_gpt_contract_lookup` (157 rows) | ✓ table-backed at the field level |
| GPT context payload allowed keys + char budget | `post_intake_gpt_context_lookup` (98 rows) | ✓ table-backed |
| Driver formulas, applicability, presence rule, validation formula | `post_intak_mapping_lookup` (26 rows) | ✓ table-backed |
| Cash strategy bounds, debt schedule policy, cash phase order | `post_intake_cash_policy_lookup` (9 rows) | ✓ table-backed |
| Payroll OEWS title universe, sanity bounds, wage positioning, trend rules | `post_intake_headcount_policy_lookup` (1 row) | ✓ table-backed |
| Industry-typical realism bands (49 metrics, 47,700 rows) | `post_intake_industry_baseline_lookup` | ✗ table loaded, **0 callers in runtime code** |
| Stage-classification ramp policy (Q1-Q4 revenue ceilings, profitability postures, validator rules) | `stage_planning_ramp_policy()` Python function in [post_intake_mapping.py:2813](../python/client_intake_and_finmo/post_intake_mapping.py#L2813) | ◐ deterministic but hardcoded; *not NAICS-aware* |
| Convergence non-productive cycle limit | Module constant `_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT = 3` ([post_intake_convergence/runner.py:46](../python/client_intake_and_finmo/post_intake_convergence/runner.py#L46)) | ✗ hardcoded |
| Convergence per-cycle wall (180s) | Read from sequence row `timeout_seconds` for `unified_convergence_decision` | ✓ table-backed |
| **Total convergence wall budget** | None | ✗ does not exist |
| Cash-strategy preferred debt/equity ratios | `_CASH_STRATEGY_PREFERRED_DEBT_RATIO = 0.40`, `_CASH_STRATEGY_PREFERRED_EQUITY_RATIO = 0.60` constants in `post_intake_cash/runner.py` | ✗ hardcoded |
| Maintenance-capex GPT bound | "must be at least 2 and no more than 15" hardcoded in `post_intake_contracts/runner.py:1100` | ✗ hardcoded; not in `min_value`/`max_value` columns |

### 1.3 Where GPT calls happen and what they actually decide

| # | Call site | Decision | Contract row | Context row | Numeric guardrails |
|---|---|---|---|---|---|
| 1 | `_estimate_maintenance_capex_percent_with_gpt` ([post_intake_contracts/runner.py:1051](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1051)) | Single percent (PPE-replacement intensity) | `maintenance_capex_percent` | yes | bound 2–15 *hardcoded* |
| 2 | `_estimate_r_and_d_applicability_with_gpt` ([post_intake_contracts/runner.py:1397](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1397)) | Boolean + reasoning | `r_and_d_applicability` | yes | none beyond schema |
| 3 | `_estimate_balance_sheet_contextual_seed_with_gpt` ([post_intake_contracts/runner.py:1550](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1550)) | AR, AP, prepaid, deferred revenue, inventory, debt seed values | `balance_sheet_contextual_seed` | yes | mapping-table `minimum_live_value`/`maximum_live_value` only; **no NAICS days/% bands** |
| 4 | `_estimate_stage_ramp_contract_with_gpt` ([post_intake_contracts/runner.py:1698](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1698)) | Q1-Q20 quarter ramp grid: revenue qoq min/max, FTE qoq max, utilization watermark, COGS%, marketing%, R&D%, G&A%, profitability posture | `stage_ramp_contract` | yes (`stage_planning_ramp_policy()` injected) | Python `stage_planning_ramp_policy` produces stage-family rules; **not NAICS-conditioned** |
| 5 | `estimate_payroll_headcount_schedule_with_gpt` ([post_intake_headcount/schedule.py:1959](../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1959)) | OEWS-title mix, FTE Q1-Q20 ramp, capacity_units_per_supporting_fte, wage positioning tier, target payroll/revenue (sanity only) | `payroll_headcount_schedule` | yes | `post_intake_headcount_policy_lookup` payroll/rev bounds by labor_intensity_class (low 6–45%, …); **NOT NAICS-keyed** |
| 6 | `call_quarter_grid_openai` ([quarter_grid.py:2030](../python/client_intake_and_finmo/quarter_grid.py#L2030)) | Q1-Q20 lever edits batched | quarter-grid contract | yes | `attach_quarter_grid_cell_envelopes()` from stage ramp contract; bounds passed to GPT but Python does not clip |
| 7 | unified convergence GPT ([post_intake_convergence/runtime.py:3070](../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L3070)) | `lever_adjustments` + `mapped_repair_targets` per cycle | `unified_convergence_decision` | yes (filtered) | sequence row `timeout_seconds` per cycle; `max_attempts` per run |
| 8 | unified convergence verification GPT (same module) | Closure scoring | `unified_convergence_verification` | yes | same |
| 9 | `_run_cash_strategy_review_openai` ([post_intake_cash/runner.py:1945](../python/client_intake_and_finmo/post_intake_cash/runner.py#L1945)) | Funding plan, distributions, debt issuance/paydown timing | `cash_strategy_review` | yes | hardcoded debt/equity ratio constants; cash policy floor/ceiling table-backed |

**Important:** Calls 1–6 (initial grid) sit *outside* the convergence loop and feed it inputs. Calls 7–9 (post-grid) sit *inside* the loop or after it.

### 1.4 The four FINMO-input "silent zero" sites Agent 4 confirmed

These are the realism-killing fallbacks in seed code that should be replaced with NAICS-cascade lookups now that `post_intake_industry_baseline_lookup` exists:

- `cogs_percent_of_revenue` → `0.0` at [finmo_bridge.py:341](../python/client_intake_and_finmo/finmo_bridge.py#L341) and [quarter_grid.py:107-121](../python/client_intake_and_finmo/quarter_grid.py#L107-L121)
- `marketing_percent_of_revenue` → `0.0` at [finmo_bridge.py:946-948](../python/client_intake_and_finmo/finmo_bridge.py#L946-L948), 3364–3368, 3410, 3447
- `taxes_percent` → `0.0` at [finmo_bridge.py:3461](../python/client_intake_and_finmo/finmo_bridge.py#L3461) and 970
- `ar_balance`, `ap_balance`, `inventory_balance` → `0.0` at [finmo_bridge.py:3470-3472](../python/client_intake_and_finmo/finmo_bridge.py#L3470-L3472), 3586–3597, 1808–1810

These cascade outward: zero COGS → 100% gross margin; zero AR/AP → no working-capital lag; zero taxes → overstated net income. The 2026-05-05 audit observed a $10M retail superstore emitting $0 taxes and payroll under 10% of revenue exactly because of these patterns.

---

## Part 2. What the Pipeline Should Do per Golden Rule + Industry Baseline System

The Golden Rule (file: [context/Golden Rule to Live By.md](Golden Rule to Live By.md)) is unambiguous about ownership:

- **Python** owns deterministic structure through lookup tables and table-backed functions. Python does not invent values, does not complete GPT decisions, does not silently repair, does not patch outputs.
- **GPT** owns business judgment *inside table-defined contracts, schemas, contexts, and bounds*. GPT does not define structure or invent fields.
- **FINMO** calculates from `model_input_json` only and does not receive patched outputs.

For the new Industry Baseline Lookup System (system overview §"Industry Baseline Lookup System"), the design intent is:

> They are consulted only when intake omits a value (silent `or 0.0` fallback sites). Explicit intake values still win.
> They provide min/max bands for GPT to pick within, not specific values that override GPT decisions.
> They feed finalize-stage realism gates (planned, not yet wired) that flag outputs outside NAICS-typical bands.

So the ideal end state has three new structural layers wired in:

**A. Producer-side substitution.** Every `or 0.0` site that today emits a silent zero must instead call `post_intake_industry_baseline_for_naics(metric_key, naics_6)` and seed the NAICS-cascaded benchmark when intake omits the value. Provenance fields (`naics_level_used`, `confidence_tier`, `data_source`) ride along.

**B. Bounds-tightening for GPT.** Every GPT call where the decision is a ratio/percent that has a NAICS metric (COGS%, marketing%, R&D%, SG&A%, rent%, payroll/rev, revenue/FTE, deferred-revenue%, prepaid%, capex%, effective tax rate, distributions%, AR-days, AP-days, inventory-days, ebitda margin) must receive a NAICS-keyed `[min, target, max]` band as guardrail context, and the GPT contract row must carry `min_value`/`max_value` derived from the same band.

**C. Finalize realism gate.** The finalize validator must, *after* the run produces the final `finmo_json`, recompute the same set of ratios from FINMO output and assert each one falls inside the NAICS band (with `confidence_tier`-aware tolerance). A deviation outside the band fails the run and surfaces the upstream input that's wrong — not a quiet warning.

The Golden Rule explicitly forbids using these tables to *replace* GPT — they augment by narrowing the lane GPT can choose within and by failing fast at finalize when the produced model violates the band.

A fourth structural change is needed for orchestration determinism:

**D. The sequence/context tables must carry the metadata that tightens the orchestration without stitching.** Right now several steps stitch behavior in Python because the sequence row is missing the column that would let the controller drive it. Specifically: stage-classification gating, planning-mode gating, NAICS-realism metric attachment per step, total-phase budget, and non-productive cycle limit are all controller-relevant but live as constants or as inline `if/elif` chains inside phase runners.

---

## Part 3. Top Stitch / Brittleness / Inconsistency Problems (Ranked)

Ranking criteria: **realism impact** (does fixing this make plans look real for any business type?) × **regression risk** (can this be wired without breaking the passing E2E?). Highest realism × lowest regression risk first.

### P1. Industry baseline lookup is loaded but unread (CRITICAL realism)
Forty-seven thousand seven hundred NAICS-keyed benchmark rows for 49 metrics exist in `post_intake_industry_baseline_lookup` and not a single runtime call site reads them. The user's audit noted this directly: "every cost/balance-sheet line in the app silently fell through to `0.0`." Until the resolver `post_intake_industry_baseline_for_naics(naics_6, metric_key)` exists and the four silent-zero sites are wired to it, every business type that doesn't volunteer COGS/AR/AP/marketing/taxes via intake produces an unrealistic plan. This is the single biggest realism win available, and because it only fires when intake omitted a value (explicit intake still wins), the regression risk on the passing E2E is essentially zero — those E2Es supplied complete intakes.

### P2. Finalize realism gate does not exist
The finalize validator ([post_intake_runtime_validation/finalize_post_intake.py:397-642](../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L397-L642)) checks horizon completeness, formula reconciliation, payroll, debt, balance-sheet drivers, and cash-phase trace — but it has zero industry-typical-band assertions. A run can finish with `cogs_percent = 0.95` or `current_ratio = 0.1` or `effective_tax_rate = 0` and `all_cleared = true` will still print. This is the gate that catches "fake-looking models before they ship," and it has to land *with* the resolver from P1.

### P3. Stage ramp contract is hardcoded to fixed Q1/Q2/Q3/Q4 ratios, not NAICS-aware
`stage_planning_ramp_policy()` ([post_intake_mapping.py:2813](../python/client_intake_and_finmo/post_intake_mapping.py#L2813)) hardcodes `early_revenue_share_ceiling_of_late_run_rate = {Q1: 0.25, Q2: 0.40, Q3: 0.60, Q4: 0.80}` for startup stage and similar fixed ratios for early/operational. A SaaS startup, a restaurant startup, and a physical-retail startup all get the same ramp ceilings. The new baseline table has `startup_qoq_growth_typical`, `early_qoq_growth_typical`, `mature_qoq_growth_typical` populated at NAICS-4 from BDS — these should override the fixed Python fractions for the GPT prompt context and for the post-cycle revenue-QoQ enforcement at [post_intake_convergence/runner.py:202-240](../python/client_intake_and_finmo/post_intake_convergence/runner.py#L202-L240).

### P4. Stage-ramp enforcement is asymmetric: only revenue_qoq_max is real; FTE/utilization/spike-count are prompt-only window-dressing
`_apply_stage_ramp_revenue_driver_limits` ([post_intake_convergence/runner.py:132](../python/client_intake_and_finmo/post_intake_convergence/runner.py#L132)) is a real Python validator that adjusts capacity/price/utilization to clip revenue under the ramp QoQ ceiling. But `fte_qoq_max`, `utilization_high_watermark`, `max_spike_count` are written into the contract, sent to GPT in the prompt, and then never enforced by Python. So GPT can return a ramp that violates them and as long as revenue QoQ stays under `revenue_qoq_max`, the cycle accepts it. This is exactly the kind of "window-dressing label passed into prompts" the user asked about. The audit confirmed there's no Python validator for these on the solver-output side.

### P5. Convergence has per-cycle 180s wall but no total-phase budget and no oscillation hash
The user explicitly mentioned the 4-minute cycle-budget concern. Today the loop reads `timeout_seconds = 180` from the `unified_convergence_decision` sequence row and enforces it per cycle. But there is no total convergence wall — `_UNIFIED_CONVERGENCE_MAX_CYCLES` × 180s gives the upper bound only by multiplication. With `max_attempts = 8`, that's 24 minutes of wall time before the run fails. The non-productive bailout (`_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT = 3`) protects against pure non-progress but does not protect against slow-progress that runs the meter. There is also no two-cycle state-hash comparison; the existing `repeated_same_pattern` flag depends on validation-error pattern equality, which can vary between cycles even when GPT returns nearly-identical lever adjustments.

### P6. Solver "anchor escape hatch" causes live-vs-local divergence
The system-overview May 2 notes describe a recurring bug: "live E2E persisted results still sometimes show the solver returning the GPT anchor/no-op value" while local reproduction returns the correct algebraic estimate. Agent 2 traced this to [numeric_solver.py:893-911](../python/client_intake_and_finmo/numeric_solver.py#L893-L911) — the solver evaluates the GPT-provided anchor first, and if it happens to satisfy tolerance, returns it without running the direct-estimate path. A direct-fit lever (one lever, one target metric, one targeted quarter) should *always* go through the deterministic algebraic path; falling back to the GPT anchor when the anchor is "good enough" is non-deterministic across runs because the anchor depends on GPT temperature.

### P7. Balance-sheet contextual seed has no NAICS bounds
The seed GPT call gets `minimum_live_value`/`maximum_live_value` from `post_intak_mapping_lookup` per row (e.g., AR, AP, inventory, prepaid, deferred revenue) but those mapping bounds are universal, not NAICS-conditioned. The new `prepaid_expenses_percent_of_revenue`, `deferred_revenue_percent_of_revenue`, AR-days, AP-days, inventory-days metrics are exactly the bounds GPT should have. Software with 12-34% deferred revenue is materially different from retail with ~0.6% prepaids; today GPT picks both freely from the same wide band.

### P8. Payroll/revenue and revenue/FTE bounds are universal, not NAICS-conditioned
`post_intake_headcount_policy_lookup` provides `payroll_revenue_sanity_bounds_by_labor_intensity_class` (low 6–45%, medium 10–55%, high 16–70%, expert 18–80%). These bands are wide enough to admit nearly anything. The new `payroll_percent_of_revenue` and `revenue_per_fte` NAICS metrics tighten the band by industry. Crucially, today this band is "reasonableness context only — Python must not clip payroll." The Golden Rule is right that payroll should not be clipped to fit revenue — but the *target band itself* should be NAICS-tightened so GPT gets a narrower "reasonable" target, and the finalize gate should fail when the derived payroll/revenue ratio is outside the NAICS band by more than the confidence tier allows.

### P9. Maintenance-capex bound (2–15%) is hardcoded prose in the prompt
[post_intake_contracts/runner.py:1100](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1100) tells GPT "must be at least 2 and no more than 15." The bound exists to prevent hallucinations, but capital-light services and capital-heavy manufacturing don't have the same band. The `maintenance_capex_percent_of_revenue` metric in the baseline table (676 rows, derived depreciation proxy) supplies a NAICS-keyed band. The hardcoded text bound should come from the GPT contract row's `min_value`/`max_value` columns, populated from the NAICS cascade.

### P10. Cash-strategy preferred ratio constants leak through Python
`_CASH_STRATEGY_PREFERRED_DEBT_RATIO = 0.40` and `_CASH_STRATEGY_PREFERRED_EQUITY_RATIO = 0.60` are module-level constants in `post_intake_cash/runner.py`. They should be cash-policy-table columns. They affect the cash-strategy review GPT prompt and the funding plan normalization that mutates GPT's decision after the fact.

### P11. Convergence retry "decision reconstruction" can mutate GPT output
Agent 1 flagged this as a potential Golden Rule violation: at [post_intake_convergence/runtime.py:3380-3451](../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L3380-L3451), on retry the runtime builds a *new* payload with narrowed `allowed_lever_ids` and modified `scoped_baseline_map` and re-asks GPT. That's healthy if the previous response was fully discarded; the concern is whether anything from the rejected response carries forward implicitly. Needs verification with a focused trace check.

### P12. Cash strategy review second-pass effectively re-runs cash decisioning
[post_intake_cash/runner.py:2370-2480](../python/client_intake_and_finmo/post_intake_cash/runner.py#L2370-L2480) runs `_build_cash_strategy_second_pass_plan()` if the primary decision fails normalization. Two GPT cash-decision calls in a row blur "GPT decides" with "Python iterates GPT until it gets the answer it wants." Should be either one shot with strict fail-fast, or a properly declared sub-step in the sequence with its own contract.

### P13. Hardcoded `_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT = 3` should be table-backed
A column on `post_intake_process_sequence_lookup` for the convergence step would let operators tune this without code change. Same for `_CYCLE_DEADLINE_GUARD_SECONDS = 8.0`, `_PLANNER_GPT_MAX_SECONDS = 150.0`, `_VERIFICATION_GPT_MAX_SECONDS = 45.0`.

### P14. Planning_mode is prompt-only
`planning_mode` ("rebalance", "turnaround", "normalize") flows into GPT prompts and into stage-ramp policy text but does not numerically constrain the convergence solver envelope. The user asked specifically about this. The right answer is probably: planning_mode *should* select different policy rows from a `post_intake_planning_mode_policy_lookup` (new table) that constrains profitability floor, allowed-loss latest quarter, and which issue codes are ramp-tolerant.

### P15. Stage_classification is partial
It does drive `stage_planning_ramp_policy()` (Q1-Q4 ceilings, profitability postures, validator rules at [post_intake_mapping.py:2842-2901](../python/client_intake_and_finmo/post_intake_mapping.py#L2842-L2901)). Those validator rules — `q10_min_net_income_margin_floor`, `q11_to_q20_min_net_income_margin_floor`, `loss_allowed_latest_quarter`, `operational_requires_positive_from_q5` — *are* enforced numerically. So stage_classification is not pure window-dressing; it just isn't NAICS-aware. The ramp ceiling fractions (0.25/0.40/0.60/0.80) are the part that is universal-business not industry-business.

---

## Part 4. Specific Fix per Problem

For each problem, the fix is one of:
- **(B)** Tighten table-backed bounds (add columns, populate rows)
- **(N)** NAICS-baseline-lookup substitution for a hardcoded constant or silent-zero fallback
- **(G)** Finalize-stage realism gate
- **(S)** New sequence/context-table column or new policy row to remove stitching

### P1 fix (N)
Write `post_intake_industry_baseline_for_naics(metric_key, naics_6)` resolver in a new module `python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py`. Implement the documented cascade: 6→5→4→3→2→0 (`generic_default`)→`no_coverage`. Return `{benchmark_min, benchmark_target, benchmark_max, naics_level_used, data_source, sample_size, confidence_tier, trust_flag, fallback_chain_attempted}`. Then replace the four silent-zero sites:

- [finmo_bridge.py:341](../python/client_intake_and_finmo/finmo_bridge.py#L341): if `_safe_ratio()` returned `None`, look up `cogs_percent_of_revenue` for the NAICS, use `benchmark_target` as seed; carry provenance into seed metadata.
- [finmo_bridge.py:946-948, 3364-3368](../python/client_intake_and_finmo/finmo_bridge.py#L946-L948): same for `marketing_percent_of_revenue`.
- [finmo_bridge.py:970, 3461](../python/client_intake_and_finmo/finmo_bridge.py#L970): same for `effective_tax_rate`.
- [finmo_bridge.py:3470-3472](../python/client_intake_and_finmo/finmo_bridge.py#L3470-L3472): same for AR/AP/inventory using `ar_days_dso`, `ap_days_dpo`, `inventory_days` and the revenue/expense base — implementation: `ar_balance_seed = revenue_quarter * (ar_days_dso/90)` when intake AR is missing.
- [quarter_grid.py:107-121](../python/client_intake_and_finmo/quarter_grid.py#L107-L121): same for `cogs_percent_of_revenue`.

Each seed must carry `seed_source = "naics_cascade"`, `naics_level_used`, `confidence_tier` so the workbook and finalize gate see provenance.

### P2 fix (G)
Add `validate_industry_realism_bands` to [finalize_post_intake.py](../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py). Walk a new SQL table `post_intake_finalize_realism_check_lookup` that maps each FINMO-derivable metric key to:
- `metric_key` (e.g., `cogs_percent_of_revenue`)
- `derivation_formula_key` (e.g., `cogs_dollars / revenue_dollars` from FINMO live quarters)
- `tolerance_bps_high_confidence` (e.g., +/- 1500 bps for `high`)
- `tolerance_bps_medium_confidence` (e.g., +/- 2500 bps for `medium`)
- `tolerance_bps_generic_default` (typically `null` = skip the check rather than gate on a generic band)
- `gate_kind` (`hard_fail`, `warn`, `skip_if_no_coverage`)
- `applicability_rule_key` (e.g., `inventory_days` only checked when business has inventory)

Per-quarter (or quarter-aggregate) compute the actual ratio, look up the NAICS band, downgrade tolerance per `confidence_tier`, fail-fast with the failing metric, the produced value, the band, the source, and the upstream input that drove the deviation. The finalize gate should not invent; it must surface what produced the bad ratio and let the operator decide.

### P3 fix (N)
Replace the hardcoded `early_revenue_share_ceiling_of_late_run_rate` in `stage_planning_ramp_policy()` with a NAICS-conditioned reading. The function gets `business_naics` (already resolved upstream) and looks up `startup_qoq_growth_typical` (BDS-derived, populated at NAICS-4) for stage="startup", and similarly for early/mature. The Q1-Q4 fractions become a function of the typical QoQ rate:

```
ceiling[Q1] = (1 + qoq_typical_min)
ceiling[Q2] = ceiling[Q1] * (1 + qoq_typical_min)
…
```

Conservative when no NAICS coverage: keep the current 0.25/0.40/0.60/0.80 as the level-0 generic default in a new table `post_intake_stage_ramp_default_lookup` so the fallback is explicit.

### P4 fix (B)
The hard-validator at [post_intake_convergence/runner.py:132-263](../python/client_intake_and_finmo/post_intake_convergence/runner.py#L132-L263) currently only adjusts revenue lever combination to clip revenue QoQ. Add three sister validators: `_apply_stage_ramp_fte_qoq_max`, `_apply_stage_ramp_utilization_high_watermark`, `_apply_stage_ramp_max_spike_count` that act on `expenses::Payroll`-supported FTE and `revenue::Utilization` levers respectively. Symmetric with the revenue path. Or — equivalent design — fail-fast in convergence verification when the produced model violates these constraints, with the failing constraint, quarter, and lever named explicitly.

### P5 fix (S)
Add columns to `post_intake_process_sequence_lookup`:
- `total_phase_budget_seconds DECIMAL(10,2)` — total wall budget for phases that loop (convergence). Read by the controller; loop fail-fasts when total elapsed > budget regardless of cycle count.
- `non_productive_cycle_limit INT` — replaces the hardcoded 3.
- `cycle_deadline_guard_seconds DECIMAL(10,2)`, `planner_gpt_max_seconds`, `verification_gpt_max_seconds` — replace the four module constants in convergence runner.

Also add an oscillation-detection pass before the existing non-productive-cycle bailout: take the SHA256 of `(active_lever_ids_sorted, target_metric_names_sorted, scoped_baseline_signature)` per cycle. Two consecutive cycles with the same hash and no improvement = fail-fast `convergence_oscillation_detected`. State hash is data-driven; pattern hash today is error-driven.

### P6 fix (B)
Make the direct-estimate path mandatory when there is exactly one allowed lever and one target metric and one targeted quarter, *before* evaluating the GPT anchor. The anchor evaluation should be a tiebreaker only when the algebraic path failed (e.g., probe out of bounds). In code: at [numeric_solver.py:893](../python/client_intake_and_finmo/numeric_solver.py#L893), reorder so the single-variable linear interpolation runs first, then the anchor test. This is what local reproduction showed actually closing the COGS direct target. The runtime probes (`numeric_solver_direct_estimate_code_probe`) confirmed the new code is loaded; the divergence is execution-order, not file-staleness.

### P7 fix (B + N)
Extend the GPT contract for `balance_sheet_contextual_seed` so each row carries `naics_baseline_metric_key` and the field's `min_value`/`max_value` are dynamically populated at prompt-build time from the NAICS cascade (preserving the existing mapping-table absolute bounds as the outer envelope). For example, when seeding `deferred_revenue_balance`, the contract field's `min_value` becomes `revenue_quarter * deferred_revenue_percent_of_revenue.benchmark_min` (NAICS-cascaded) and `max_value` becomes `revenue_quarter * deferred_revenue_percent_of_revenue.benchmark_max`. The mapping table's universal bounds become the outer absolute envelope; the NAICS band becomes the inner narrowing envelope GPT must respect.

### P8 fix (B + G)
Add a `naics_baseline_metric_key` column to `post_intake_headcount_policy_lookup` so the policy row points at `payroll_percent_of_revenue` (and `revenue_per_fte` as secondary). Build the GPT prompt's `target_payroll_percent_of_revenue` reasonableness target from the NAICS cascade. Keep the labor_intensity_class table-backed range as the outer envelope. **Crucially keep the Golden Rule that payroll is not clipped to fit revenue.** Then add a finalize-gate check (P2) that the produced payroll/revenue lands within the NAICS band by `confidence_tier` tolerance — failing the run when GPT picked an industry-implausible mix even though the labor_intensity_class envelope admitted it.

### P9 fix (B)
Move the "2 to 15" maintenance-capex bound out of prompt prose into the contract row's `min_value`/`max_value` columns. The prompt then renders the bound from the contract (already supported by `post_intake_build_prompt_from_contract`). Then make the bound NAICS-conditioned: the row's `min_value`/`max_value` become *NAICS cascade output*, populated at prompt-build time. Generic default falls through to the current 2–15.

### P10 fix (S)
Add columns to `post_intake_cash_policy_lookup`:
- `preferred_debt_to_assets_ratio DECIMAL(10,4)` (replaces `_CASH_STRATEGY_PREFERRED_DEBT_RATIO`)
- `preferred_equity_to_assets_ratio DECIMAL(10,4)` (replaces `_CASH_STRATEGY_PREFERRED_EQUITY_RATIO`)
- Optionally also `preferred_distribution_yield_target`, `preferred_min_cash_runway_months_at_growth_pace`

Set them per `cash_strategy` × `debt_position` cell so balanced/preserve_cash/shareholder_return diverge.

### P11 fix (verification + S)
Trace each retry flow through `_apply_followup_exact_updates` and the model_input_repair_cell normalizer at [runtime.py:3306](../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L3306) to confirm rejected GPT responses do not seed the next prompt's defaults. If they do, sever that and add a sequence-table boolean `discard_rejected_response_completely TINYINT` on the `unified_convergence_decision` row.

### P12 fix (S)
Make the cash-strategy second pass either (a) one explicit sub-step in `post_intake_process_sequence_lookup` with its own contract `cash_strategy_review_second_pass`, or (b) deleted in favor of a single-shot fail-fast. Option (a) is cleaner — it gives the controller authority over whether the second pass runs and lets each pass have its own context filter and contract.

### P13 fix (S)
Already covered by P5 — `non_productive_cycle_limit`, `cycle_deadline_guard_seconds`, `planner_gpt_max_seconds`, `verification_gpt_max_seconds` move to sequence row columns.

### P14 fix (S)
Create `post_intake_planning_mode_policy_lookup` with rows keyed by `planning_mode` (rebalance, turnaround, normalize) and columns:
- `profitability_floor_q1_q4` / `q5_q10` / `q11_q20`
- `loss_allowed_latest_quarter`
- `tolerated_issue_codes_json` (issues that don't block convergence in this mode)
- `cycle_budget_multiplier` (turnaround can use 2× normal budget; rebalance uses 1×)

Then `stage_planning_ramp_policy()` reads this table instead of branching on `planning_mode == "turnaround"`.

### P15 fix (N + B)
Already covered by P3 (NAICS-condition the Q1-Q4 ceilings). Keep the validator_rules portion as Python because they're invariant to industry (e.g., "operational requires non-negative net income from Q1" is universal).

---

## Part 5. Phased Implementation Plan

Phases are ordered by *realism impact landed first* with *regression risk minimized*. Each phase ends in a green E2E before the next phase starts.

### Phase 0 — Prep (no behavior change)
1. Add a `post_intake_industry_baseline/` package with `lookup.py` containing `post_intake_industry_baseline_for_naics(metric_key, naics_6)` resolver implementing the 6→5→4→3→2→0 cascade against `post_intake_industry_baseline_lookup`. Return the documented payload (`benchmark_min/target/max`, `naics_level_used`, `data_source`, `sample_size`, `confidence_tier`, `trust_flag`, `fallback_chain_attempted`).
2. Add unit tests for the resolver against the verified ValueMart NAICS 455211 cascade (`effective_tax_rate` resolves to NAICS-5 IRS_SOI; `cogs_percent_of_revenue` to NAICS-6 industry_metrics_raw; `payroll_percent_of_revenue` to L0 generic_default).
3. Add `post_intake_industry_metric_registry` lookup function that returns `governs_model_input_lever`, `primary_source`, `fail_if_no_coverage` for a metric_key.

**Exit criteria:** Resolver tests pass. No existing E2E touched.

### Phase 1 — Producer-side substitution at the four silent-zero sites
Replace the silent zeros in `finmo_bridge.py` and `quarter_grid.py` (P1 fix). Each site, when intake omits the value, calls the resolver and uses `benchmark_target` × revenue base as the seed. Carry provenance in `model_input_json` driver metadata under a new `seed_source` tag.

This is producer-side. It only fires when intake omitted the value, which is exactly the behavior the design contract permits ("explicit intake values still win"). Both 2026-05-05 E2Es (NexGen, ValueMart) had complete-enough intakes that the new path won't fire — both should pass unchanged.

**Exit criteria:** NexGen + ValueMart E2Es still pass. A new E2E with a deliberately sparse intake (e.g., AR/AP/marketing/taxes omitted) shows non-zero NAICS-cascaded seeds in the workbook with provenance.

### Phase 2 — Stage ramp NAICS-condition (P3, P15)
Wire `stage_planning_ramp_policy()` to read `startup_qoq_growth_typical` / `early_qoq_growth_typical` / `mature_qoq_growth_typical` from the resolver. Generic default falls through to current fixed fractions. The convergence revenue-QoQ enforcement at [runner.py:202-240](../python/client_intake_and_finmo/post_intake_convergence/runner.py#L202-L240) automatically picks up the new ceilings because it reads them from the contract.

**Exit criteria:** Existing E2Es pass with NAICS-tightened ramps (NexGen software stage_qoq differs from ValueMart retail). Workbook ramp section shows `naics_level_used` provenance.

### Phase 3 — GPT contract NAICS bound injection (P7, P8, P9)
At GPT prompt-build time, populate the contract field's `min_value`/`max_value` from the NAICS cascade for: `maintenance_capex_percent`, all `balance_sheet_contextual_seed` working-capital fields, payroll target percent, marketing percent (if a percent-driver exists), R&D percent. Mapping-table absolute bounds remain the outer envelope; NAICS band is the inner narrowing envelope.

This is contract-level only. GPT continues to decide; the lane just narrowed. The risk is GPT returning a value outside the now-tighter band — which would have been captured before by being "inside the wide universal band" but now triggers contract validation. Acceptable because Phase 4 catches the same condition at finalize.

**Exit criteria:** Existing E2Es pass. Convergence iteration count does not increase materially.

### Phase 4 — Finalize realism gate (P2)
Build `validate_industry_realism_bands` per P2 fix. New table `post_intake_finalize_realism_check_lookup`. Initially set `gate_kind = warn` for all metrics so we observe a few runs without blocking; flip to `hard_fail` per metric once we see no false positives. This gate runs after the existing finalize checks.

**Exit criteria:** Existing E2Es pass with all-warn mode; final workbook shows realism band for each ratio with `confidence_tier` annotation. Then one hardening pass flips the most-confident metrics (COGS%, AR-days, AP-days, EBITDA margin where high-confidence NAICS-6 coverage exists) to `hard_fail`. Re-run E2Es to confirm.

### Phase 5 — Convergence determinism tightening (P5, P6, P13)
1. Move `_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT`, `_CYCLE_DEADLINE_GUARD_SECONDS`, `_PLANNER_GPT_MAX_SECONDS`, `_VERIFICATION_GPT_MAX_SECONDS` to columns on the `unified_convergence_decision` sequence row.
2. Add `total_phase_budget_seconds` column. Implement total-elapsed enforcement.
3. Add oscillation hash check (state-hash-based, not error-pattern-based).
4. Reorder `numeric_solver.solve_review_plan` so the single-variable direct-estimate runs before the GPT-anchor evaluation.

**Exit criteria:** Existing E2Es pass. A deliberately oscillating intake (one that today burns the full max_attempts) fails-fast at the new oscillation-hash gate within ≤2 cycles after pattern stabilizes.

### Phase 6 — Stage-ramp asymmetric enforcement (P4)
Add Python validators for `fte_qoq_max`, `utilization_high_watermark`, `max_spike_count` symmetric with the existing revenue-QoQ-max validator. Or alternatively add a finalize-stage rejection (preferred — simpler and covered by the realism gate framework).

**Exit criteria:** Existing E2Es pass. Synthetic test with a contract violating fte_qoq_max fails-fast.

### Phase 7 — Cash policy hardcoded constants → table (P10), planning-mode table (P14), cash-strategy second-pass step (P12)
1. Add the cash-policy preferred-ratio columns; populate per cash_strategy × debt_position cell.
2. Create `post_intake_planning_mode_policy_lookup`; remove the inline `if planning_mode ==` chains.
3. Either delete the cash-strategy second-pass or formalize it as a sequence sub-step with its own contract.

**Exit criteria:** Existing E2Es pass. Cash-strategy decisions vary correctly by `debt_position` rather than by hardcoded 0.40/0.60.

### Phase 8 — Retry-discard verification (P11)
Trace and verify rejected GPT responses are not seeding next-cycle defaults. Add the explicit sequence-row boolean if any leakage path is found.

**Exit criteria:** A trace test confirms zero retained state from rejected responses.

### Phase 9 — Documentation refresh
Update [context/system_overview_update_4.25.26.md](system_overview_update_4.25.26.md) and [context/post_intake_golden_baseline_f949316.md](post_intake_golden_baseline_f949316.md) to reflect the new structural layers. Re-freeze `post_intake_lookup_table_snapshot` to capture the new sequence/context/contract rows.

---

## Appendix A — New SQL columns and tables this diagnostic recommends

**Existing table extensions (additive, backward-compatible):**

`post_intake_process_sequence_lookup` — add:
- `total_phase_budget_seconds DECIMAL(10,2) NULL`
- `non_productive_cycle_limit INT NULL`
- `cycle_deadline_guard_seconds DECIMAL(10,2) NULL`
- `planner_gpt_max_seconds DECIMAL(10,2) NULL`
- `verification_gpt_max_seconds DECIMAL(10,2) NULL`
- `discard_rejected_response_completely TINYINT(1) NOT NULL DEFAULT 1`
- `realism_metric_keys_json LONGTEXT NULL` — which baseline metrics this step's output should be checked against at finalize
- `planning_mode_gate_json LONGTEXT NULL` — which planning_modes activate this step (default: all)
- `stage_classification_gate_json LONGTEXT NULL`

`post_intake_gpt_contract_lookup` — add:
- `naics_baseline_metric_key VARCHAR(128) NULL` — when set, `min_value`/`max_value` populated at prompt-build time from this metric's NAICS cascade
- `naics_baseline_band_kind VARCHAR(32) NULL` — `min_target_max` or `target_only`
- `mapping_table_outer_envelope TINYINT(1) NOT NULL DEFAULT 1` — whether mapping-table absolute bounds remain the outer envelope

`post_intake_cash_policy_lookup` — add:
- `preferred_debt_to_assets_ratio DECIMAL(10,4) NULL`
- `preferred_equity_to_assets_ratio DECIMAL(10,4) NULL`
- `preferred_distribution_yield_target DECIMAL(10,4) NULL`
- `preferred_min_cash_runway_months DECIMAL(10,4) NULL`

`post_intake_headcount_policy_lookup` — add:
- `naics_baseline_payroll_metric_key VARCHAR(128) NULL`
- `naics_baseline_revenue_per_fte_metric_key VARCHAR(128) NULL`

**New tables:**

`post_intake_finalize_realism_check_lookup` — drives the finalize realism gate (P2). Columns: `id`, `metric_key`, `derivation_formula_key`, `quarter_aggregation` (single_quarter/year_one/horizon_average), `tolerance_bps_high_confidence`, `tolerance_bps_medium_confidence`, `tolerance_bps_low_confidence`, `tolerance_bps_generic_default`, `gate_kind` (hard_fail/warn/skip_if_no_coverage), `applicability_rule_key`, `model_input_lever_id_for_provenance`, `notes`, `active`.

`post_intake_planning_mode_policy_lookup` — drives planning-mode behavior (P14). Columns: `id`, `planning_mode`, `profitability_floor_q1_q4`, `profitability_floor_q5_q10`, `profitability_floor_q11_q20`, `loss_allowed_latest_quarter`, `tolerated_issue_codes_json`, `cycle_budget_multiplier`, `notes`, `active`.

`post_intake_stage_ramp_default_lookup` — explicit generic-default ramp ceilings when NAICS coverage is missing (P3). Columns: `id`, `stage_family`, `qoq_growth_default`, `qoq_growth_max_spike`, `q1_revenue_share_of_late_run_rate`, `q2_…`, `q3_…`, `q4_…`, `notes`, `active`.

---

## Appendix B — Coverage caveat for finalize realism gate (P2)

Several metrics are still generic-default-only (`sba_initial_interest_rate`) or coverage-thin at NAICS-6 (`marketing_percent_of_revenue` at NAICS 455211 falls through to NAICS-2 at 12.41%). For the Phase 4 finalize gate, set `gate_kind = warn` initially for any metric whose `confidence_tier` resolved is `generic_default` or `low`. Only `hard_fail` when `confidence_tier in {high, medium}` and `naics_level_used in {6, 5, 4}`. This avoids false-positive run failures while the data substrate fills in.

---

## Part 6. Honest Re-audit: Are the Tables Used to the Fullest?

The first five parts of this diagnostic land structural realism but hold back in several places where the table-driven design can go further without breaking the schedules or the OEWS title behavior. This part closes those gaps.

### 6.1 Every FINMO line on every statement gets a realism band, not "key ratios"

The Phase 4 finalize realism gate (P2) was sketched with one new table and a small initial set of "key ratios." That undersells the registry. Every line that appears on a P&L, balance sheet, or cash-flow statement and that has a NAICS-keyed metric should be covered. The 49 metrics already loaded into `post_intake_industry_baseline_lookup` are enough to cover essentially the whole live statement.

Mapping each FINMO output line to its NAICS metric so the finalize gate is exhaustive:

**P&L coverage (live Q1-Q20)**
- Revenue — covered indirectly via `Capacity × Unit Price × Utilization` reconciliation that already exists, plus QoQ growth typicals (`startup/early/mature_qoq_growth_typical`).
- COGS — `cogs_percent_of_revenue` (n=1,686 rows, strong coverage).
- Gross profit — `gross_margin_percent` (derived check; band is 1 - cogs band).
- Payroll — `payroll_percent_of_revenue` (n=1,052) and `revenue_per_fte` (n=1,103) — the latter is the more reliable check because payroll/revenue is muddier.
- Marketing — `marketing_percent_of_revenue` (NEW via SEC EDGAR, n=421).
- Advertising — `advertising_percent_of_revenue` (NEW, n=188; usually rolls into marketing — applicability rule).
- R&D — `r_and_d_percent_of_revenue` (covered when applicable per `r_and_d_applicability` GPT decision).
- Lease/Rent — `rent_percent_of_revenue` + `lease_percent_of_revenue` + `occupancy_total_percent_of_revenue` (combined; expert NAICS-2 + SEC EDGAR NAICS-6 where present).
- G&A / SG&A — `sga_percent_of_revenue` (strong NAICS coverage from industry_metrics_raw).
- Depreciation — `depreciation_percent_of_revenue`.
- Interest — derived from debt schedule and rate policy; finalize already reconciles this.
- Taxes — `effective_tax_rate` (n=1,519, strong coverage).
- Stock-based comp — `stock_based_compensation_percent_of_revenue` (NEW, n=576).
- Operating income / EBITDA / Net income — `operating_margin_percent`, `ebitda_margin`, `net_income_margin` (n=1,686 each).

**Balance sheet coverage (live Q1-Q20)**
- AR — `ar_days_dso`.
- AP — `ap_days_dpo`.
- Inventory — `inventory_days` (applicability gated to inventory businesses per business context).
- Prepaid expenses — `prepaid_expenses_percent_of_revenue` (CLOSED via SEC EDGAR, n=827).
- Deferred revenue — `deferred_revenue_percent_of_revenue` (CLOSED via SEC EDGAR, n=745; applicability gated by recurring/subscription/deposit business model).
- PP&E — `ppe_percent_of_revenue`.
- Total assets — `total_assets_to_revenue`.
- Owners' capital / equity — `owners_capital_percent_of_assets`.
- Debt — `debt_to_equity` and `debt_to_assets` (applicability gated; only checked when debt > 0).
- Current ratio — `current_ratio` (universal liquidity sanity, weak NAICS variation; warn-only).
- Quick ratio — `quick_ratio`.

**Cash flow coverage (live Q1-Q20 aggregates and per-quarter where appropriate)**
- Operating cash flow — `operating_cash_flow_margin` (NEW via SEC EDGAR, n=555).
- CapEx — `capex_percent_of_revenue`.
- Maintenance capex — `maintenance_capex_percent_of_revenue` (n=676; today the 2-15% hardcoded prose).
- Distributions — `distributions_percent_of_net_income` (n=830).
- Financing flows — reconcile to debt schedule (already covered by existing finalize check).

That's roughly 30 line-level checks. The Phase 4 fix expands `post_intake_finalize_realism_check_lookup` to one row per line above with `derivation_formula_key`, `quarter_aggregation` (per_quarter / year_one_aggregate / horizon_average), `applicability_rule_key`, `gate_kind`, and confidence-tier-keyed tolerance. The expansion is rote table population — the gate machinery from P2 doesn't change.

### 6.2 Schedules: don't break, make better

Payroll, debt, and depreciation schedules stay structurally as they are today. Each gains a NAICS-keyed sanity layer that is read-only on the schedule itself and feeds the finalize gate:

**Payroll schedule (preserve OEWS title selection unchanged)**
- *Preserved exactly as today*: Python builds the OEWS title universe from `oews_state_wages` for the business NAICS; GPT selects exact `oews_occ_title` strings from that universe; FTE Q1-Q20 ramp is GPT-authored; key-person wages from intake are injected first; Python derives `payroll-supported Capacity` from FTE × `capacity_units_per_supporting_fte`; payroll dollars come from quarter FTE × resolved wage × wage positioning multiplier × (1 + tax_benefits_pct).
- *New (additive only)*: at finalize, two sanity checks pull from the NAICS baseline:
  - **Wage realism**: average produced wage per FTE for the supporting-staff portion is compared to `avg_wage_per_fte` for the NAICS (n=2,413, strong coverage). Out-of-band by more than the confidence-tier tolerance fails the run with "produced average wage $X for NAICS Y is outside band [min..max]; check wage_positioning_tier='Z'." This does not change GPT's wage-positioning decision; it surfaces when the decision is industry-implausible.
  - **Productivity realism**: produced revenue per total FTE compared to `revenue_per_fte` for the NAICS (n=1,103). Same pattern — flags an industry-implausible labor model without overriding the schedule.
- *Carries provenance*: each payroll-schedule output row gets `wage_naics_level_used` and `productivity_naics_level_used` so the workbook shows whether the band was NAICS-6 direct or fell to a higher level.

**Debt schedule (preserve `amortizing_remaining_balance` math)**
- *Preserved*: method = `amortizing_remaining_balance`; new borrowing layers in the issue quarter; declining principal; quarterly interest from rate × remaining balance; current-portion short-term debt computed; SBA-backed forecast interest rate from `sba_loan_7a_raw`.
- *New (additive)*: rate-source cascade. Today the rate must come from `sba_loan_7a_raw` (cash-policy-table requires source = `sba_loan_7a_raw`, fallback disallowed by default). When that table is sparse for an exact NAICS, today the result is fail-fast with no SBA row. The cascade adds: SBA exact NAICS → NAICS baseline `sba_initial_interest_rate` (the same SBA data, but pre-aggregated and cascaded via the baseline lookup, so when there's no NAICS-6 row there's at least a NAICS-2 or generic_default rate) → fail-fast. Cash policy row gets a new `interest_rate_source_priority_json` column that declares this priority deterministically rather than the current binary `sba_loan_7a_raw` requirement.
- *New finalize check*: the produced interest rate per quarter is compared to the NAICS `sba_initial_interest_rate` band. Out-of-band by confidence tier flags as either rate-source mismatch or schedule misapplication.

**Depreciation schedule (preserve capex → PPE → depreciation chain)**
- *Preserved*: capex schedule, PPE roll-forward, deterministic depreciation calc.
- *New finalize checks*:
  - Produced `capex_percent_of_revenue` per quarter and year-one aggregate against NAICS band.
  - Produced `ppe_percent_of_revenue` end-of-year-one against NAICS band.
  - Produced `depreciation_percent_of_revenue` per quarter against NAICS band.
- The maintenance-capex GPT bound moves out of prompt prose into the contract row (P9) and uses NAICS `maintenance_capex_percent_of_revenue` cascade instead of the universal 2-15.

The shape of each schedule's persisted JSON does not change. The Phase 1 producer-side substitution touches only the `or 0.0` seed paths, never the schedule mechanics. The Phase 4 finalize gate touches only post-run validation, never the schedule output.

### 6.3 Sequence table fullness audit

Today `post_intake_process_sequence_lookup` carries 69 active rows covering every top-level step the controller dispatches. The 2026-05-05 E2E confirmed 69 addressable steps via `run_targeted_process_step(...)`. That breadth is good — every top-level executor function is declared. What's *not* in the table:

**Inline behaviors that should become sequence rows (sub-steps)**
- `cash_strategy_review_second_pass` (P12) — currently fires conditionally inside the cash runner when the primary decision fails normalization. Two GPT decisions in one logical step blur authority. Promote to a sub-step under parent `cash_strategy_review` with its own `recompute_of_step_key` referencing the parent and its own `contract_name = "cash_strategy_review_second_pass"`.
- `_apply_followup_exact_updates` and the model-input-repair-cell normalizer ([runtime.py:3306-3309](../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L3306-L3309)) — these execute inside the convergence loop and mutate model_input. They're sequenced today (called from `unified_convergence_apply_updates`), but they normalize repair-cell IDs in code rather than declaring the normalization in a contract row. The normalization rules should sit on the `unified_convergence_decision` GPT contract field rows.
- The convergence revenue-QoQ-max enforcer ([runner.py:132](../python/client_intake_and_finmo/post_intake_convergence/runner.py#L132)) and its three missing siblings (P4: fte_qoq_max, utilization_high_watermark, max_spike_count) — these should each be a declared sub-step `unified_convergence_enforce_<constraint>` with its own row, so the controller drives them in order and produces a uniform trace, instead of one inline call.
- The non-productive-cycle bailout, the oscillation-hash check (new in P5), and the total-phase budget check should all be declared as named guards on the `unified_convergence_decision` row through the new columns in P5/P13.

**Inline validators/normalizers/repair behaviors that should be declarative**
- A new lookup `post_intake_runtime_validator_lookup` could declare each post-cycle validator (revenue_qoq_max, fte_qoq_max, utilization_high_watermark, payroll_revenue_sanity, balance_sheet_drivers_present, debt_schedule_reconciliation, etc.) with `validator_kind`, `applicability_rule_key`, `failure_severity` (warn / hard_fail), `failure_code`, and `target_phase`. The convergence and finalize phases each enumerate validators by `target_phase` and run them. This matches the pattern already used by `post_intake_issue_codes_for_phase()` and removes the last bit of "phase runner owns business rules" stitching. Honest call: this is real work and only worth doing if more validators are coming. If the validator list stabilizes at a dozen or so, adding columns to the existing sequence row is enough.

**Cross-step recompute rules**
- The sequence table has `recompute_triggers_json` already — but in practice today, a downstream change rarely triggers an upstream rerun. Most "recomputes" are inline rebuilds inside one step. Worth a focused review per step: every output that downstream may need to recompute should declare the upstream step in `recompute_triggers_json` so the controller can drive it cleanly. The Golden Rule explicitly says: "If a downstream requirement changes an upstream output, the correct action is to rerun the upstream step through the sequence controller." Today some of those reruns happen as inline rebuilds.

### 6.4 Tables that today exist but are under-leveraged

- `post_intake_gpt_contract_lookup.min_value`/`max_value` — exists as columns; populated for some contracts but not all. The 2-15 maintenance capex bound, the supporting-staff guardrails currently in prose, and the stage-ramp ceilings should *all* sit in these columns and render into the prompt from there. P9, P3, and the supporting-staff portion of payroll should land here.
- `post_intake_gpt_contract_lookup.allowed_aliases` and `enum_values` — used for some fields, not used to lock down OEWS-title selection. The OEWS title catalog could be enumerated per-payroll-call as the `enum_values` for `oews_occ_title` so the contract validator rejects out-of-catalog titles before normalization. Today that's a runtime check ([schedule.py:1166-1186](../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1166-L1186)). Doing it at the contract layer means the GPT JSON-schema response_format itself rejects the response, which is a stronger gate.
- `post_intak_mapping_lookup.zero_allowed_reason_key` — exists per row; could explicitly name `naics_baseline_target_when_zero` so the producer-side substitution path knows whether to seed from NAICS or hold at zero.
- `post_intake_cash_policy_lookup.cash_phase_sequence_json` — exists; the 2026-05-05 E2E confirmed it drives the cash phase order. Good. No change needed.
- `post_intake_industry_metric_registry.fail_if_no_coverage` — currently 0 for all 49 metrics. This flag is the per-metric kill switch that would let an operator say "if `effective_tax_rate` has no coverage, the run fails." Phase 4 is the right time to flip this on for high-confidence metrics where NAICS coverage is broad.

### 6.5 Updated phase plan to incorporate Part 6

The 9 phases from Part 5 still hold. Edits:

- **Phase 1 (producer-side substitution)** explicitly seeds AR/AP/inventory/prepaid/deferred revenue from the NAICS days/percent metrics — covering the full balance-sheet seed surface, not just the four named silent-zero sites.
- **Phase 3 (GPT contract NAICS bound injection)** also moves OEWS titles into `enum_values` on the payroll contract row so the contract validator enforces title membership. Existing runtime catalog check stays as belt-and-suspenders.
- **Phase 4 (finalize realism gate)** populates `post_intake_finalize_realism_check_lookup` with the ~30 line-level checks enumerated in 6.1, not just a few key ratios. Includes the schedule-side cross-checks from 6.2 (avg wage, revenue/FTE, capex%, ppe%, depreciation%, interest rate band).
- **Phase 7 (cash and planning-mode tables)** also adds the cash policy `interest_rate_source_priority_json` column from 6.2.
- **New Phase 8b**: declare convergence sub-steps (cash_strategy_review_second_pass, fte_qoq_max enforcer, utilization_high_watermark enforcer, max_spike_count enforcer) as sequence rows so the controller dispatches them rather than inline runner code. Low risk — these become explicit rows under existing parents, executed by the same handlers, traced uniformly.

### 6.6 What is still preserved exactly as today (re-stated for confidence)

- Exact OEWS titles for payroll, with the Python-built title universe per NAICS, key-person wage injection, and the Q1-Q20 FTE-ramp causality.
- Debt schedule method `amortizing_remaining_balance`, declining principal, SBA-backed rate sourcing, model-input row writes (Interest Rate, Debt Issuance, Debt Repayment, Short Term Debt).
- Depreciation schedule and capex → PPE roll-forward chain.
- Mapping table formula contract; `seed_formula_key` / `finmo_formula_key` / `validation_formula_key` ownership.
- FINMO calculates only from `model_input_json`; receives no patched outputs.
- Sequence controller authority; final-for-stage output finality enforcement.
- Stage-classification validator rules (Q1-Q4 profitability postures, `loss_allowed_latest_quarter`, `operational_requires_positive_from_q5`) — these stay as Python because they're industry-invariant.

The realism layer is purely additive. Nothing in this diagnostic moves business logic out of where Python or GPT or FINMO already own it; it tightens lanes, fills silent-zero gaps with NAICS-cascaded data, and adds a finalize gate that catches industry-implausible outputs. Schedules get more sanity context, not less determinism.

---

## Part 7. Where GPT Reliance Could Be Reduced

Now that NAICS-keyed bands exist for 49 metrics, several GPT calls are doing arithmetic that the tables can do deterministically. Ranked by reducibility (highest first), with an honest read on what GPT genuinely adds vs. what it's currently doing because the NAICS data wasn't there.

### 7.1 Flatness caveat (read first)

The reduction below depends on one design rule, otherwise it produces unrealistic flat-looking statements: **deterministic baselines must position within a NAICS band, not pin to its median.** Two same-NAICS businesses landing at identical line items is just as fake as silent zeros — the realism gap moves but doesn't close.

The four mitigations that prevent flatness:

1. **Intake-anchored override.** Explicit intake values always win. If intake says monthly rent is $25K, the lease line is anchored to that; only the rest of the statement gets NAICS-positioned relative to that anchor.
2. **Position-within-band signal.** Derive a single positioning signal from intake — e.g., `revenue_per_fte_intake / revenue_per_fte_naics_median` places the business at P30 / P50 / P75 of the NAICS band. That positioning carries consistently across related line items: a high-end specialty business naturally lands at P75 on COGS, marketing, and wage positioning; a commodity-positioned business at P25. The signal is one number; the variance across lines comes for free.
3. **Stage ramp shape across quarters.** The stage ramp contract enforces Q1→Q20 variation (startup ramps utilization from 25% to full; mature stays steady; distress posture has loss curves). So even with a deterministic quarterly target, Q1 ≠ Q20 by stage shape.
4. **Different rules per metric domain.** Not every line gets the same positioning. COGS at the band P50; marketing at stage-and-NAICS-typical; lease anchored to intake-explicit; deferred revenue only when business model qualifies; distributions only when policy says so. The cross-line pattern itself differentiates a software company from a restaurant.

With those four in place, the "deterministic baseline" produces a model that's NAICS-realistic *and* business-specific. Without them, the alternative architecture would be a regression in realism. Treat 7.1 as the gate on everything below.

### 7.2 Ranked GPT reductions

**1. `maintenance_capex_percent` GPT call — delete entirely.** NAICS metric `maintenance_capex_percent_of_revenue` (n=676) supplies a direct band with confidence tier. There is no judgment GPT adds that the NAICS data doesn't already encode; today's only "judgment" is staying inside the 2–15% prose bound. Fall through to generic_default when NAICS coverage is thin.

**2. Convergence verification GPT (call #8) — redundant once the finalize realism gate lands.** Today it does fuzzy "is this convergence solution realistic" reasoning. The Phase 4 finalize gate does the same job deterministically with NAICS bands and confidence-tier-aware tolerance. Verification GPT was a workaround for the missing gate. After Phase 4, delete it.

**3. `balance_sheet_contextual_seed` — mostly replaceable.** Each line has a NAICS metric: `ar_days_dso`, `ap_days_dpo`, `inventory_days`, `prepaid_expenses_percent_of_revenue`, `deferred_revenue_percent_of_revenue`. The seed becomes `revenue_q × days/90` (or `× percent`), positioned within band per 7.1. The only real decision left is *applicability* — does this business have inventory? deferred revenue? That's a tiny per-line check. Likely a NAICS-2-keyed applicability lookup (sector 51/54 → deferred revenue likely; sector 44/45 → inventory likely) with GPT as tiebreaker only for ambiguous lines.

**4. `r_and_d_applicability` — NAICS-2 supplies the answer for ~80% of businesses.** Sector 51 (Information), 54 (Professional/Scientific/Technical), 325/333/334/336 (Pharma/Industrial Machinery/Computers/Transportation Equipment) → yes. Sector 44/45/72/81 → typically no. A small `post_intake_r_and_d_applicability_lookup` keyed by NAICS-2 with `applicability_default ∈ {required, optional, not_applicable}` covers nearly everything. GPT only fires when the row says `optional` and business context is genuinely mixed (software-enabled retail, services with proprietary platforms).

**5. Direct-fit convergence cycles (call #7 partial) — short-circuit when the cycle is one-lever/one-metric/one-quarter direct.** Today every cycle calls planner GPT first. When `len(active_lever_ids) == 1 and len(target_metric_names) == 1 and len(targeted_quarters) == 1` and the mapping between lever and metric is `direct` (e.g., `expenses::Cost of Goods Sold` directly drives `cogs`), the answer is algebraic — solve, apply, done. The numeric solver already has this path; the GPT cycle wrapping it is wasted budget. The May 2 "anchor escape hatch" bug is partly because GPT is being asked to make a decision that's algebraically determined.

**6. `cash_strategy_review` — mostly deterministic.** Cash policy already supplies `cash_floor_months`, `cash_ceiling_months`, `distribution_weight`, `debt_paydown_weight`, `retain_weight` per (cash_strategy × debt_position). Given quarterly free cash flow from FINMO, the allocation is arithmetic: `surplus = ending_cash − required_buffer; distribution_share = surplus × distribution_weight; paydown_share = surplus × debt_paydown_weight; retain_share = surplus × retain_weight`. A Python function can compute the full Q1-Q20 funding plan from the policy weights. GPT would still own *new debt issuance timing* (more judgment-bound — when to take on debt for growth investment). The existing GPT call's distribution/paydown allocation is just policy weights × FCF.

**7. Payroll headcount — three pieces become deterministic, two stay GPT.** Becomes deterministic: `wage_positioning_tier` (NAICS wage premium/discount lookup), `labor_intensity_class` (NAICS payroll/revenue band → low/medium/high), `capacity_units_per_supporting_fte` (NAICS `revenue_per_fte` ÷ avg unit price). Stays GPT: the OEWS title mix selection and the Q1-Q20 FTE ramp shape — these genuinely depend on what kind of business this is. Roughly half the payroll GPT contract becomes Python; the parts the user explicitly wants preserved (exact OEWS titles, FTE-primary ramp) stay GPT.

**8. `stage_ramp_contract` — could narrow significantly, hard to fully replace.** Once NAICS QoQ-typical bands govern the bounds, GPT's degrees of freedom shrink. A Python ramp generator that takes `(stage_family, planning_mode, NAICS_qoq_typical_band, position_within_band_signal)` could emit a default ramp deterministically; GPT becomes a "do you want to deviate from the default and why" call. Could keep GPT or could go full deterministic — depends on how much weight you give to GPT's integrative read of business specifics.

**9. `quarter_grid_openai` — hardest to reduce without architectural shift.** This is the call that composes the live model across 20 quarters × dozens of cells. Even with NAICS bounds per cell, the cell values still have to be produced. This is where the "Python proposes, GPT repairs" architecture flip would land — see 7.4 below.

**Net effect if 1–7 land:**
- Delete 2 GPT calls outright (#1 maintenance capex, #8 verification).
- Reduce 4 calls to tiny tiebreaker calls or arithmetic-with-GPT-for-edge-cases (#2 R&D, #3 balance sheet seed, #5 direct-fit convergence cycles, #6 cash strategy).
- 3 calls (#4 stage ramp, #7 payroll, #9 quarter grid) keep meaningful GPT judgment but inside much tighter NAICS-bounded lanes.

Roughly 30-40% reduction in GPT calls per run, plus dramatically less variance per remaining call. None of these reductions are required for the Phase 1–9 plan to land — they sit on top of it. Do them after the realism layer is wired and the finalize gate is hard-failing on the high-confidence metrics.

### 7.3 The "Python proposes, GPT repairs" architecture

The user asked for more on this. Today's architecture is **GPT proposes, Python validates**: `quarter_grid_openai` composes a 20-quarter model, then convergence iterates GPT until Python's validators stop complaining. The alternative inverts that order:

**Today's flow (GPT proposes):**
```
intake → GPT composes Q1-Q20 model (quarter_grid_openai)
       → Python validates against contracts/mapping/stage ramp
       → if issues, convergence loop calls GPT again with narrowed scope
       → finalize validates structural reconciliation
```

**Proposed flow (Python proposes):**
```
intake → Python composes Q1-Q20 baseline
            • intake-anchored cells (explicit values win)
            • position-within-band signal derived from intake
            • NAICS metric × position × stage_ramp_shape per cell
            • mapping-table formulas for derived drivers
       → Python validates against contracts/mapping/stage ramp/realism bands
       → if issues, convergence loop calls GPT to repair specific cells
            (GPT receives: current cell value, NAICS band, why it failed,
             which other cells must remain consistent)
       → finalize validates structural reconciliation + realism bands
```

**What changes:**
- The initial 20-quarter compose is deterministic. Same intake produces the same baseline every time.
- GPT only fires when a deterministic baseline can't satisfy a constraint (margin floor violation, coverage gap, business-model implausibility, intake conflict).
- The repair call is small and bounded: "this cell at this quarter is producing this value; the NAICS band is X; the stage-ramp ceiling is Y; the issue is Z; pick a value or explain why no value fits."

**What stays:**
- GPT still decides the integrative judgment pieces — OEWS title mix, FTE ramp shape, R&D applicability for ambiguous NAICS, new-debt-issuance timing, business-model-specific posture.
- The stage ramp contract still exists; Python uses it as input to the baseline composer rather than as a wall around GPT output.
- Mapping table, cash policy, headcount policy unchanged.

**Why this is appealing:**
- Reproducibility. Same intake → same baseline. The non-determinism shrinks to the repair calls, which are scoped narrowly.
- Cost and latency. Replacing the big initial-compose GPT call with deterministic Python is a meaningful token saving. Repair calls only fire on real issues.
- Auditability. Every baseline cell has provenance: which intake field anchored it, which NAICS row gave the band, which positioning signal, which stage-ramp shape factor. The workbook can show "Q5 marketing % = 6.2% — anchored to NAICS-3 marketing% target 6.5% × position P40 × stage ramp factor 0.95."
- Determinism for direct repairs. The single-lever single-metric direct-fit case (item 5 above) collapses to algebra, no GPT needed.
- GPT becomes a tool, not the model. Today GPT is the primary author and Python is the editor; flipping puts Python as primary author and GPT as the consultant called in for genuinely hard cases.

**Why it's risky and why I'd phase it carefully:**
- **Flatness is the killer risk.** If the position-within-band signal is weak or the per-line positioning rules are too uniform, every same-NAICS business looks identical. The mitigations in 7.1 are mandatory; they have to be tested on diverse businesses (the 2026-05-05 NexGen software vs. ValueMart retail spread is the right kind of diversity test).
- **Loss of integrative judgment on edge cases.** GPT is good at noticing "this is a high-end specialty restaurant in a college town, so margins should be tighter than NAICS median." A Python composer needs the position-within-band signal to capture that, or it misses. The signal needs intake fields that today GPT inferred from prose.
- **Repair-cascade risk.** If the deterministic baseline fails too many constraints on every run, the repair call cascades and we end up calling GPT just as much, just with smaller payloads. The threshold for "deterministic baseline is good enough" needs to be empirical — measure on real intakes, see how often repair fires.
- **Architecture flip is real work.** Today's `quarter_grid_openai` is the spine of post-intake. Replacing it isn't a wiring change; it's a redesign of the initial-grid step. Worth doing only after the Phase 1–9 plan lands and we've seen the realism layer in action.

**Suggested phasing for the architecture flip (Phase 10+, after the existing plan lands):**

- **Phase 10**: Introduce the Python composer for one self-contained line at a time. Start with maintenance capex (already a deletion candidate per 7.2 #1) — no quarter-grid integration needed. Then balance-sheet seeds (per 7.2 #3). Each replacement is a straightforward swap: GPT call out, deterministic composer in, finalize realism gate catches the band violations. Low risk because the line is already isolated.
- **Phase 11**: Composer covers the cost-ratio block (COGS%, marketing%, R&D%, SG&A%, lease%, depreciation%) using NAICS bands × position-within-band × stage-ramp shape. The convergence loop still exists for repair; the initial-compose for these lines becomes deterministic.
- **Phase 12**: Composer covers the balance-sheet days block (AR-days, AP-days, inventory-days), already largely covered by Phase 11's seeding work.
- **Phase 13**: Cash flow block (capex%, distributions%, operating cash flow margin) follows.
- **Phase 14**: The remaining `quarter_grid_openai` work shrinks to the genuinely judgment-bound parts — revenue lever shape, FTE ramp, debt issuance timing. At that point the call may stay or be replaced by smaller dedicated calls per concern, with the structure clearly visible.

The honest conclusion: **the Phase 1–9 plan in this diagnostic is necessary regardless** — finalize realism gate and NAICS-keyed bounds are the foundation. The architecture flip is an option that becomes much smaller and lower-risk once that foundation lands, because by then GPT is already choosing inside narrow NAICS-bounded lanes. Decide on the flip in a quarter or two, with empirical data from the post-Phase-9 runs, not now.

---

## Part 8. The Three-Statement Model Invariant Is Foundational

This is the constraint that everything in this diagnostic must respect, restated explicitly so no later proposal can drift from it.

### 8.1 The chain that never changes

**Drivers → Schedules → Mapping formulas → FINMO calc → Statements.**

That is the architecture. It is not negotiable. Every change in this document — the NAICS realism layer, the finalize gate, the GPT reductions in Part 7, the "Python proposes" architecture flip — operates inside this chain, never around it.

Concretely:

1. **Drivers live in `model_input_json`.** They are the only things the runtime authors. Capacity, Unit Price, Utilization, COGS%, Marketing%, Headcount FTE, Wage, Debt Issuance, Debt Repayment, Interest Rate, AR Days, AP Days, etc. — these are drivers.

2. **Schedules produce or shape drivers.** The payroll schedule (FTE-driven, OEWS-resolved, capacity-derived), the debt schedule (`amortizing_remaining_balance` over remaining principal), the depreciation schedule (capex → PPE → depreciation). Each schedule writes its driver rows in `model_input_json`. Schedules do not write statements; they write drivers.

3. **Mapping table formulas convert driver intent into derived driver values.** When `post_intak_mapping_lookup` says a row is `percent_of_revenue`, Python applies the formula: `derived_driver_value = revenue × ratio`. The formula registry is named, finite, and table-selected. Python never invents a formula.

4. **FINMO calculates the statements.** P&L, balance sheet, cash flow are computed from `model_input_json` drivers via the FINMO formulas. FINMO receives drivers, not patched output rows. The 3-statement relationship (income → equity → cash flow → balance sheet) is preserved by the FINMO calc.

5. **The numeric solver adjusts drivers within bounds.** When a target metric (cogs, revenue, margin floor, etc.) needs to be hit, the solver searches the driver space — not the statement space. It moves driver values within the allowed-lever envelope and re-runs FINMO until targets are met within tolerance or the search exhausts. The solver is part of the foundation, not an optional tool.

6. **No shortcut writes statements directly.** Not GPT, not Python, not the realism gate, not the finalize check. Statements are always FINMO output computed from drivers.

### 8.2 How every change in this diagnostic respects the chain

A walk-through, because the document deserves the explicit map:

- **Phase 1 producer-side substitution (silent-zero fixes).** When `cogs_percent_of_revenue` is missing from intake, the NAICS cascade produces a value that lands in the `expenses::Cost of Goods Sold` driver row in `model_input_json`. Same for AR-days, AP-days, marketing%, taxes%, deferred revenue%, prepaid%. These are driver values; FINMO calculates the statement rows from them. The substitution operates *upstream* of FINMO, never downstream.

- **Phase 3 NAICS bound injection on GPT contracts.** The contract row's `min_value`/`max_value` are populated from the NAICS cascade at prompt-build time. GPT picks a value inside the band; the value lands as a driver in `model_input_json`. Same path as today, just narrower input lane.

- **Phase 4 finalize realism gate.** This reads FINMO output (which was calculated from drivers), recomputes ratios from those statement rows, and compares to NAICS bands. If a ratio is out of band, the gate fails the run and surfaces the upstream driver that produced the bad ratio. It does not patch the statement; it does not patch the driver. It points at the broken upstream input. The chain is intact; the gate is a wall *after* the chain runs.

- **Phase 5 convergence determinism (oscillation hash, total budget, direct-fit short-circuit).** All of these operate inside the existing convergence loop, which already uses the solver to adjust drivers. The short-circuit specifically routes single-lever single-metric single-quarter cycles directly to the solver instead of through GPT first — *strengthening* the solver's role, not weakening it.

- **Phase 6 stage-ramp asymmetric enforcement.** Adds Python validators for fte_qoq_max, utilization_high_watermark, max_spike_count. These check FINMO output against the stage-ramp contract and either reject the cycle or trigger a rerun through the solver. The solver moves drivers; FINMO recalculates. Standard chain.

- **Phase 7 cash policy table extensions, planning-mode policy table.** Replace hardcoded constants with table columns. The cash strategy review (whether GPT or deterministic per Part 7) outputs decisions about debt issuance amounts, distribution amounts, paydown amounts. Those land as drivers in `model_input_json` (Debt Issuance lever, Debt Repayment lever, distribution lever). FINMO calculates the cash statement and balance sheet from those drivers via the debt schedule and mapping formulas. Standard chain.

- **Schedule sanity bands (Part 6.2).** The wage realism check, productivity check, capex/PPE/depreciation band check, debt rate band check — all of these read the produced FINMO values and compare to NAICS bands. They never write back into FINMO. They flag, fail-fast, or trigger an upstream solver rerun. The schedule shapes don't change.

### 8.3 Specifically on "Python proposes, GPT repairs" — what gets proposed

The Part 7.3 architecture flip needs this distinction stated cleanly because the phrasing is easy to misread:

**Python does not propose statements. Python proposes drivers.**

Concretely, the proposed flow:

```
intake → Python composes DRIVER values for Q1-Q20 in model_input_json
            • Capacity, Unit Price, Utilization, COGS%, Marketing%, etc.
            • Each driver value sourced from:
              - intake-anchored cell (explicit value), OR
              - NAICS band × position-within-band signal × stage_ramp_shape
            • Mapping-table formulas convert percent-of-revenue drivers
              and similar derived rows
       → Schedules (payroll/debt/depreciation) write their driver rows
            • Payroll: GPT-selected OEWS titles + FTE ramp → payroll-supported
              capacity → payroll dollars, all into driver rows
            • Debt: amortizing_remaining_balance schedule writes
              Debt Issuance, Debt Repayment, Interest Rate, Short Term Debt
              driver rows
            • Depreciation: capex → PPE → depreciation driver rows
       → FINMO calculates statements from the driver rows in model_input_json
       → Python validates against contracts, mapping, stage ramp,
         realism bands
       → if issues: numeric solver searches driver space within
         bounded levers to fit the target metrics
            • single-lever single-metric direct case: solver does it
              algebraically with no GPT
            • multi-lever multi-target case: GPT may be called for
              repair guidance, then solver fits the GPT-approved bounds
       → finalize validates structural reconciliation + realism bands
```

What changed vs. today: the *initial* compose of Q1-Q20 driver values is deterministic instead of being a single big GPT call. What did not change: the schedules still produce their driver rows; the mapping formulas still apply; FINMO still calculates statements from driver rows; the solver still adjusts drivers when targets need fitting; statements are never written directly. The 3-statement chain is identical.

The flip is upstream-only — it changes who picks the initial driver values, not how those values become statements.

### 8.4 What the numeric solver guarantees and why it stays

The solver is the deterministic component that holds the 3-statement model coherent under driver adjustment. It exists because:

- Targets sometimes conflict (e.g., revenue must hit X *and* margin floor must hold *and* capacity-supported FTE must reconcile to payroll). One driver move can satisfy one constraint and break another. The solver searches the joint driver space.
- Algebraic direct-fit is possible for single-lever single-metric cases (the May 2 COGS case is exactly this — local reproduction returned `0.388` correctly). The solver is the guaranteed-correct path for those.
- For multi-lever cases, the solver bounds the search to GPT/Python-approved levers and returns a coherent driver set. FINMO then recomputes statements from that set.

The solver does not invent levers, does not write statements, does not bypass the mapping table. It is the constrained optimizer over the driver space. Anything that strengthens it (Phase 5's direct-fit short-circuit, Phase 8b's declarative repair sub-steps) is good. Anything that lets values reach FINMO without going through driver bounds is forbidden.

### 8.5 The GPT-reduction proposals all respect the invariant

A line-by-line confirmation against Part 7:

| Reduction | What lands in model_input_json | Path to statements |
|---|---|---|
| Delete maintenance_capex GPT (#1) | NAICS-derived percent in maintenance capex driver row | Driver → capex schedule → PPE → depreciation → FINMO |
| Delete verification GPT (#8) | Nothing changes in driver path | Same chain; only post-hoc realism check changes |
| Reduce balance_sheet_contextual_seed (#3) | NAICS-derived AR/AP/prepaid/deferred-revenue driver values | Driver → mapping formulas → FINMO balance sheet |
| Reduce R&D applicability (#4) | NAICS-2-keyed boolean gates the R&D driver row | Driver → FINMO P&L |
| Direct-fit convergence (#5) | Solver computes single-lever fit directly | Solver → driver → FINMO recalc |
| Reduce cash_strategy_review (#6) | Python arithmetic from policy weights × FCF produces debt/distribution driver values | Driver → debt schedule + cash policy → FINMO cash flow |
| Reduce payroll judgment (#7) | wage_positioning, labor_intensity_class, capacity_units_per_FTE become deterministic; titles + FTE ramp stay GPT | Same payroll schedule path; same driver rows |
| Narrow stage_ramp (#8) | Tighter bounds on the ramp contract; solver enforces against drivers | Driver bounds → solver → FINMO |
| "Python proposes" (#9 / 7.3) | Python composes driver values; GPT repairs cells when constraints unsolvable | Same chain: driver → schedule/formula → FINMO |

Every row converges into the same path. The reductions change *who picks the driver value*, never *whether the driver value flows through the chain*.

### 8.6 What is forbidden and why

For confidence, the explicit list of things this diagnostic does not contemplate, must not contemplate, and would reject if proposed in a future iteration:

- Writing values directly to FINMO output rows. FINMO is calc-only, always.
- Bypassing the mapping table's named formula registry.
- Replacing the payroll/debt/depreciation schedules with statement-level patches.
- Letting the realism gate or the finalize check rewrite drivers or statements; gates fail-fast and surface the upstream input, never repair.
- Removing the solver in favor of GPT picking final driver values without numeric verification.
- Letting GPT propose statement rows directly (e.g., "Q5 net income = $X") instead of driver rows.
- Adding any post-FINMO patch step that changes statement values after they've been calculated.

These are all the same prohibition stated different ways: **the only path from intake to statements runs through drivers, schedules, mapping formulas, FINMO calc, and (when needed) the numeric solver.** That is the foundation of the 3-statement model and it does not move.

---

## Part 9. Stub 0 vs. Forecast, and Balance-Sheet Primacy

This is a rule the document was treating as implicit and shouldn't.

### 9.1 Stub 0 is intake fact, not the forecast trajectory

**Stub 0 is what the client said during intake. It represents Q0 actuals. It never changes.**

That's the anchor. But there's a second part that's just as important: **stub 0 is not necessarily the basis for the forecast.** Clients are often wrong about their own financials, and many people running businesses don't have a strong financial model in their head. Some intake values will be approximate, some will be wrong, and some will be legitimate zeros (the client genuinely has no inventory, no AR, no debt). All three cases look identical in the stub 0 column.

The forecast layer (Q1-Q20) reconciles this:

- **Explicit non-zero stub 0 → forecast anchor.** When the client said `monthly_rent = $25K` at intake, stub 0 holds it and the forecast lease line is anchored there, walking forward by stage-ramp shape and inflation. NAICS lease% becomes a sanity check, not an override.
- **Stub 0 = 0 because client legitimately has none → forecast keeps zero (or grows from zero per business stage).** A pre-revenue startup with stub 0 inventory = 0 stays at zero or builds inventory only as revenue comes online. NAICS inventory days becomes the forecast trajectory once revenue appears.
- **Stub 0 = 0 because client omitted or got it wrong → forecast NAICS-substitutes for Q1+, stub 0 unchanged.** This is the producer-side substitution case from Phase 1. Stub 0 is preserved as-reported; the forecast quarters get the NAICS-cascaded seed because the underlying driver clearly applies (live revenue exists, so AR clearly applies even if intake AR balance was missing).

The applicability rule is what distinguishes the second case from the third: the system must check whether the driver applies (does the business have inventory? does the business model imply deferred revenue?) before deciding whether stub 0 = 0 means "client has none" or "client omitted." That applicability check is itself a decision — table-backed by NAICS-2 sector defaults plus business-model context, with GPT as tiebreaker for ambiguous cases (covered in Part 7.2 #3).

### 9.2 Balance-sheet primacy at intake

Intake captures most balance sheet items directly: cash, debt, equity, AR, AP, inventory, PPE, prepaid, deferred revenue. Intake captures less P&L — typically revenue and a few large cost categories. As a result, **the balance sheet is the more authoritative signal of business scale at intake.** This is already documented in the 2026-04-26 update: "balance sheet intake is more authoritative than derived P&L intake because balance-sheet inputs are asked more directly."

The implication for the forecast layer is concrete:

- **Forecast must be consistent with the starting balance sheet.** A business whose stub 0 BS shows $2M total assets cannot forecast $50M annual revenue without staging the BS expansion to support it. The BS sets the floor on plausible operating scale.
- **If client-reported P&L implies a business larger than the BS supports, scale or phase the P&L.** Don't automatically upsize the BS to match an aspirational P&L. The user's design intent is explicit on this.
- **The realism gate must reconcile P&L scale to BS scale.** If forecast revenue scales to a level that would require working capital the starting BS can't fund, that's a finalize-stage signal — either phase the revenue ramp differently or surface the BS-vs-P&L conflict.

### 9.3 Implications for the realism layer

This re-shapes several Part 7 / Part 6 / Phase 1-4 details:

**The position-within-band signal (Part 7.1) gets a BS-primacy input.** Today I described it as `revenue_per_fte_intake / NAICS_median`. That's still a useful axis. But the strongest single signal of "where this business sits within the NAICS band" is BS scale: `total_assets_intake / NAICS_typical_total_assets_for_their_revenue_level`. A business with BS scale at NAICS P30 should land near P30 across cost ratios and working-capital days, not at P50. This locks cross-statement realism: the BS scale signal carries through to P&L positioning so the statements feel consistent.

**Producer-side substitution (Phase 1) is forecast-only.** Stub 0 is never touched by the NAICS cascade. The seed substitution writes Q1-Q20 driver values when intake omitted them; stub 0 keeps the client's value (including zeros). The system overview's Balance Sheet Driver Sample Rule already says this — "AR cannot disappear just because `ar_balance` was missing at intake when live revenue exists" — but it should be obvious from the diagnostic too.

**The finalize realism gate (Phase 4) validates forecast Q1-Q20, not stub 0.** Stub 0 is intake fact; it cannot fail the realism gate by definition. The gate runs on the forecast columns only. Per-quarter checks start at Q1.

**The balance_sheet_contextual_seed step (today's GPT call #3) does its real job in the gap between intake BS and forecast BS.** When intake captured the BS but at "snapshot end of last fiscal year," the seed step has to walk that snapshot into Q1 driver values consistent with revenue starting up. The NAICS substitution in Phase 1 fills the missing-line cases; this step still owns the trajectory question for the lines intake did capture. Reducing this GPT call (Part 7.2 #3) needs the BS-scale → forecast-trajectory logic to be deterministic enough; otherwise the GPT call still has work to do.

**The "Python proposes" baseline composer reads stub 0 as starting reality.** It does not propose stub 0 — that's intake. It composes Q1-Q20 driver values around the stub 0 anchors, applying NAICS bands × position-within-band signal × stage-ramp shape, with explicit intake values acting as overrides. If a Q1 forecast value would conflict materially with stub 0 (e.g., AR days dropping from 60 to 5 in one quarter), the composer should phase the transition rather than jump.

### 9.4 The forbidden moves on stub 0

Same forbidden-list pattern as Part 8.6, applied here:

- Stub 0 is never written to, mutated, or normalized by post-intake. It is intake fact.
- The producer-side NAICS cascade does not touch stub 0. It writes only forecast Q1-Q20 driver rows.
- The realism gate does not validate stub 0. It runs on forecast quarters.
- The Python baseline composer, if it lands, does not author stub 0. It reads stub 0 and composes around it.
- The numeric solver does not move stub 0 driver values. The solver searches the forecast driver space.
- A forecast cannot "fix" intake. If intake values are wrong, the run can fail-fast with a clear message about which intake field is implausible against NAICS bands; the operator decides whether to re-do intake or accept the run as-is.

### 9.5 Acknowledgment

The user noted that BS-as-tone-setter "is probably not the best way to go about this." That's a fair self-critique — ideally intake would capture P&L and BS at equal fidelity, and the forecast would reconcile both directly. In practice, asking BS questions directly produces more accurate intake than asking P&L questions, so BS gets the primacy by default. The realism layer should not pretend this asymmetry doesn't exist; it should use BS scale as the cross-statement positioning signal so the asymmetry produces *consistent* forecasts rather than P&L inflation that BS can't support. That's the realism win in this section.

---

## Part 10. The Organizing Principle: Realism-Primary, Intake-Anchored Where Reliable

This is the principle that ties Parts 1–9 together. Stating it explicitly so it governs every later interpretation.

### 10.1 The current scope

The app will eventually do many things. Right now its goal is narrower: **create real business plans for startups and operating businesses.** Post-intake is the second phase of that pipeline. Everything in this diagnostic is scoped to that goal — the realism layer, the finalize gate, the GPT reductions, the optional architecture flip. It is not over-engineering for some future use case; it is closing the gap between "the run completes" and "the plan looks real."

Two flavors of intake matter:

- **Startup intakes.** The owner often hasn't run a business at scale and doesn't have a strong financial model in their head. They'll give concrete numbers for the things they *do* know — balance sheet items they hold today, the price they intend to charge — and approximate or guess on the things they don't, like utilization, capacity ramps, year-1 headcount profile.
- **Operating-business intakes.** The owner has historical numbers for most lines but may quote them imprecisely, mix up periods, or report them inconsistently. Balance sheet items are still the most directly captured; P&L details vary more by how the operator tracks them.

Both flavors share one pattern: **some intake fields are high-confidence, others are low-confidence, and the system has to know the difference.**

### 10.2 The hierarchy of intake-field confidence

Not all intake values are equal. The forecast should treat them by their confidence tier, not uniformly:

**Tier A — Strong anchors (forecast respects these; NAICS bands tighten around them).**
- Cash, debt, equity, AR, AP, inventory, PPE balances at intake (BS items asked directly).
- Unit price the business charges (concrete and known).
- Key-person wages reported at intake.
- Existing operating expense items reported as concrete dollars (rent contracts, lease payments).

**Tier B — Medium anchors (forecast anchors but allows NAICS-conditioned drift).**
- Reported annual revenue (intake fact but interpretation varies: gross? net? trailing 12? projected?).
- Reported headcount (count is concrete; mix isn't).
- Reported business stage and operating duration.
- Reported planning_mode and cash_strategy elections.

**Tier C — Weak signals (forecast trusts NAICS realism over intake; intake informs but does not pin).**
- Inferred utilization, capacity, capacity_units_per_supporting_fte.
- Implied growth assumptions ("we'll triple in year 2").
- Inferred ramp shapes from prose responses.
- Profitability postures the client narrated.

**Tier D — Missing or zero.**
- Stub 0 = 0 because client legitimately has none of that item (legitimate zero).
- Stub 0 = 0 because client omitted or didn't know to report it (silent zero).
- Distinguishing the two is the applicability decision (Part 9.1).

### 10.3 The rule

**Forecast is based on NAICS realism, with intake fields entering as anchors only at the confidence tier where they're reliable.**

Concretely:

- **Tier A intake values fix points in the forecast.** If client reports `total_debt_outstanding = $1.2M` and `monthly_rent = $25K`, those are forecast anchors. NAICS bands operate around them as sanity context, not as overrides. The realism gate would only fail an A-tier anchor if it's grossly off (e.g., monthly rent at 80% of revenue) — and even then it surfaces the conflict for the operator rather than silently overriding intake.
- **Tier B intake values anchor with NAICS reconciliation.** Reported revenue is honored as the year-1 target, but NAICS revenue/FTE and payroll/revenue bands govern how the forecast walks Q1-Q20. If client says revenue $50M but BS scale is $2M, the BS-implied scale wins for the forecast trajectory and revenue gets phased.
- **Tier C intake values inform the prompt but don't pin numbers.** The forecast picks utilization and capacity from NAICS realism × stage-ramp shape × business-model fit. Tier C intake adds context to the GPT prompt where applicable but doesn't bind the numeric output.
- **Tier D missing values get NAICS-cascaded for the forecast (with the applicability check).** Stub 0 stays unchanged.

This is the actual organizing principle. The earlier sections in this diagnostic each implement a slice of it; Part 10 names it.

### 10.4 Why this protects the model from sparse or implausible intake

The principle is not "force forecast to align with intake" — that breaks the model when intake is sparse, internally inconsistent, or implausible. It's also not "ignore intake" — that throws away the high-confidence anchors that make the plan business-specific.

- **Sparse intake** (client gave Tier A items but skipped Tier B and C). NAICS realism fills the forecast trajectory; Tier A anchors lock the points client knew. The plan still feels business-specific because price, BS, key wages anchor it; it doesn't break because the missing pieces fall to NAICS.
- **Dumb intake numbers in Tier C** (client guessed utilization at 95% from day one). Tier C signals don't pin the forecast; NAICS realism and stage-ramp shape produce a plausible trajectory; the implausible guess doesn't propagate.
- **Dumb intake numbers in Tier A** (client reported $5M cash but it's actually $50K). The realism gate at finalize catches the cross-statement implausibility (cash supports debt service for 24 months at the reported level — but the BS-implied scale doesn't support the operating revenue). Fail-fast surfaces the conflict; operator decides whether to re-do intake or accept.
- **Aspirational intake** (Tier B revenue is 10× what BS supports). BS-primacy from Part 9 means the BS scale wins; revenue gets phased per stage ramp respecting BS scale. The plan reaches the aspiration over time instead of starting at an unsupported peak.

In none of these cases does sparse or dumb intake break the model. The realism layer is the bones; intake is the connective tissue at the points where it can hold load.

### 10.5 How the position-within-band signal updates

Part 7.1 introduced the position-within-band signal as the anti-flatness mechanism. With Part 10's hierarchy, the signal becomes:

```
position_within_band = weighted_blend(
  bs_scale_signal,        # Tier A: total_assets_intake / NAICS_typical_total_assets_at_their_revenue_level
  price_position_signal,  # Tier A: unit_price_intake / NAICS_typical_unit_price_for_business_type
  revenue_position_signal,# Tier B: scaled by BS-primacy reconciliation
)
# Tier C signals do NOT enter the position calculation.
# Tier D missing values do NOT enter.
```

This is a single number per business that places them in the NAICS band consistently across cost ratios, working-capital days, and wage positioning. A business with strong A-tier signals lands at a defined position that carries cross-statement; a business with sparse A-tier signals defaults toward NAICS P50 with stage-ramp variation. Either way the forecast looks plausible — never flat across same-NAICS businesses, never broken by sparse or implausible intake.

### 10.6 Implications for each phase already in the plan

- **Phase 1 producer-side substitution.** Already forecast-only and applicability-gated. Reaffirmed: only Tier D missing values get NAICS substituted; Tier A/B/C explicit values are preserved.
- **Phase 3 NAICS bound injection on GPT contracts.** The bounds wrap *around* Tier A anchors when those exist. For example, if intake gave `monthly_rent = $25K`, the lease driver's `min_value`/`max_value` come from `intake_anchor ± 5%` rather than from the NAICS lease% band.
- **Phase 4 finalize realism gate.** Validates Tier A anchors against extreme-deviation NAICS bands (gross conflict only). Validates Tier B-derived forecast values against confidence-tier-aware NAICS bands. Validates Tier D-substituted values against the NAICS source they came from.
- **Phase 7 GPT reductions.** Each reduction reads intake at the tier-appropriate level. The Python balance-sheet seed composer (7.2 #3) honors Tier A balances at stub 0 and walks them forward; it doesn't NAICS-substitute over a Tier A anchor.
- **The "Python proposes" composer (7.3).** Composes Q1-Q20 driver values by: read Tier A as fixed points → derive position-within-band signal from Tier A → place Tier B at the position with NAICS reconciliation → fill Tier C from NAICS × stage ramp × business-model context → fill Tier D from NAICS cascade with applicability check.

### 10.7 The principle stated minimally

The realism layer's job is to produce a plan that is:

- **Business-specific** because Tier A intake anchors carry through the forecast.
- **NAICS-realistic** because the trajectory and the gaps are filled from real industry data with provenance.
- **Robust to sparse intake** because Tier C/D fall back to realism instead of breaking.
- **Robust to implausible intake** because the realism gate surfaces conflicts rather than silently propagating bad numbers.
- **Cross-statement coherent** because the position-within-band signal carries from BS through P&L through cash flow.

That's the design rule. Everything else in this diagnostic is mechanism to enforce it.

---

## Part 11. The Cash Process — Honest Understanding After Direct Reading

This part corrects and refines the cash-related content in Parts 6.2, 7.2 #6, and 8.5. The earlier sections were directionally correct but understated how table-driven the cash pass already is, and overstated how much GPT is doing. Reading the cash modules directly — `post_intake_cash/runner.py` (4,586 lines), `common.py`, `planning_envelope.py`, the debt schedule subsystem — produces a clearer picture.

### 11.1 The cash pass is an 11-phase table-driven sequence

The phase sequence is in `_DEFAULT_CASH_PASS_PHASE_SEQUENCE` ([post_intake_mapping.py:182](../python/client_intake_and_finmo/post_intake_mapping.py#L182)) and persisted as `cash_phase_sequence_json` per (cash_strategy × debt_position) row in `post_intake_cash_policy_lookup`. The sequence controller-equivalent for cash is `_cash_pass_phase_contract` + `_record_cash_pass_phase` + `_assert_cash_pass_phase_trace_complete` in [post_intake_cash/runner.py:789-912](../python/client_intake_and_finmo/post_intake_cash/runner.py#L789-L912). Each phase records into `phase_trace` with its expected `phase_owner`, `validation_gate`, and `requires_finmo_rebuild_after`. The trace fail-fasts if a phase runs out of order or skips.

The 11 phases:

| # | phase_code | order | owner | requires_rebuild | what it does |
|---|---|---|---|---|---|
| 1 | `cash_debt_schedule_seed` | 5 | python | yes | Apply the SQL cash-policy amortizing debt schedule before review so scheduled principal is not optional. |
| 2 | `cash_short_term_debt_seed` | 10 | python | yes | Normalize current portion of long-term debt before envelope build. |
| 3 | `cash_review_context_build` | 20 | python | no | Build full 20-quarter cash envelope, strategy policy, debt snapshot, lever bounds. |
| 4 | `cash_gpt_review` | 30 | **gpt** | no | GPT fills the cash strategy decision contract. |
| 5 | `cash_translation_plan` | 40 | python | no | Translate GPT funding/policy decisions into mapped model-input driver updates. |
| 6 | `cash_apply_exact_updates` | 50 | python | yes | Apply exact updates to model_input_json and rebuild FINMO. |
| 7 | `cash_debt_schedule_rebuild` | 55 | python | yes | Rebuild debt schedule after cash updates so new debt layers properly. |
| 8 | `cash_short_term_debt_current_portion` | 60 | python | yes | Apply current portion of long-term debt after cash updates. |
| 9 | `cash_surplus_cleanup` | 70 | python | yes | Deploy residual surplus above SQL cash policy ceiling using mapped levers. |
| 10 | `cash_post_validation` | 80 | python | no | Validate cash-pass-owned issues and hard cash rules. |
| 11 | `cash_final_finmo_rebuild` | 90 | python | yes | Final FINMO rebuild for handoff to finalize. |

**Out of 11 phases, exactly 1 is GPT-owned.** The rest is deterministic Python orchestrating the debt schedule subsystem, the planning/validation envelopes, and the model_input → FINMO rebuild loop. The cash policy table tells the controller which phases run in which order; the validation_gate per phase says what "done" means for that phase; phase_trace fails fast if any phase is skipped or out of order.

### 11.2 What the GPT call actually decides

The GPT call at `cash_gpt_review` (phase order 30) is much more constrained than I described in Part 7.2 #6. The schema in `_cash_strategy_review_schema` ([runner.py:1605](../python/client_intake_and_finmo/post_intake_cash/runner.py#L1605)) shows GPT picks:

- `recommended_adjustments[].lever_id` — from a Python-derived enum (`allowed_lever_ids`)
- `recommended_adjustments[].timing_start_q` and `timing_end_q` — from a Python-derived enum (`allowed_quarters`)
- `quarter_funding_plan[].quarter_index` — from Python-derived `required_funding_quarters`
- `quarter_funding_plan[].required_funding_gap` and `expected_buffer` — Python provides the gap; GPT confirms or adjusts within bounds
- `funding_sources[].lever_id` — from `funding_source_policy.allowed_funding_source_lever_ids` (Python-narrowed)
- `funding_sources[].amount` — `integer, minimum: 0`, capped by the Python-derived per-quarter `max_value` from `_cash_strategy_lever_bounds`

Every one of these picks is from a Python-pre-computed enum or inside a Python-pre-computed numeric bound. GPT is doing a small allocation problem inside a defined feasible region. It's not making strategic calls — strategy is already encoded in the cash policy row + the funding source policy + the lever bounds.

### 11.3 What's already deterministic

Reading the modules in order, Python already owns:

- **Cash strategy resolution.** `_resolved_cash_strategy()` reads `financials_json.cash_strategy` (intake election), canonicalizes to one of `preserve_cash`, `balanced`, `shareholder_return`. Maps to a policy row. Deterministic.
- **Debt position classification.** `_cash_strategy_capital_structure_snapshot()` ([common.py:169](../python/client_intake_and_finmo/post_intake_cash/common.py#L169)) computes `debt_to_equity`, classifies as `low_debt`/`moderate_debt`/`high_debt` (with the docstring rule: "If equity is zero or negative and debt exists, classify as high_debt"). Deterministic.
- **Buffer requirement.** `buffer_components()` ([common.py:216](../python/client_intake_and_finmo/post_intake_cash/common.py#L216)) computes `cash_buffer_required = monthly_opex × cash_floor_months` from the policy row's `cash_floor_months` column. Deterministic.
- **Cash ceiling.** Same path: `cash_ceiling = monthly_opex × cash_ceiling_months`. Deterministic.
- **Debt schedule plan.** `build_debt_schedule_plan()` ([post_intake_debt_schedule/schedule.py:248](../python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L248)) computes the full Q1-Q20 amortizing plan from opening principal, the SBA-backed forecast interest rate policy, and the `amortizing_remaining_balance` method. Each quarter's required principal, interest, debt service, closing balance is computed deterministically. Pure math.
- **Debt opening seed.** `debt_opening_seed()` reads stub 0 + financials_json + intake debt fields. Deterministic.
- **Short-term current portion.** `apply_short_term_debt_current_portion()` walks the debt schedule and writes the current-portion-of-LTD driver row. Deterministic.
- **Funding source policy narrowing.** `_cash_strategy_funding_source_policy()` ([runner.py:1038](../python/client_intake_and_finmo/post_intake_cash/runner.py#L1038)) deterministically excludes debt issuance for chronic gaps with material interest drag, excludes other_equity unless externally justified. Pure rule logic; the GPT call sees only the remaining sources.
- **Per-quarter lever bounds.** `_cash_strategy_lever_bounds()` ([runner.py:1130](../python/client_intake_and_finmo/post_intake_cash/runner.py#L1130)) computes per-quarter `min_value`/`max_value` for debt_repayment, distributions, debt_issuance, owners_capital, other_equity from the violation envelope's `residual_funding_gap`, `cumulative_support_headroom`, `deployable_surplus_above_ceiling`, `max_additional_debt_paydown`, `max_additional_distribution`, `cash_support_multiplier`. Pure arithmetic from the envelope.
- **Surplus cleanup above ceiling.** `_apply_cash_policy_surplus_cleanup()` (phase order 70) deploys residual surplus above the policy ceiling using mapped cash levers. Deterministic.
- **Post-pass validation.** `_validate_cash_strategy_post_pass()` checks ending_cash ≥ buffer per quarter, hard cash rules, working-capital reconciliation. Deterministic.

### 11.4 The hardcoded constants that should be table columns (P10 confirmed)

Three module constants in `post_intake_cash/runner.py` ([lines 77-80](../python/client_intake_and_finmo/post_intake_cash/runner.py#L77-L80)) leak through Python:

- `_CASH_STRATEGY_BUFFER_MONTHS = 1.0` — used as default when `cash_floor_months` policy value is missing.
- `_CASH_STRATEGY_PREFERRED_DEBT_RATIO = 0.40` — passed to `build_cash_planning_envelope` and `build_cash_validation_envelope`. Shapes capital-structure soft guidance per quarter.
- `_CASH_STRATEGY_PREFERRED_EQUITY_RATIO = 0.60` — same.

The cash policy table already has `cash_floor_months` and `cash_ceiling_months` per row, so the buffer constant is just a fallback — fine. The two preferred-ratio constants are *not* in the table and they affect every quarter's capital structure guidance. P10's fix (add `preferred_debt_to_assets_ratio` and `preferred_equity_to_assets_ratio` columns to `post_intake_cash_policy_lookup`) is well-grounded after this read.

### 11.5 Refining the Part 7.2 #6 reduction proposal

What I said in Part 7.2 #6: "cash_strategy_review — mostly deterministic. A Python function can compute the full Q1-Q20 funding plan from policy weights × FCF."

What is actually true after the read:

- The **funding plan** is already mostly deterministic. The violation envelope produces per-quarter `residual_funding_gap`, `deployable_surplus_above_ceiling`, `cumulative_support_headroom`, `max_additional_debt_paydown`, `max_additional_distribution`. The funding source policy already narrows the source set. The lever bounds already define the feasible region per quarter.
- The **GPT call's residual judgment** is: among the remaining sources, which lever × which quarter × how much. This is a small allocation problem inside a defined feasible region with pre-computed bounds.
- A Python greedy allocator could replace it: for each quarter with `residual_funding_gap > 0`, allocate from `allowed_funding_source_lever_ids` in priority order (e.g., `owner_capital` first, then `debt_issuance` if not excluded, then `other_equity` if justified) up to the per-quarter `max_value`. For each quarter with `deployable_surplus > 0`, allocate per cash policy `distribution_weight` / `debt_paydown_weight` / `retain_weight`.
- The judgment GPT might add that a greedy allocator misses: timing nuance ("save the equity raise for Q3 when the operator can negotiate from a stronger position"). That's real but small. A priority-policy table with quarter timing rules per (cash_strategy × debt_position) could capture it.

**Refined proposal:** `cash_gpt_review` is reducible to a deterministic allocator + per-policy timing rules. Phase 30 of the cash sequence becomes Python-owned. The reduction is well-bounded because the GPT call already operates inside a tightly Python-defined feasible region.

### 11.6 The second-pass plan question (P12 reframed)

I criticized the cash strategy second pass in P12 as "two GPT decisions in a row blur authority." After reading, the second pass is more nuanced. `_build_cash_strategy_second_pass_plan` ([runner.py:2599](../python/client_intake_and_finmo/post_intake_cash/runner.py#L2599)) runs when `_normalize_cash_strategy_review_decision_from_funding_plan` ([runner.py:1663](../python/client_intake_and_finmo/post_intake_cash/runner.py#L1663)) detects the GPT decision is incomplete or inconsistent against the policy-allowed funding sources / required funding quarters. It rebuilds the funding plan deterministically from the violation envelope rather than calling GPT again — the "second pass" is Python correcting GPT's allocation, not a second GPT call.

Refined view: the second pass is actually a Python repair of GPT's funding plan inside the same lever-bounds + funding-source-policy. That's defensible. What I should have been more concerned about is the *normalization* mutation in `_normalize_cash_strategy_review_decision_from_funding_plan` itself — it can rewrite GPT's funding-source choices when they don't align with the policy. Whether that's "Python correcting an out-of-contract GPT response" (acceptable per Golden Rule) or "Python silently completing GPT's decision" (forbidden) depends on whether GPT got a valid response and Python merely normalized vs. GPT got an invalid response and Python invented the missing pieces. The fail-fast path is only triggered for `_cash_strategy_review_decision_contract_error` cases; normalization paths continue silently.

**Refined proposal:** the second pass should remain but be made fail-fast-explicit when the GPT response was incomplete/invalid, rather than silently normalizing toward policy. Or — given Part 11.5 — once the GPT call is replaced by a deterministic allocator, the second pass disappears because Python is already producing a valid plan on the first pass.

### 11.7 What the cash chain looks like through drivers (Part 8.5 confirmed)

For confidence, the chain check from Part 8.5 holds end-to-end:

1. Debt schedule plan computed → writes `expenses::Interest Rate`, `cash_flow::Debt Issuance`, `cash_flow::Debt Repayment`, `balance_sheet::Short Term Debt` driver rows in `model_input_json`.
2. Cash review GPT (or its eventual deterministic replacement) decides additional `cash_flow::Debt Issuance`, `cash_flow::Debt Repayment`, `cash_flow::Owner's Capital`, `cash_flow::Other Equity`, `cash_flow::Distributions` driver values per quarter.
3. `_apply_followup_exact_updates` ([runner.py:3152](../python/client_intake_and_finmo/post_intake_cash/runner.py#L3152)) writes those exact values to the driver rows in `model_input_json`.
4. FINMO rebuilds — `build_python_finmo_json` consumes the updated drivers, the mapping-table formulas convert percent-of-base rows, the 3-statement calc produces P&L, balance sheet, cash flow.
5. Surplus cleanup phase reads the rebuilt FINMO, computes new surplus above ceiling, writes adjustments back to driver rows, FINMO rebuilds again.
6. Post-validation reads the final FINMO and asserts ending_cash ≥ buffer per quarter, hard rules clear.
7. Final FINMO rebuild for handoff to finalize.

At no point does cash write a statement row directly. Every cash decision lands as a driver value in `model_input_json` and flows through the existing chain. The chain is intact.

### 11.8 Honest summary of cash-process understanding

What I now understand cleanly:

- The 11-phase orchestration is table-driven by `cash_phase_sequence_json` per cash policy row.
- Phases 5, 10, 20 are Python-deterministic context build (debt schedule + envelope + lever bounds).
- Phase 30 is the only GPT call; it picks lever × quarter × amount inside Python-defined enums and bounds.
- Phases 40-90 are Python-deterministic translation, application, schedule rebuild, surplus cleanup, validation, final rebuild.
- The debt schedule subsystem (`post_intake_debt_schedule/`) is pure deterministic math owned by the cash policy.
- The funding source policy already excludes inappropriate sources before GPT sees them.
- The buffer is `cash_floor_months × monthly_opex` from the cash policy row.
- Two hardcoded preferred-ratio constants (debt 0.40, equity 0.60) leak through Python and should move to the cash policy row (P10 confirmed).
- The second pass is Python repair of GPT allocation, not a re-call. The mutation/repair distinction matters for Golden Rule compliance; the path could be made more explicit.

What this means for proposals already in the document:

- **Part 6.2 (debt schedule sanity bands)**: still correct. The debt schedule is deterministic and writes drivers; adding NAICS-keyed `sba_initial_interest_rate` cascade and finalize-stage rate-band check is purely additive.
- **Part 7.2 #6 (reduce cash_strategy_review GPT)**: stronger than I had it. The GPT call already operates in a Python-narrowed feasible region; replacing with a deterministic allocator + per-policy timing rules is well-bounded.
- **Part 8.5 (cash chain through drivers)**: confirmed. Cash never writes statements; every decision lands as a driver value.
- **P10 (cash policy preferred ratios → table)**: confirmed and slightly expanded — also surface `cash_floor_months` and `cash_ceiling_months` defaults more explicitly.
- **P12 (cash second pass)**: refined. Either make the second-pass repair explicit and fail-fast on truly invalid GPT responses, or eliminate the second pass when phase 30 becomes deterministic.

### 11.9 What I still don't know about cash and would want to verify

- **The validation envelope vs. planning envelope distinction.** I know they exist (`build_cash_planning_envelope`, `build_cash_validation_envelope`), and that `assert_cash_envelope_lifecycle` asserts the lifecycle phase. I haven't read the envelope-build internals end-to-end — specifically how `cumulative_support_headroom` and `cash_support_multiplier` (interest-drag-aware support per $1000) are computed. This matters for whether a deterministic allocator can reproduce them.
- **The FINMO rebuild between phases.** Phases 1, 2, 6, 7, 8, 9, 11 all set `requires_finmo_rebuild_after = true`. Each rebuild re-runs the full FINMO calc on the updated `model_input_json`. I haven't measured the wall-time cost; it could be material across 7 rebuilds per cash pass.
- **The interaction between cash phase 70 (`cash_surplus_cleanup`) and the GPT phase 30 decision.** Phase 30 might allocate distributions, then phase 70 deploys further surplus. Whether these can conflict (e.g., GPT distributes Q5 surplus, then phase 70 also distributes Q5 surplus) needs a closer read of `_apply_cash_policy_surplus_cleanup`.

I'd verify these before writing any code that replaces phase 30. The structural understanding is solid; the deterministic-allocator implementation needs the envelope internals to be exact.

---

## Part 12. Intake Reality Check — What Is Actually Captured

This part corrects the Tier A/B/C/D hierarchy in Part 10. The earlier hierarchy was reasoning from how intake *should* be structured given the user's stated principle ("startups know BS items and prices better than utilization and capacity"). The actual intake captures are sometimes broader and sometimes narrower than that. Reading the intake handlers (`intake_consult.py`, `intake_consultant.py`, `target_market_consultant.py`, `people_capability_consultant.py`, `financials_consultant.py`, `financials_year1.py`) and the focus sequence produces a corrected map.

### 12.1 The intake focus sequence

Four sequential phases ([intake_consult.py:6392-6411](../python/api_handlers/intake_consult.py#L6392-L6411)), each producing a JSON blob in `intake_consult_drafts`:

1. **ops** → `operating_model_json` (business type, units, price, capacity, utilization, sales modality, geography, capacity driver)
2. **market** → `target_market_json` (consumer type, demographic intent, B2B industry/size/age, ACS/NAICS coding)
3. **people** → `people_json` (named people with wages and roles + LLM-inferred missing roles)
4. **financials** → `financials_json` (current state — historical/recent BS and P&L) + `financials_year1_json` (Year 1 forecast — mostly computed from ops, partially asked)

Plus two side outputs populated during or after the sequence: `fulfillment_json` (capacity model details) and `marketing_model_json` (Census/CBP-derived market sizing).

A `cash_strategy` field lives on `financials_json` and is asked at the end of the financials phase. **`planning_mode` is not an intake field at all** — it is determined post-intake by `quarter_grid.determine_planning_mode()` based on baseline profitability and feasibility. My Part 10 was wrong to put it in Tier B.

### 12.2 Corrected hierarchy: Tier A (directly asked, reliable for forecast anchor)

The intake handlers ask these as concrete numbers with explicit validation; client typically knows them or has them recorded. They survive both fidelity tests: directly asked AND reasonably reliable from any business owner.

**Balance sheet (asked individually at the financials stage):**
- `cash_on_hand` ([intake_consult.py:2033](../python/api_handlers/intake_consult.py#L2033))
- `ar_balance` ([line 2036](../python/api_handlers/intake_consult.py#L2036))
- `ap_balance` ([line 2040](../python/api_handlers/intake_consult.py#L2040))
- `inventory_balance` ([line 2044](../python/api_handlers/intake_consult.py#L2044))
- `initial_assets` (PPE proxy — equipment/furniture/fixtures, [line 2008](../python/api_handlers/intake_consult.py#L2008))
- `initial_lease` (lease balance/buyout obligation)
- `initial_equity` ([line 2014](../python/api_handlers/intake_consult.py#L2014))
- `total_debt_outstanding` ([line 2018](../python/api_handlers/intake_consult.py#L2018))
- `other_monthly_debt_payments` ([line 2022](../python/api_handlers/intake_consult.py#L2022))
- `annual_interest_payment` ([line 2026](../python/api_handlers/intake_consult.py#L2026))
- `annual_principal_payment` ([line 2029](../python/api_handlers/intake_consult.py#L2029))

**P&L (current period, recent fact):**
- `current_revenue` (current month)
- `current_payroll` (current month, [line 1966](../python/api_handlers/intake_consult.py#L1966))
- `monthly_rent_expense` ([line 1979](../python/api_handlers/intake_consult.py#L1979))
- `other_operating_expense` (monthly, [line 1992](../python/api_handlers/intake_consult.py#L1992))
- `current_num_employees` ([line 1996](../python/api_handlers/intake_consult.py#L1996))
- `current_capex` (current period, [line 2001](../python/api_handlers/intake_consult.py#L2001))

**Strategic:**
- `cash_strategy` (preserve_cash / balanced / shareholder_return — [line 2046](../python/api_handlers/intake_consult.py#L2046))

**Operations:**
- `unit_price` (per product, asked and validated as positive — [intake_consultant.py:318](../python/client_intake_and_finmo/intake_consultant.py#L318))

**Notable:** the intake captures **annual interest payment AND annual principal payment AND monthly rent**. This means the debt schedule has two more concrete anchors than I assumed in Part 6.2 — the interest rate can be back-derived from `annual_interest / total_debt_outstanding` as a sanity reading, and the principal cadence is asked directly. The realism layer should honor these.

### 12.3 Corrected hierarchy: Tier B (directly asked, but interpreted or computed)

These are captured but require interpretation, are inferred from a date, or are baseline-estimated and then confirmed.

- `business_type` (asked, then restated and confirmed — high-confidence string but interpretation-dependent for NAICS resolution)
- `business_stage` (computed from `business_start_date` per a deterministic rule — [intake_consultant.py:250-256](../python/client_intake_and_finmo/intake_consultant.py#L250-L256))
- `cogs_percent_of_revenue` — **baseline-estimated by Python, then client asked to adjust** ([intake_consult.py:2076-2088](../python/api_handlers/intake_consult.py#L2076-L2088)). So the COGS% has a NAICS-derived starting point already and the client either confirms or revises. Medium confidence: better than zero, less reliable than directly volunteered.
- `business_naics_6` — partially captured (may come from people phase or from target_market; sometimes null)
- `key_people` array with `annual_wage` per person — directly asked but client may not know exact wages; `wage_source` field tracks "told you / estimated / lookup"
- `consumer_type` (consumer / b2b / mixed)
- `lob_models` (multi-product structure when applicable)
- `capacity_driver` (labor / system / demand)
- `primary_growth_lever`

### 12.4 Corrected hierarchy: Tier C (directly asked, weak as forecast anchor)

The user's earlier point: "startup owners don't know that much, but they will have more concrete numbers for balance sheet items and their price they charge than, say, utilization or capacity." Intake *does* directly ask for utilization and capacity at the ops phase, but reliability for forecast anchoring is genuinely weaker for startups.

- `units_per_period_capacity` ([intake_consultant.py:275](../python/client_intake_and_finmo/intake_consultant.py#L275)) — directly asked but startup owners often guess
- `utilization_rate` ([line 314](../python/client_intake_and_finmo/intake_consultant.py#L314)) — directly asked, point estimate, no confidence interval; startup-owner reliability low
- `unit_cadence` (weekly / monthly / contract) — directly asked, high capture confidence
- `operating_periods_per_year` — defaulted (52 weekly, 12 monthly) unless client overrides for contract cadence
- `avg_units_per_week_year1` (per product) — directly asked OR computed from capacity × utilization. Computed values inherit Tier C reliability.
- `geographic_scope` and `geographic_coverage` — directly asked but `coverage` may be vague (intake research noted "client-named; may be vague")
- `shipping_method`, `sales_modality` — directly asked, high capture confidence
- `lobs[].products[].avg_units_per_period_year1` — direct or computed; computed inherits Tier C

The Tier C correction matters because Part 10 had capacity/utilization in Tier C with the implication that they're inferred. They're directly asked. The reliability concern is that **what the client says ≠ what they actually know.** Startup owners answer the question because they're asked, not because they have data.

### 12.5 Corrected hierarchy: Tier D (NOT directly asked at intake; post-intake must fill)

This is the critical correction. My Part 10 grouped some items as Tier A that intake never asks. The actual gaps:

**Balance sheet items intake does NOT ask:**
- `deferred_revenue_balance` — never asked. Currently silent-zero or post-intake estimated. Affects: SaaS, subscription, deposit, retainer, membership businesses.
- `prepaid_expenses_balance` — never asked. Same silent-zero or estimate.
- Short-term vs. long-term debt split — never asked; debt schedule subsystem infers
- Specific debt amortization terms (loan term, interest rate by tranche) — only annual aggregates asked

**P&L items intake does NOT ask:**
- `marketing_percent_of_revenue` — never asked at intake. Estimated post-intake by `estimate_marketing_baseline_from_context()` in `financials_consultant.py` (Census/CBP-derived).
- `r_and_d_percent_of_revenue` — never asked. Decided post-intake by `estimate_r_and_d_applicability_with_gpt`.
- `depreciation_percent_of_revenue` — never asked. Computed post-intake from `initial_assets` plus a derived rate.
- `tax_rate` / `effective_tax_rate` — never asked at intake. Defaulted by business type/state.
- `maintenance_capex_percent_of_revenue` — never asked. The 2-15% GPT call (Part 7.2 #1) fills this gap.

**Headcount items intake does NOT fully validate:**
- `inferred_roles[]` (the LLM-estimated supporting roles beyond named key people) carry **OEWS-lookup wages and speculative `months_until_hire`**. Per the intake research: "inferred_roles are 100% LLM estimates based on industry norms; annual wages come from OEWS public data, not negotiated with client; hiring timeline is speculative."
- `capacity_units_per_supporting_fte` — never captured at intake. Decided post-intake by the payroll headcount schedule GPT.
- Role mix (which functions are needed) — inferred from people list; no function coding asked.

**Strategic items intake does NOT capture:**
- `planning_mode` (rebalance / turnaround / normalize) — determined post-intake.
- Growth-rate assumptions, ramp shape — never asked.
- Seasonal adjustments, customer concentration risk, deal-size distribution — never asked.

### 12.6 What this means for the realism layer (corrected)

Several proposals in earlier parts need refinement now that intake reality is mapped:

**Phase 1 producer-side substitution (Part 5).** Confirmed to land cleanly for the actual silent-zero sites because:
- `deferred_revenue` and `prepaid_expenses` are never captured at intake. The NAICS cascade (`deferred_revenue_percent_of_revenue` n=745, `prepaid_expenses_percent_of_revenue` n=827) fills a real gap, not just a fallback.
- `marketing_percent_of_revenue` is never asked at intake — only post-intake-estimated. The NAICS cascade (`marketing_percent_of_revenue` n=421 SEC EDGAR) is the right substitution.
- `taxes_percent` is never asked. NAICS `effective_tax_rate` (n=1,519, strong coverage) is the right substitution.
- `cogs_percent_of_revenue` IS asked (Tier B — baseline + client confirm). So the substitution path here is more nuanced: when client accepted the baseline as-is, the value is essentially the post-intake estimate already; when client revised, intake's revised value wins. The silent-zero at `quarter_grid.py:107-121` only fires when *both* `current_cogs` and the cogs ratio are missing — rare but possible.

**Part 7.2 #3 (reduce `balance_sheet_contextual_seed` GPT call).** This call is now better understood as filling Tier D balance-sheet items (deferred revenue, prepaid, plus the trajectory question for the Tier A items intake captured at stub 0). The reduction is well-bounded:
- For deferred revenue and prepaid — pure NAICS substitution with applicability gate (NAICS-2 sector default for whether the item applies).
- For AR/AP/inventory — intake captured stub 0 values. The seed step's residual job is the *trajectory question*: how do those balances walk into Q1+ as revenue ramps. NAICS days metrics (`ar_days_dso`, `ap_days_dpo`, `inventory_days`) provide the trajectory directly: `ar_balance_q = revenue_q × ar_days/90`. Deterministic.
- For PPE / debt / equity — intake-anchored at stub 0; post-intake schedules (capex/depreciation, debt) own the trajectory.

So the seed GPT call can be reduced more aggressively than I had it. Most of its work becomes deterministic NAICS-cascade × Tier A-anchor logic.

**Part 7.2 #5 (payroll headcount reduction).** Confirmed and slightly expanded. Intake's `inferred_roles[]` are LLM-estimates with OEWS wages and speculative timing — Tier D. The post-intake payroll headcount schedule is the FIRST place these are actually validated against OEWS for the NAICS. So the post-intake payroll GPT call is filling real Tier D gaps that intake's people phase only loosely seeded. The reduction (wage_positioning_tier, labor_intensity_class, capacity_units_per_supporting_fte → deterministic) is correct; the OEWS title selection and FTE ramp shape stay GPT because intake doesn't capture them at all.

**Part 7.2 #1 (delete maintenance_capex GPT).** Confirmed. Intake never asks for maintenance capex. The 2-15% prose bound is filling a Tier D gap. The NAICS metric `maintenance_capex_percent_of_revenue` (n=676) replaces it 1:1.

**Part 6.2 (debt schedule cross-checks).** Refined. Intake captures `annual_interest_payment` and `annual_principal_payment` directly — both Tier A. The debt schedule subsystem can use these as anchors more strongly than I described:
- The implied current interest rate is `annual_interest / total_debt_outstanding`. Compare to NAICS `sba_initial_interest_rate` band as a sanity check.
- The implied current principal cadence is `annual_principal / total_debt_outstanding`. Compare to typical loan terms.
- These intake anchors should *constrain* the SBA-rate cascade rather than the cascade overriding them.

### 12.7 Updated position-within-band signal (Part 7.1, refined)

The anti-flatness signal needs to be rebuilt against actual Tier A captures:

```
position_within_band = weighted_blend(
  bs_scale_signal,             # Tier A: total_assets_intake (cash + AR + inventory + PPE)
                               #         vs NAICS_typical_total_assets_at_their_revenue_level
  price_position_signal,       # Tier A: unit_price × annual_units_implied
                               #         vs NAICS_typical_revenue_per_unit
  current_revenue_signal,      # Tier A: current_revenue × 12
                               #         vs NAICS_typical_revenue_for_business_size
  rent_position_signal,        # Tier A: monthly_rent × 12 / annualized_revenue
                               #         vs NAICS_typical_rent_percent
  debt_signal,                 # Tier A: total_debt_outstanding / total_assets_intake
                               #         vs NAICS_typical_debt_ratio
)
# Tier B and C signals do NOT enter the position calculation.
# Tier D missing values do NOT enter.
```

This is stronger than the Part 10 version because it pulls from five independent Tier A measurements rather than one or two. Cross-validates: if all five point to NAICS P30, the business positions consistently at P30; if they disagree (BS scale at P75 but revenue at P30 — implying low asset turnover), the realism layer surfaces the inconsistency rather than averaging it away.

### 12.8 Intake direction: fewer questions, not more (correction)

The previous version of this section suggested adding intake questions for deferred revenue, tax rate, and marketing spend. **That direction is wrong.** Intake is moving the opposite way: questions are being reduced, not added. The known reductions:

- **`cogs_percent_of_revenue` is being removed from intake.** This drops `cogs_percent_of_revenue` from Tier B (baseline-estimated with client confirm) into Tier D (post-intake derives entirely). The NAICS `cogs_percent_of_revenue` cascade (n=1,686, strong coverage) fills the gap. The `current_cogs` dollar amount may or may not stay; if it goes too, the realism layer is fully responsible.
- **`units_per_period_capacity` and `utilization_rate` are likely being removed.** Not yet final. If they go, both move from Tier C (directly asked, weak forecast reliability) into Tier D (post-intake derives). This is a much bigger structural shift because the revenue formula `Revenue = Capacity × Unit Price × Utilization` loses two of its three inputs at the source. The realism layer would have to derive capacity and utilization from NAICS bands + BS scale signal + revenue target.
- **No new questions will be added.** Deferred revenue, prepaids, taxes, marketing spend, depreciation, R&D — all stay Tier D and the realism layer takes responsibility for them.

The marketing-percent question is interesting in its own right: intake doesn't ask a number, it *backs into* a number through `_fallback_marketing_estimate` ([intake_consult.py:3205-3362](../python/api_handlers/intake_consult.py#L3205-L3362)) and the GPT-primary path through `estimate_marketing_baseline_from_context`. The audience-driven derivation (reachable market × capture rate × CAC) is closer to a deterministic schedule than to an ask. See Part 13 for the marketing schedule proposal that emerges from this.

### 12.9 The intake-reduction trajectory and what it means for the realism layer

If intake is moving toward "BS items + key prices + concrete operating facts," with utilization/capacity/COGS coming out, the realism layer does proportionally more work. The good news: this is exactly what the new NAICS baseline data is for. The trajectory:

**Before reductions (today):**
- Tier A: BS items, unit_price, monthly_rent, current_revenue/payroll/capex, debt amortization, cash_strategy
- Tier B: cogs%, business_type, business_stage, key_people_wages
- Tier C: capacity, utilization, periods, lob structure
- Tier D: deferred revenue, prepaid, taxes, marketing %, R&D, depreciation, maintenance capex, OEWS supporting wages

**After likely reductions:**
- Tier A: BS items, unit_price, monthly_rent, current_revenue/payroll/capex, debt amortization, cash_strategy *(unchanged)*
- Tier B: business_type, business_stage, key_people_wages *(COGS removed)*
- Tier C: periods, lob structure *(capacity, utilization removed)*
- Tier D: COGS%, capacity, utilization, deferred revenue, prepaid, taxes, marketing %, R&D, depreciation, maintenance capex, OEWS supporting wages

**Implication for revenue derivation.** Today: `revenue_year1 = capacity × utilization × price × periods` (Tier C inputs feed Tier B output). After reductions: revenue must come from somewhere else. Options:
1. Add an explicit "Year 1 revenue target" Tier A question (not consistent with the user's reduction direction, but most direct).
2. Derive revenue from BS scale + NAICS revenue/total-assets ratio. `total_assets_intake × NAICS_typical_revenue_per_total_assets` gives a NAICS-anchored revenue range. The position-within-band signal places the business inside it.
3. Use `current_revenue × 12` as the revenue baseline for operating businesses; for pre-revenue startups, fall to BS-scale derivation.

Option (3) is the most consistent with the existing intake captures. `current_revenue` is already Tier A and asked; it just stays as the year-1 anchor and the post-intake stage ramp shape walks Q1-Q20. For pre-revenue startups with no current_revenue, BS-scale derivation produces the year-1 target.

**Implication for the position-within-band signal (Part 12.7 refined again).** With capacity and utilization removed from intake, the signal can't pull from them. Updated:

```
position_within_band = weighted_blend(
  bs_scale_signal,         # Tier A: total_assets_intake / NAICS_typical_total_assets_at_revenue_level
  price_position_signal,   # Tier A: unit_price / NAICS_typical_unit_price_for_business_type
  current_revenue_signal,  # Tier A: current_revenue × 12 / NAICS_typical_revenue_at_BS_scale
  rent_position_signal,    # Tier A: monthly_rent × 12 / current_revenue × 12 vs. NAICS rent%
  debt_signal,             # Tier A: total_debt_outstanding / total_assets_intake vs. NAICS debt ratio
  payroll_position_signal, # Tier A: current_payroll × 12 / current_revenue × 12 vs. NAICS payroll%
)
```

Six independent Tier A signals, none of which depend on capacity or utilization. Strong cross-validation. For pre-revenue startups, three of these (current_revenue, rent_position, payroll_position) will be zero or absent — the signal then derives primarily from BS scale + price + debt, which is still adequate for positioning.

**Implication for the "Python proposes" architecture (Part 7.3 refined).** When intake reduces, the deterministic baseline composer becomes more essential, not less. The composer's job grows from "fill in Tier D items NAICS-style" to "derive Tier C and D items from NAICS bands × stage ramp × Tier A anchors, with intake-confirmed Tier A as fixed points." Capacity comes from `revenue_target / (utilization_typical × unit_price × periods)`. Utilization comes from `NAICS_typical_utilization × stage_ramp_position`. COGS comes from NAICS cascade. The composer is no longer optional once intake reduces — it's the path that produces a coherent forecast from minimal intake.

This actually makes the architecture flip *easier* to justify, because there's less GPT compose work to displace. The big initial GPT compose call (`call_quarter_grid_openai`) shrinks when most of the cell values come from deterministic NAICS × stage-ramp logic anchored to a small Tier A set. GPT remains for the genuinely judgment-bound pieces (OEWS title mix, FTE ramp shape, new debt issuance timing, business-model-specific posture).

### 12.9 Honest summary

The intake research changes my Part 10 hierarchy meaningfully:

- **Tier A grew** to include `annual_interest_payment`, `annual_principal_payment`, `monthly_rent_expense`, `other_monthly_debt_payments`, `current_revenue`, `current_payroll`, `current_capex`, `current_num_employees`, `other_operating_expense`. These are all directly asked and recently observed.
- **Tier B was clarified**: `cogs_percent_of_revenue` is baseline + client confirm (not pure direct ask). `business_stage` is computed from start_date.
- **Tier C was repositioned**: `units_per_period_capacity` and `utilization_rate` are *directly asked* but their forecast reliability is weak for startups. Capture confidence ≠ forecast reliability.
- **Tier D was clarified**: `deferred_revenue`, `prepaid_expenses`, `depreciation`, `tax_rate`, `marketing_percent`, `r_and_d`, `maintenance_capex`, `capacity_units_per_supporting_fte`, `inferred_roles_validated_wages`, `planning_mode` are all NOT captured at intake.

This refinement makes the realism layer's job clearer: NAICS substitution closes well-defined Tier D gaps; intake-anchored Tier A values fix the high-confidence points; Tier B and C inform but don't pin. The Phase 1-9 plan and the Part 7 GPT reductions hold; their fix-paths are now better grounded against what intake actually captures.

---

## Part 13. The Marketing Schedule (the user's instinct, formalized)

The user observed: "I almost wish I could make a marketing schedule (see how we back into marketing percent in intake)." That observation is sharp. Reading the marketing computation in intake confirms it: marketing percent is already a derivation, not an ask, and the derivation has the shape of a schedule. It just runs once at intake time and freezes a single annual percent rather than producing Q1-Q20 driver values.

### 13.1 What the existing marketing derivation already does

The current marketing-percent derivation at intake walks an audience-driven chain:

1. **Compute reachable market.** B2C side from Census/ACS demographics (`_build_b2c_marketing_basis`); B2B side from CBP establishment counts at the matched NAICS (`_build_b2b_marketing_basis`); composite for mixed models. ZIP/county/state geography drives the universe.
2. **Compute expected entities (customers/clients).** From `required_units_year1 / repeat_units_per_entity`, where `repeat_units_per_entity` is hardcoded by `unit_cadence` (weekly: 6 B2C / 10 B2B; monthly: 2.5 B2C / 6 B2B; annual: 1.2; default 2.0 / 3.0).
3. **Compute capture rate.** `expected_entities / combined_reachable_market`.
4. **Compute baseline marketing percent.** A deterministic adjustment chain in `_fallback_marketing_estimate` ([intake_consult.py:3227-3291](../python/api_handlers/intake_consult.py#L3227-L3291)):
   - Stage adjustment: operating +3.5%, pre-revenue +6.0%, default +4.5%
   - Market type: consumer +2.5%, mixed +2.0%, b2b +1.2%
   - Sales modality: online/ecommerce +1.8%, hybrid +1.0%, in-person/shop/facility +0.4%
   - Geographic scope: regional +0.8%, national +1.5%, local +0.2%
   - Unit price: ≥$1000 −1.2%, ≥$500 −0.6%, ≤$75 +1.5%, ≤$200 +0.8%
   - Capacity driver: labor −0.4%
   - Channel terms in marketing plan text: up to +1.5% based on count
   - Clamp to [2.5%, 18%]
5. **Classify intensity.** `low / medium / high / very_high` from the percent.
6. **Output.** Single `baseline_marketing_percent` plus `reachable_market`, `capture_rate_year1`, `expected_customers_or_clients_year1`, `expected_units_year1`. Frozen at intake; consumed by post-intake.

There is also a GPT-primary path (`estimate_marketing_baseline_from_context`) that produces the same shape; the deterministic chain is the fallback. Either way, intake produces *one annual percent*, not a per-quarter driver schedule.

### 13.2 What's wrong with marketing being a one-shot intake derivation

Three things, structurally:

1. **It's frozen at intake time, before the stage ramp is known.** The startup-vs-operating-vs-distress posture, the Q1-Q20 revenue trajectory, and the customer-acquisition ramp aren't known yet. The single percent has to cover all 20 quarters, which forces post-intake to either honor the percent flatly or override it with GPT.
2. **It doesn't write to driver rows in `model_input_json`.** Today the percent flows through the post-intake stage as a NAICS-style baseline that GPT can adjust per quarter (in `quarter_grid_openai`). It's not a schedule that produces driver values — it's a hint that GPT later interprets per quarter. That's exactly the pattern the Golden Rule says to avoid: derived behavior living as prompt input rather than as a deterministic schedule producing model_input rows.
3. **It doesn't compose with the other schedules.** Payroll schedule produces FTE → capacity → revenue support per quarter. Debt schedule produces issuance/repayment/interest per quarter. Depreciation produces capex/PPE/depreciation per quarter. Marketing should produce required acquisitions × CAC → marketing dollars per quarter. The existing derivation has the *math* of a schedule but not the *output shape* of a schedule.

### 13.3 What a real marketing schedule would look like

A `post_intake_marketing_schedule/` subsystem parallel to `post_intake_debt_schedule/`, `post_intake_headcount/`, and the depreciation logic. The shape:

**Inputs (drivers and context):**
- Reachable market by geography + market type (already computed at intake into `marketing_model_json`)
- Repeat-units-per-entity by `unit_cadence` (already computed)
- Year-1 revenue target → quarterly revenue trajectory from stage ramp shape
- `unit_price` (Tier A intake)
- `business_stage`, `planning_mode`
- NAICS-keyed band data: `marketing_percent_of_revenue` (n=421 SEC EDGAR), `advertising_percent_of_revenue` (n=188 SEC EDGAR)
- Stage-ramp signal (startup needs higher early CAC, operating businesses retain customers)

**Method (per quarter Q1-Q20):**
1. **Required entities served in quarter q** = `revenue_q / unit_price / repeat_units_per_entity`.
2. **Retained entities from prior quarters** = `entities_q-1 × (1 − churn_rate)` (churn from NAICS or business-model default).
3. **New entities required in quarter q** = `required_entities_q − retained_entities`.
4. **Required acquisitions in quarter q** = `new_entities / capture_conversion_rate` (acquisition-to-customer conversion; NAICS or stage-default).
5. **CAC in quarter q** = NAICS-keyed customer acquisition cost (back-derived from `marketing_percent_of_revenue × revenue / typical_acquisitions` per NAICS), modulated by stage:
   - Pre-revenue startup: 1.4× NAICS CAC (early-stage premium; brand is unknown)
   - Operating + scaling: 0.85× NAICS CAC (efficiency gains)
   - Default: 1.0× NAICS CAC
6. **Marketing dollars in quarter q** = `required_acquisitions × CAC_q`.
7. **Sanity ceiling**: `marketing_dollars_q ≤ revenue_q × NAICS_marketing_percent_max`. If the formula exceeds the ceiling, flag with `acquisition_demand_exceeds_industry_band` — the realism gate either accepts (with confidence_tier downgrade) or fails depending on how far out of band.

**Outputs (writes to model_input_json):**
- The driver row shape **does not change**. Marketing remains a `percent_of_revenue` driver row exactly as it is today. The schedule's job is to *produce* the per-quarter percent, not to change what model_input expects.
- The schedule's internal math computes dollars (audience × acquisitions × CAC), then divides by the quarter's revenue to derive `marketing_percent_of_revenue_q = marketing_dollars_q / revenue_q`, and writes that percent to the existing `expenses::Marketing` driver row Q1-Q20.
- The mapping table's `percent_of_revenue` formula on that row keeps doing what it does today: FINMO multiplies the percent driver by revenue to produce the P&L marketing line. No FINMO change. No mapping-table change. No driver shape change.

**Provenance (carried alongside the schedule, not in model_input):**
- `acquisition_required_per_quarter`, `cac_per_quarter`, `marketing_dollars_q` (the intermediate computation), `naics_cac_band`, `naics_marketing_percent_band`, `stage_ramp_factor`, `confidence_tier_used`. Stored in a sidecar payload (parallel to `payroll_headcount_schedule` and `debt_schedule` payloads) and shown in the workbook so the operator can see how the percent was derived. Model_input itself just sees the percent.

### 13.4 What this changes vs. today

| Aspect | Today | With marketing schedule |
|---|---|---|
| Marketing % source | Single annual percent frozen at intake | Per-quarter percent computed by schedule from audience × CAC math; same `percent_of_revenue` driver row as today |
| Quarter-to-quarter variation | Flat or GPT-adjusted | Naturally varies with revenue ramp + acquisition ramp + CAC stage modifier |
| Pre-revenue startup spike | Has to be post-intake-GPT-introduced | Falls out of the math (low retention base, high required acquisitions, high stage CAC) |
| Operating-business retention | Has to be post-intake-GPT-introduced | Falls out of the math (high retention, low new acquisitions) |
| Driver row authority | GPT (via quarter_grid_openai) within stage-ramp envelope | Schedule (deterministic) within NAICS-bounded envelope |
| Realism check | None at finalize today | Per-quarter and year-1 aggregate vs. NAICS marketing% band |
| GPT call removed | n/a | `quarter_grid_openai` no longer composes marketing rows; existing intake marketing GPT remains for audience-derivation context only |

### 13.5 How it fits with the existing chain

The marketing schedule writes the `expenses::Marketing` driver row in `model_input_json` as a **percent of revenue value per quarter** — same row, same shape, same mapping-table formula as today. From there:
- The mapping table's `percent_of_revenue` formula on the marketing row converts the percent to dollars in FINMO exactly as it does today. No mapping-table change.
- FINMO computes the P&L marketing line as `revenue × percent`. Marketing flows into operating expense → operating income → net income → cash flow → balance sheet equity (via retained earnings). No FINMO change.
- The standard Drivers → Schedules → Mapping formulas → FINMO calc → Statements chain (Part 8) is preserved exactly. Marketing is now another schedule in that chain — but its output type matches the existing percent driver shape, so nothing downstream notices the difference except that the percent now comes from a deterministic schedule instead of a GPT decision.

**This is the critical preservation:** model_input's marketing driver row is `percent_of_revenue` today and stays `percent_of_revenue` tomorrow. The schedule does its internal dollars math (audience × CAC) and converts to a percent at the boundary. FINMO never sees the schedule's internal dollars; it only sees the percent driver row it has always seen.

The numeric solver still has its role: if the produced marketing schedule + revenue ramp + payroll schedule + debt service produce a margin floor violation, the solver searches the driver space (revenue, payroll, marketing percent, debt levers) within their bounds for a coherent set. Marketing now has a deterministic baseline percent the solver can move against, not a GPT-frozen percent.

### 13.6 Where the schedule's inputs come from

| Input | Source | Confidence |
|---|---|---|
| Reachable market | Intake `marketing_model_json` (Census/CBP-derived) | Tier A indirect (intake captures geography; reach is computed from authoritative external data) |
| `repeat_units_per_entity` | Hardcoded by `unit_cadence` today; could move to a NAICS-keyed lookup | Tier B (cadence is asked; repeat rate is industry-typical) |
| Year-1 revenue target → quarterly trajectory | `current_revenue × 12` for operating, BS-scale derivation for pre-revenue (per Part 12.9), stage ramp shape | Tier A for operating, Tier B+realism for pre-revenue |
| Unit price | Intake | Tier A |
| Business stage | Intake (computed from start_date) | Tier B |
| Planning mode | Post-intake (`determine_planning_mode`) | Computed |
| NAICS marketing% band | `post_intake_industry_baseline_lookup.marketing_percent_of_revenue` | NAICS-cascade with confidence tier |
| NAICS CAC | Back-derived from NAICS marketing% × revenue / NAICS-typical-acquisitions | Computed; needs the schedule to define the back-derivation |
| Churn rate | NAICS-typical or business-model default; could be a small lookup table per business type | New table-backed default |
| Stage CAC modifier | Hardcoded factors (1.4× pre-revenue, 0.85× operating-scaling, 1.0× default); could move to the planning-mode policy table | Hardcoded → table candidate |

The schedule is fully derivable from existing intake captures plus the NAICS baseline plus a handful of small policy defaults. No new intake question is required.

### 13.7 Phasing (where this fits in the implementation plan)

The marketing schedule is a substantial new subsystem. It belongs in **Phase 11 or 12** of the existing plan (which already covered cost-ratio block deterministic composition), specifically as its own module:

- **Phase 11a (after Phase 4 finalize realism gate is hard-failing on high-confidence metrics):** introduce `post_intake_marketing_schedule/` with the audience → acquisitions → CAC → dollars math. Initial mode: produce the schedule alongside the existing GPT marketing path; finalize gate runs both and warns on divergence. This is the data-gathering phase.
- **Phase 11b (after empirical confirmation across 3-5 diverse business types):** make the marketing schedule the source of truth for the `expenses::Marketing` driver. The intake-time `_compute_marketing_model_json` becomes audience-derivation input only (its `baseline_marketing_percent` becomes a sanity check, not a driver value).
- **Phase 12:** the `quarter_grid_openai` GPT call no longer composes marketing rows; marketing flows from the schedule. This shrinks the GPT compose call's scope further.

### 13.8 Risks specific to the marketing schedule

- **Churn rate is the new unknown.** B2C SaaS, B2B services, retail, restaurants all have very different churn dynamics. NAICS-keyed defaults are a reasonable start but the band may be wide. Worth marking `confidence_tier = low` on the churn input and surfacing the assumption clearly.
- **CAC back-derivation circularity.** Computing CAC from `NAICS marketing% × revenue / acquisitions` introduces a circular dependency if acquisitions are computed from CAC. The clean break: use NAICS-typical CAC ($/customer) directly when SEC EDGAR data permits the derivation; otherwise use NAICS marketing% × NAICS revenue / NAICS new-customer-count as the base. The numeric is straightforward; the data sourcing needs care.
- **The audience-driven model breaks for some industries.** Software with viral organic growth, restaurants in tourist locations, professional services with referral-only acquisition — for these, the audience × capture × CAC formula understates or overstates marketing. Worth keeping a `business_model_marketing_pattern` table that overrides the default formula for known patterns (e.g., `b2b_referral_dominant` → marketing% = 1-3% regardless of audience math).
- **Existing E2Es may shift.** Both passing E2Es from 2026-05-05 (NexGen Software, ValueMart Superstores) had GPT-authored marketing per quarter. Switching to a schedule will produce different numbers. Phase 11a's "produce alongside, warn on divergence" mode is exactly to surface those shifts before they become regression failures.

### 13.9 SQL registration: parallel to debt and payroll schedules

The marketing schedule must be registered in the same table-backed pattern as the existing schedules. That means three table changes:

**A. `post_intake_process_sequence_lookup` — add a sequence row.**

Each schedule today has its own step in the sequence table:
- Payroll headcount schedule has its sequence rows under the initial-grid phase.
- Debt schedule has rows inside the cash phase sequence (`cash_debt_schedule_seed` at order 5, `cash_debt_schedule_rebuild` at order 55, `cash_short_term_debt_current_portion` at order 60).
- Depreciation runs as part of the post-intake derived-driver chain.

The marketing schedule needs analogous sequence rows. Sketch:

| step_key | phase | parent | order | handler_key | contract_name | required_lookup_tables |
|---|---|---|---|---|---|---|
| `post_intake_marketing_schedule_compose` | initial_grid | (top-level) | after `payroll_headcount_schedule` | `compose_marketing_schedule` | none (deterministic) | `post_intake_marketing_policy_lookup`, `post_intake_industry_baseline_lookup`, `post_intake_process_context_lookup` |
| `post_intake_marketing_schedule_apply` | initial_grid | `post_intake_marketing_schedule_compose` | next | `apply_marketing_schedule_to_model_input` | none | `post_intak_mapping_lookup` |
| `post_intake_marketing_schedule_finalize_check` | finalize | (top-level) | inside finalize | `validate_marketing_schedule_band` | none | `post_intake_industry_baseline_lookup`, `post_intake_finalize_realism_check_lookup` |

`required_context_keys`, `produced_output_keys`, `output_storage`, `output_finality`, `timeout_seconds`, and `recompute_triggers_json` follow the same conventions as the payroll schedule rows.

**B. New table `post_intake_marketing_policy_lookup` — parallel to `post_intake_headcount_policy_lookup`.**

The headcount policy table has 1 row keyed by `policy_code = "default"` and columns for OEWS wage sources, payroll/revenue sanity bounds, wage positioning multipliers, payroll trend rules, etc. The marketing analog:

```
policy_code                                     VARCHAR(64) PRIMARY KEY (default: 'default')
model_input_driver                              VARCHAR(128)  -- 'expenses::Marketing'
schedule_storage_field                          VARCHAR(128)  -- e.g. 'marketing_schedule' column in intake_consult_drafts
forecast_horizon_quarters                       INT           -- 20

-- Audience and acquisition policy
naics_marketing_metric_key                      VARCHAR(128)  -- 'marketing_percent_of_revenue'
naics_advertising_metric_key                    VARCHAR(128)  -- 'advertising_percent_of_revenue'
naics_cac_back_derivation_method                VARCHAR(64)   -- e.g. 'naics_marketing_pct_x_revenue_per_typical_acquisitions'
repeat_units_per_entity_by_cadence_json         LONGTEXT      -- replaces the hardcoded 6/2.5/1.2/2.0 etc.
churn_rate_default_by_business_model_json       LONGTEXT      -- per business_model_pattern (b2b_recurring, b2c_subscription, b2c_transactional, etc.)

-- Stage modulation
stage_cac_modifier_pre_revenue                  DECIMAL(10,4) -- 1.4
stage_cac_modifier_early_operating              DECIMAL(10,4) -- 1.1
stage_cac_modifier_operating_scaling            DECIMAL(10,4) -- 0.85
stage_cac_modifier_mature                       DECIMAL(10,4) -- 1.0

-- Override patterns for non-audience-driven business models
business_model_pattern_overrides_json           LONGTEXT      -- e.g. b2b_referral_dominant -> marketing% = 0.01..0.03 regardless of audience math

-- Validation policy
naics_band_confidence_tier_priority_json        LONGTEXT      -- order in which to accept high/medium/low/generic
finalize_realism_band_kind                      VARCHAR(32)   -- hard_fail / warn / skip_if_no_coverage
notes                                           LONGTEXT
policy_status                                   VARCHAR(32)   -- 'active'
```

Default row: `policy_code = "default"`, with sensible NAICS-pointers and the existing hardcoded values from `_fallback_marketing_estimate` migrated into the JSON columns. Once populated, the schedule code reads the policy through a new `post_intake_marketing_policy_lookup()` function in `post_intake_mapping.py` (parallel to `post_intake_cash_policy_for()` and `post_intake_headcount_policy_lookup()`).

**C. `post_intake_process_context_lookup` — declare the schedule's required context.**

Same pattern as every other process step: declare `step_key = "post_intake_marketing_schedule_compose"` rows for each context key the schedule reads (`marketing_model_json`, `financials_year1_json`, `business_facts.naics`, `stage_ramp_contract`, `current_revenue`, etc.). The runtime context resolver fills these from the appropriate sources at execution time.

**D. `post_intake_lookup_table_snapshot` — add the new policy table.**

The `_post_intake_snapshot_source_tables()` list ([post_intake_mapping.py:4618](../python/client_intake_and_finmo/post_intake_mapping.py#L4618)) currently freezes seven tables for the golden baseline check. Add `post_intake_marketing_policy_lookup` as the eighth so the preflight catches drift on it the same way.

### 13.10 Excel workbook output: marketing schedule tab

The client workbook export (`python/client_statements_output_excel/export_client_workbook.py` per [intake_consult.py:7024](../python/api_handlers/intake_consult.py#L7024)) already produces schedule tabs for payroll, debt, and depreciation per the system overview's "client FINMO Excel workbook" rule. The marketing schedule should appear there as a parallel tab.

**Tab content (proposed shape, parallel to existing schedule tabs):**

- **Header section:** business name, NAICS, `marketing_basis_type` (consumer / b2b / mixed), reachable market totals (B2C, B2B, combined), `confidence_tier_used`, `naics_level_used`, source data tag.
- **Inputs block (Q1-Q20 columns):** revenue per quarter (read-only link from Model Inputs), required entities served, retained entities (from prior quarter × (1−churn)), new entities required, required acquisitions, `cac_per_quarter`, `stage_cac_modifier`.
- **Computation block (Q1-Q20):** `marketing_dollars_q = required_acquisitions × cac_q`, `marketing_percent_q = marketing_dollars_q / revenue_q`, NAICS band check (`naics_marketing_pct_min`, `naics_marketing_pct_target`, `naics_marketing_pct_max`), in-band flag.
- **Output block (Q1-Q20):** `marketing_percent_of_revenue` per quarter — the value that lands in Model Inputs. This is the cell the workbook shows is being written into the `expenses::Marketing` driver row on the Model Inputs tab.
- **Provenance footer:** `naics_cac_band`, `business_model_pattern_override_applied`, `confidence_tier`, `data_source`, `derivation_formula`, `applicability_rule`. Same pattern the payroll tab uses for OEWS title sources.

**Workbook flow preserved.** The user's existing rule (system overview "Required Schedule Invariant" + 2026-05-04 client FINMO Excel update):
- Schedule tabs contain editable operating mechanics.
- Model Inputs links to those schedule tabs (the marketing percent cells in Model Inputs link to the marketing schedule tab's output block).
- FINMO links to Model Inputs.
- Checks validates formula/coherence.

So the marketing schedule tab fits the existing tabular convention exactly: it's an editable operating-mechanics tab whose output cells feed Model Inputs through formula links. If the operator wants to override the schedule's computed percent, they edit a cell on the marketing schedule tab; Model Inputs updates by reference; FINMO recalculates from Model Inputs. Same edit pattern as payroll/debt/depreciation.

**Honest note on workbook scope.** I haven't read `export_client_workbook.py` or its dependents, so the exact column-by-column tab shape will need to follow the conventions of the existing payroll/debt/depreciation tabs once those are reviewed. The points above are the structural requirements; the exact spreadsheet layout matches whatever convention the existing schedule tabs use.

### 13.11 Summary

The user's instinct — "I almost wish I could make a marketing schedule" — is structurally sound. Marketing today is a one-shot intake-time derivation that has the math of a schedule but the output shape of a frozen percent. Promoting it to a real Q1-Q20 schedule subsystem parallel to payroll/debt/depreciation would:

- Produce per-quarter marketing dollars from audience × capture × CAC math
- Eliminate one of the GPT-authored dimensions of `quarter_grid_openai`
- Capture stage-aware ramp behavior (high CAC pre-revenue, retention-heavy operating) deterministically
- Provide a finalize realism check against the NAICS marketing% band per stage
- Preserve the Drivers → Schedules → Mapping formulas → FINMO chain exactly as Part 8 requires

It's the natural next addition to the schedule family. Worth doing after the existing realism layer (Phases 1-9) is in place and stable.

---

## Appendix C — Items intentionally not changed

The Golden Rule is explicit that several behaviors must not be touched even when realism wiring lands:

- **Payroll FTE → capacity → revenue causality.** Payroll is not derived from a payroll/revenue ratio. The ratio is reasonableness context.
- **Mapping table formula contract.** Formulas chosen by SQL, executed by Python from the deterministic registry. Not changed.
- **FINMO calculates from `model_input_json` only.** Producer-side seed substitution lands in `model_input_json` (or in the contextual-seed step that writes it). FINMO sees only the resulting drivers.
- **Debt schedule, depreciation schedule, payroll schedule.** Already deterministic and table-backed. The realism gates in P2 reconcile the produced FINMO output against NAICS bands; they do not bypass these schedules.
- **Sequence controller authority.** All new behavior threads through `PostIntakeSequenceController.execute_registered_step`, declares context inputs and produced outputs in `post_intake_process_context_lookup`, and respects `final_for_stage` output finality.

This diagnostic's bias is to *augment* the structural skeleton with a NAICS-realism layer rather than to refactor anything that already passes the Golden Rule check.
