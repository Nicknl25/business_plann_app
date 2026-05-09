# Phase 9 — Adaptive Operating Doctrine Audit (Phase A: Audit Only)

**Status:** Audit complete. No code changes. Awaiting Phase B directive.
**Branch:** intake-stable
**Date:** 2026-05-09
**Doctrine reference:** Phase 9 directive (Phase A) — 7 rules + 6 legitimate terminal causes.

This document inventories every contradiction between the post-intake codebase
and the adaptive operating doctrine. Each row cites a specific file and
line range. Severity classifies how much it blocks correct planning today.

---

## 1. Executive summary — top 10 contradictions

Ranked by how far each pulls the system away from doctrine.

| # | Contradiction | File:line | Doctrine rule | Severity |
|---|---|---|---|---|
| 1 | Stage-based waivers skip mode-policy floors for startup/early/turnaround | [post_intake_mapping.py:3111-3132](../python/client_intake_and_finmo/post_intake_mapping.py#L3111-L3132) | Stage & planning mode rule (deterministic policy, not waiver) | CRITICAL |
| 2 | Solver writes one value to Q1–Q20 for every lever it moves | [orchestrator.py:103-131](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L103-L131) | Real ramp rule (path-shaped, not flat) | CRITICAL |
| 3 | 1% unit_price ramp is a hardcoded linear nudge, not a path | [orchestrator.py:1176-1258](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1176-L1258) | Real ramp rule | CRITICAL |
| 4 | All 27 realism metrics missing issue_family / remediation_family / primary_levers / deadline_quarter | [post_intake_realism/lookup.py:101-625](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L101-L625) | Hard fail / warning rule (must route to adaptation family) | CRITICAL |
| 5 | Cascade Tier 7 declares success even when residuals remain | [adaptation_cascade.py:680-688](../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L680-L688) | Hard fail rule (adaptation required before client output) | CRITICAL |
| 6 | GPT calls per planning run = 13–21, doctrine cap = 4 | [consultant_band_shaping.py:254-287](../python/client_intake_and_finmo/post_intake_solver/consultant_band_shaping.py#L254-L287), [consultant_target_shaping.py:200-229](../python/client_intake_and_finmo/post_intake_solver/consultant_target_shaping.py#L200-L229), [consultant_conflict_adjudication.py:331-371](../python/client_intake_and_finmo/post_intake_solver/consultant_conflict_adjudication.py#L331-L371) | GPT rule (max 4, Python-first) | CRITICAL |
| 7 | Cascade Tier 3 widens ALL hard_fail gates indiscriminately, not the specific failing metric | [adaptation_cascade.py](../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py) (Tier 3a/3b) | Hard fail rule (issue-aware, not progressive-loosen) | HIGH |
| 8 | Cascade Tiers 5/6/7 force planning_mode/stage shifts that touch operating drivers without issue diagnosis | [adaptation_cascade.py:586-688](../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py#L586-L688) | Stage & planning mode rule (deterministic policy) | HIGH |
| 9 | Cash buffer / minimum cash sourced from hardcoded policy table, not industry profile | [post_intake_mapping.py:55-150](../python/client_intake_and_finmo/post_intake_mapping.py#L55-L150) | (Industry profile completeness — supports adaptation rules) | HIGH |
| 10 | Payroll ratio and leverage metrics queried from NAICS but not stage-aware | [cohort_band_resolver.py:62-98](../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py#L62-L98) | Stage rule (stage drives ramp shape; payroll/leverage envelopes should ramp by stage) | HIGH |

---

## 2. Foundation — pieces already aligned with the doctrine

Documenting what NOT to break. These are the components Phase B–E should preserve and build on.

| Component | Why it's aligned | Reference |
|---|---|---|
| **Cash pass funding-only scope** | Cash strategy adjusts only debt_issuance, debt_repayment, owners_capital, other_equity, distributions, short_term_debt_percent_of_ltd. Reads operating drivers but never modifies them. | [post_intake_cash/runner.py:46-65](../python/client_intake_and_finmo/post_intake_cash/runner.py#L46-L65), [orchestrator.py:1260-1372](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1260-L1372) |
| **Cash pass invocation gate** | Cash is only invoked when `failed_rule_codes == {"liquidity_failure"}`. Other failed rules force convergence loop to continue. | [post_intake_cash/runner.py:644-659](../python/client_intake_and_finmo/post_intake_cash/runner.py#L644-L659) |
| **stage_ramp_contract.quarter_ramp_grid** | GPT-designed per-quarter revenue/utilization/cost/profitability bounds carrying genuine path shapes (s-curve, turnaround, glidepath, capacity expansion, convergence decay). | [post_intake_contracts/runner.py:1842-2084](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1842-L2084) |
| **`_enforce_composite_revenue_ramp_inside_envelopes()`** | Path-aware enforcement of `quarter_ramp_grid` bounds with priority Utilization → Capacity → Unit Price (absorption first, expansion second, price last). | [quarter_grid.py:2362-2507](../python/client_intake_and_finmo/quarter_grid.py#L2362-L2507) |
| **`_quarter_grid_stage_maturity_row()`** | Per-quarter cost-cap and ni_floor lookup that already implements stage-as-policy correctly. | [quarter_grid.py:1096-1105](../python/client_intake_and_finmo/quarter_grid.py#L1096-L1105) |
| **stage / planning_mode computation** | Both computed deterministically by Python. `_infer_business_stage()` is pure date math; `stage_planning_ramp_policy()` is whitelist + SQL lookup. No GPT in computation. | [post_intake_contracts/runner.py:154-167](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L154-L167), [post_intake_mapping.py:2984-3133](../python/client_intake_and_finmo/post_intake_mapping.py#L2984-L3133) |
| **Realism gate exception** | Validator raises `RealismBandViolation` on first hard_fail; orchestrator catches and routes through adaptation cascade rather than letting it terminate the run. | [post_intake_realism/validator.py:817](../python/client_intake_and_finmo/post_intake_realism/validator.py#L817), [orchestrator.py:880-943](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L880-L943) |
| **Phase 3 GPT consultants are LEGITIMATE-CONSULTANT type** | Band shaping, target shaping, and conflict adjudication each address genuine ambiguity (industry-vs-business, hard_fail vs warn under stage, intake-vs-band integrity). The *categorization* is correct — only the *call count* is wrong. | [consultant_band_shaping.py](../python/client_intake_and_finmo/post_intake_solver/consultant_band_shaping.py), [consultant_target_shaping.py](../python/client_intake_and_finmo/post_intake_solver/consultant_target_shaping.py), [consultant_conflict_adjudication.py](../python/client_intake_and_finmo/post_intake_solver/consultant_conflict_adjudication.py) |
| **Cascade resolver + Phase 3.5 cohort resolver** | Single entry point `post_intake_industry_baseline_for_naics(metric_key, naics_6)` with cohort-first/cascade-fallback, trust flags, confidence tiers, fallback chain stamping. | [post_intake_industry_baseline/lookup.py](../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py), [cohort_band_resolver.py](../python/client_intake_and_finmo/post_intake_solver/cohort_band_resolver.py) |
| **6 legitimate terminal failure paths exist correctly** | Realism formula registry, GPT context misconfiguration, query/transform registry, sequence controller, missing SQL contracts, finalize aggregation — each maps to one of the 6 doctrine terminal causes. | See §3 category 1 |

---

## 3. Full contradiction table

Severity legend: CRITICAL = directly produces broken plans · HIGH = lets broken plans through · MEDIUM = friction/imprecision · LOW = cosmetic/dead code.

### Category 1 — Terminal failure paths

Doctrine terminal causes (legitimate):
1. Missing required intake drivers · 2. No NAICS/industry fallback · 3. Invalid SQL mapping/schema · 4. FINMO formula integrity · 5. Impossible accounting identity · 6. Unhandled code exception.

Anything else that terminates the run today contradicts the doctrine and must route to adaptation.

| File | Line(s) | Code surface | Doctrine rule violated | What it does today | What it should do | Severity |
|---|---|---|---|---|---|---|
| post_intake_solver/target_seeking_loop.py | 282-290 | returns `{"status":"no_candidate_levers",…}` | (returns diagnostic, not raise — orchestrator routes correctly) | Returns status dict; orchestrator at 880-943 catches it and invokes cascade | LEGITIMATE — already routes to adaptation. No change. | LOW |
| post_intake_solver/target_seeking_loop.py | 352-370 | returns `{"status":"stuck_pinned",…}` | (returns diagnostic) | Same as above | LEGITIMATE — already routes. | LOW |
| post_intake_solver/target_seeking_loop.py | 396-403 | returns `{"status":"max_iterations_reached",…}` | (returns diagnostic) | Same as above | LEGITIMATE — already routes. | LOW |
| fail_fast/post_intake_fail_fast/fail_fast.py | 650-653 | `raise RuntimeError("quarter_grid_stage_ramp_revenue_bridge_failed: …")` when `not fail_fast_enabled` | Hard fail rule + Real ramp rule | Raises RuntimeError unconditionally outside test mode | Should route to adaptation cascade. Stage_ramp bridge failure ≠ FINMO formula integrity failure (unless re-classified by user — see open question). | HIGH |
| post_intake_realism/validator.py | 817 | `raise RealismBandViolation(message, results=results)` | (raises but caught) | Orchestrator catches at 1404-1426 and stores in realism_gate_payload, then runs cascade | LEGITIMATE — caught and routed. No change. | CRITICAL (kept as-is) |
| post_intake_realism/schedule_sanity.py | 593-596 | `raise RealismBandViolation(...) if raise_on_hard_fail and status=="out_of_band_hard_fail"` | (raises but caught) | Caught by orchestrator | LEGITIMATE. | HIGH (kept as-is) |
| post_intake_realism/formulas.py | 602 | `raise RealismFormulaNotRegistered(...)` | Doctrine cause #4 (FINMO formula integrity) | Raises when formula key missing from registry | LEGITIMATE terminal. | CRITICAL (kept as-is) |
| post_intake_solver/consultant_context_resolver.py | 92-97, 318, 396 | `raise FailFastError`, `raise ValueError("data_query_not_registered")`, `raise ValueError("unsupported_transform_kind")` | Doctrine cause #3 (invalid SQL mapping/schema) | Raises on missing query/transform/context | LEGITIMATE terminal. | CRITICAL (kept as-is) |
| post_intake_solver/consultant_band_amendment_rules.py | 77-82 | `raise FailFastError(...)` for buffer-rule violation | Doctrine cause #3 | Raises on band-retention floor breach | LEGITIMATE terminal. | CRITICAL (kept as-is) |
| post_intake_sequence.py | 83-87 | `raise RuntimeError("post_intake_sequence_controller_required: …")` | Doctrine cause #6 (architectural violation) | Raises when post-intake fn called outside sequence controller | LEGITIMATE terminal. | CRITICAL (kept as-is) |
| post_intake_sequence.py | 96-100 | `raise RuntimeError("post_intake_sequence_controller_wrong_step: …")` | Doctrine cause #6 | Raises on wrong active step | LEGITIMATE terminal. | MEDIUM (kept as-is) |
| post_intake_cash/runner.py | 104-108 | `raise RuntimeError("cash_strategy_contract_horizon_missing: …")` | Doctrine cause #1 (missing required driver) or #3 (missing SQL contract row) | Raises when SQL contract horizon undefined | LEGITIMATE terminal. | CRITICAL (kept as-is) |
| post_intake_runtime_validation/finalize_post_intake.py | 36-39 | `raise RuntimeError("post_intake_finalize_validation_failed: …")` | (aggregates other terminal causes) | Aggregates payroll/debt/table/sequence errors and raises if any | LEGITIMATE — aggregator of legitimate terminals. | CRITICAL (kept as-is) |
| post_intake_solver/sanity_assertion.py | 96-219 | `assert_solver_respected_targets()` returns dict; caller decides to raise | Hard fail rule (adaptation required before output) | Returns structured violation diagnostic; current callers do not raise | AMBIGUOUS — Phase 2 spec said caller raises. Verify intended escalation policy. | HIGH |
| post_intake_solver/joint_feasibility_check.py | 86-99+ | returns FeasibilityResult(feasible=False) | (gate, not raise) | Orchestrator forwards to feasibility_restoration cascade | LEGITIMATE — already routes. | MEDIUM |
| post_intake_solver/structural_feasibility_check.py | 328-340+ | returns StructuralFeasibilityResult(feasible=False) | (gate, not raise) | Orchestrator invokes feasibility_restoration cascade at 527-546 | LEGITIMATE — already routes. | MEDIUM |

**Category 1 summary:** 13 legitimate terminals; 1 contradiction (stage_ramp_revenue_bridge raise); 3 ambiguous (sanity_assertion needs decision on raise policy). The diagnostic-dict pattern in target_seeking_loop is correctly handled — orchestrator catches and routes.

---

### Category 2 — Quarter-flat solver applications

Doctrine: solver updates must be path-shaped (s-curve, turnaround recovery, linear-to-mature, glidepath, capacity expansion, convergence decay). Same value Q1–Q20 reserved for genuinely stable mature drivers (rent, fixed annual contracts).

| File | Line(s) | Code surface | Driver(s) modified | Flat or path? | Should be | Severity |
|---|---|---|---|---|---|---|
| post_intake_solver/orchestrator.py | 103-131 | `_build_apply_lever_callable()` wraps `apply_exact_lever_updates_to_model_input()` with `for q in range(1, horizon+1)` writing identical updates | EVERY solver-tweaked driver (COGS, Marketing, G&A, Payroll %, Capacity, Utilization, Unit Price, Headcount ratios) | FLAT (Q1–Q20 same value) | PATH-SHAPED for almost all; flat only for rent/fixed contracts | CRITICAL — single biggest violation |
| post_intake_solver/target_seeking_loop.py | 380 | `apply_lever_value_callable(state_input, lever_id, new_value)` | Whichever lever solver picked this iteration | FLAT (downstream of orchestrator.py:103) | PATH-SHAPED | HIGH (downstream of #1) |
| quarter_grid.py | 1721 | `apply_exact_lever_updates_to_model_input()` writes exact_value to `row["values"][quarter_index…]` | Generic write function | FLAT by definition | Caller-dependent — needs callers to pass per-quarter paths | MEDIUM (function not inherently wrong; callers misuse it) |
| finmo_bridge.py | 3027 | Revenue section: `values = [baseline_value for _ in slots]` (non-projection mode) | Capacity, Unit Price, Utilization | FLAT initial seed | PATH-SHAPED initial seed (industry QoQ trajectory by stage) | CRITICAL |
| finmo_bridge.py | 3216-3294 | Expense section non-projection mode: cogs/marketing/payroll/g_and_a/taxes/depreciation ratios applied uniformly | All ratio expense lines | FLAT (ratio held constant) | Mostly path-shaped (efficiency improvement glidepath, scale economies); rent stays flat | HIGH |
| finmo_bridge.py | 3517 | Debt Issuance schedule: `[0.0 for _ in slots]` | Debt Issuance | FLAT (schedule-locked) | CORRECTLY FLAT — driven by cash pass per-quarter, not solver | LOW (correct) |
| finmo_bridge.py | 3519 | Debt Repayment schedule: `[0.0 for _ in slots]` | Debt Repayment | FLAT (schedule-locked) | CORRECTLY FLAT — driven by amortization | LOW (correct) |
| finmo_bridge.py | 3525 | Capital Expenditures: `[explicit_capex_overrides.get(idx, 0.0) for idx in range(...)]` | Capex | MIXED / per-quarter overrides | CORRECTLY PATH-SHAPED | LOW (correct) |
| finmo_bridge.py | 3532 | Less: Principal Repayments: `[quarterly for _ in slots]` (annual/4) | Principal Repayments | FLAT | CORRECTLY FLAT — deterministic amortization | LOW (correct) |
| orchestrator.py | 1338 | Cash pass debt issuance: per-quarter computed gap | Debt Issuance | PATH-SHAPED | CORRECTLY PATH-SHAPED | LOW (correct) |
| orchestrator.py | 1218-1248 | Unit Price post-cascade ramp `base * 1.01^(q-1)` | Unit Price | PATH-SHAPED but generic linear | See Category 10 — wrong shape (generic, not stage_ramp_contract-aware) | CRITICAL |

**Category 2 summary:** The core solver mechanism (`_build_apply_lever_callable`) is the single biggest violation — every solver lever movement is broadcast flat across Q1–Q20. The Phase 8 unit_price ramp partially patches one driver (Unit Price); Capacity, Utilization, COGS%, Marketing%, Payroll%, G&A% are still flat. Schedule-locked items (capex, principal, debt issuance/repayment) are correctly path-aware.

---

### Category 3 — Cash pass entanglement

Doctrine: cash pass MAY adjust debt_issuance, debt_repayment, owners_capital, other_equity, distributions, minimum cash buffer. May NOT adjust revenue, COGS, payroll, G&A, pricing, utilization, capacity, or EBITDA tolerance.

| File | Line(s) | Code surface | What cash touches today | Doctrine verdict | Severity |
|---|---|---|---|---|---|
| post_intake_cash/runner.py | 46-65 | `_CASH_STRATEGY_ALLOWED_LEVER_IDS` whitelist | debt_issuance, debt_repayment, short_term_debt_percent_of_ltd, owners_capital, other_equity, distributions | ALIGNED (all funding-only) | LOW |
| post_intake_cash/runner.py | 515-516 | Reads `revenue` and `ebitda` from FINMO row | Read-only context for buffer sizing | ALIGNED (read-only) | LOW |
| post_intake_cash/runner.py | 553-556 | Reads payroll/marketing/r_and_d/lease_rent in `operating_expense_from_row()` | Read-only operating-expense aggregate for buffer sizing | ALIGNED (read-only) | LOW |
| post_intake_cash/runner.py | 644-659 | `_hard_rules_can_defer_to_cash_strategy()` | Cash invoked only when failed_rule_codes == {"liquidity_failure"} AND accounting_integrity_passed | ALIGNED (liquidity-only invocation) | LOW |
| post_intake_cash/planning_envelope.py | 127-146 | Hard rule: distributions forced to 0 when cash ≤ buffer | Capital distribution control | ALIGNED | LOW |
| post_intake_cash/planning_envelope.py | 147-166 | Hard rule: equity payback blocked when cash ≤ buffer | Funding control | ALIGNED | LOW |
| post_intake_cash/validation_envelope.py | 121-140 | Same hard rules post-action | Funding control | ALIGNED | LOW |
| post_intake_cash/cash_strategy_proposer.py | (full file) | Selects ONE funding source per quarter from allowed_funding_source_lever_ids; validates against per-quarter lever_bounds | Funding selection only | ALIGNED | LOW |
| orchestrator.py | 1260-1372 | Phase 8 minimal cash strategy: walks quarter_rows, computes funding gaps, issues debt sized at `sum(gaps)*1.1` in first deficit quarter | Modifies only `debt_issuance` lever; rebuilds FINMO | ALIGNED | LOW |

**Category 3 summary:** ZERO doctrine violations found. Cash pass is funding-only by construction. Read-only access to revenue/EBITDA/payroll/marketing/r_and_d/rent for buffer sizing is correct. Cash runs after operating drivers are solved (post-cascade tail). Three legacy modes (preserve_cash, balanced, shareholder_return) all respect funding-only constraint. **This is one of the cleanest pieces of the system.**

---

### Category 4 — Planning mode and business stage as labels vs policy

Doctrine: stage and mode are deterministic adaptive policy inputs. Stage determines ramp shape and deadlines. Mode determines adaptation objective.

| File | Line(s) | Use type | What it does today | Doctrine verdict | Severity |
|---|---|---|---|---|---|
| **post_intake_mapping.py** | **3111-3116** | **WAIVER** | Skips `operational_requires_nonnegative_from_q1` rule when family ∈ {startup, early} OR distress context | Mode policy must apply uniformly OR floor *values* (not application) must vary by stage. Skip-pattern violates "deterministic policy input." | **CRITICAL** |
| **post_intake_mapping.py** | **3113-3114** | **WAIVER** | Skips `operational_requires_positive_from_q5` rule for startup/early/turnaround | Same as above | **CRITICAL** |
| **post_intake_mapping.py** | **3115-3116** | **WAIVER** | Skips `profitability_floor_q1_q4` for startup/early/turnaround | Same as above | **CRITICAL** |
| **post_intake_mapping.py** | **3117-3118** | **WAIVER** | Skips `profitability_floor_q5_q10` for startup/early/turnaround | Same as above | **CRITICAL** |
| **post_intake_mapping.py** | **3121-3132** | **WAIVER (fallback)** | `elif family not in {startup,early} and not distress:` applies hardcoded operational floors only when policy table absent | Soft fallback masquerading as policy. Either codify in planning_mode_policy SQL table or fail-hard. | **CRITICAL** |
| post_intake_mapping.py | 3056-3071 | POLICY | startup family: Q1–Q4 revenue ceiling 0.25/0.40/0.60/0.80 + 7 ramp rules | Stage drives ramp shape — correct | LOW |
| post_intake_mapping.py | 3072-3088 | POLICY | early family: Q1–Q4 ceiling 0.55/0.70/0.85 + 5 ramp rules + losses through Q8 | Correct | LOW |
| post_intake_mapping.py | 3089-3095 | POLICY | distress branch: 4 turnaround-specific rules | Mode drives adaptation objective — correct | LOW |
| post_intake_mapping.py | 3096-3104 | POLICY | operational baseline: 5 rules + Q5 positive posture | Correct | LOW |
| post_intake_realism/validator.py | 296-315 | POLICY | `_profitability_floor_for_quarter()` reads `planning_mode_policy.profitability_floor_q*` | Correct | LOW |
| post_intake_realism/validator.py | 361-370 | POLICY | `_planning_mode_policy()` SQL lookup | Correct | LOW |
| post_intake_realism/validator.py | 426-431 | POLICY | Builds tolerated_codes set from active_policy | Correct | LOW |
| post_intake_realism/validator.py | 732-737 | POLICY | Raises effective_min to mode floor when floor > band_lower | Correct | LOW |
| post_intake_realism/validator.py | 748-762 | POLICY | Downgrades hard_fail → warn when issue code ∈ tolerated_codes | Correct | LOW |
| post_intake_solver/adaptation_cascade.py | 252-275, 326, 586-609, 615-625, 680-688 | POLICY | Tier 5/6/7 use stage_family + planning_mode to widen contract | Stage+mode drive adaptation — direction correct, but cascade logic itself violates issue-aware doctrine (see Cat 6) | LOW (within Cat 4); see Cat 6 |
| numeric_execution.py | 314-343, 350-357, 576-649 | POLICY | Mode → solver posture (turnaround→restore_working_business_earlier; normalize→remove_overstatement; rebalance→rebalance_business_shape) | Correct | LOW |
| post_intake_contracts/runner.py | 154-167 | POLICY | `_infer_business_stage()` from `business_start_date` (pure date math) | Correct | LOW |
| post_intake_contracts/runner.py | 6301-6307 | POLICY | `_business_stage_family()` normalizes to {startup, early, operational} | Correct | LOW |
| financials_year1.py | 1372-1374 | HINT | Adds business_stage to GPT context_signals as label | Vague hint, not policy | MEDIUM |
| financials_year1.py | 1460-1467 | HINT | Soft-trigger r_and_d_setup_check when stage ∈ {pre-revenue, early-stage} | Heuristic, not deterministic | MEDIUM |
| post_intake_headcount/schedule.py | 2027-2029 | HINT | Passes stage/mode to GPT headcount consultant context | Soft context, not enforced | MEDIUM |
| post_intake_convergence/runtime.py | 1927-1932 | HINT | Echoes stage/mode to compact contract output | Informational, low risk | LOW |
| intake_consult_draft.py | 344, 425-426, 579-580 | HINT | Echoes mode in draft output for UI | Display only | LOW |

**Category 4 summary:** 20 correct policy uses, 5 hint uses (medium severity), 5 critical waivers. The waivers at post_intake_mapping.py:3111-3132 are the doctrine's headline contradiction — they are exactly the "vague label" anti-pattern the doctrine forbids. Stage and mode computation chains are otherwise clean, deterministic Python.

---

### Category 5 — Hard fail / warning surface

Doctrine: hard fail = adaptation required before client output (not "stop the run"); warning = adapt, stage-tolerate with reason, or accept-with-documented-exception (not "log and ignore").

Two anti-patterns to detect:
- (A) warnings sitting passively (logged but never acted upon)
- (B) hard fails that ARE legitimate per the 6 terminal causes vs hard fails that should route to adaptation

| File | Line(s) | Check | Today's action | Anti-pattern | Should | Severity |
|---|---|---|---|---|---|---|
| post_intake_realism/validator.py | 95-100, 55, 764-817 | `RealismBandViolation` raise on hard_fail | Raises immediately; orchestrator catches and runs adaptation cascade | Neither (correct) | Keep | LOW |
| post_intake_realism/validator.py | 819-820 | `if status == "out_of_band_warn": warnings_list.append(...)` | Appended to payload `warnings`. No inline escalation. Caller is expected to inspect, but contract is undocumented. | A | Define explicit warn-path contract: each warning must route to adaptation, stage-tolerate, or accept-with-exception. | MEDIUM |
| post_intake_realism/validator.py | 502-529 | `gate_kind == "skip_if_no_coverage"` | Returns status="skipped" silently | Neither (legitimate skip) | Keep | LOW |
| post_intake_realism/validator.py | 532-561, 668-700 | Missing tolerance config / band edges missing | Skip + reason tagged | Neither (data signal) | Keep but log for completeness audit | MEDIUM |
| post_intake_realism/validator.py | 759-763 | `derived_issue_code in tolerated_codes` → downgrade hard_fail to warn | Mode-driven downgrade is correct policy | Neither | Keep | LOW |
| post_intake_realism/validator.py | 750-752, 288-293 | 4 metrics with mode-driven escalation: ebitda_margin, net_income_margin, operating_margin_percent, gross_margin_percent | Hard_fail ↔ warn based on planning_mode tolerated codes | Neither | Keep — extend to all metrics with `tolerated_issue_codes` | LOW |
| post_intake_realism/schedule_sanity.py | 143-230 | `_check_wage_realism()` | warn-only; no escalation path | A | Wage out-of-band must route to adaptation OR accept-with-exception ("BLS OEWS shows owner-led labor at this wage tier"). Today it logs and forgets. | HIGH |
| post_intake_realism/schedule_sanity.py | 238-341 | `_check_productivity_realism()` (revenue per FTE) | warn-only | A | Same — must route or document. | HIGH |
| post_intake_realism/schedule_sanity.py | 351-451 | `_check_debt_rate_realism()` | warn-only | A | Same — debt rate out-of-band should adapt rate to NAICS or document override. | HIGH |
| post_intake_realism/schedule_sanity.py | 462-540 | `_check_capex_ppe_consistency()` (PPE chain drift > 5%) | warn-only | A | Drift in PPE chain is structural — should route to adaptation, not warn-and-forget. | HIGH |
| post_intake_realism/schedule_sanity.py | 548-605 | `validate_schedule_sanity()` | Aggregates all warnings; no hard_fail escalation regardless of count | A | Define escalation rule: e.g., 2+ schedule warnings → hard_fail and route to adaptation. | HIGH |
| post_intake_realism/formulas.py | 1-50 | 27 formula implementations | Return None on div-by-zero/missing input; never raise | Neither (fail-safe by design) | Keep | LOW |
| post_intake_realism/formulas.py | 588-609 | `RealismFormulaNotRegistered` | Raises on missing formula_key (terminal cause #4) | Neither | Keep | LOW |
| post_intake_solver/sanity_assertion.py | 96-219 | `assert_solver_respected_targets()` | Returns dict with violations; current callers do not raise | A or B (depends on intent) | Decide: raise on residual_violations (stamp adaptation as required), or document caller's accept-with-exception path. | HIGH |
| post_intake_solver/joint_feasibility_check.py | 86-192 | `verify_joint_feasibility()` | Returns feasible=False; orchestrator routes to adaptation | Neither (correct) | Keep | LOW |
| post_intake_solver/structural_feasibility_check.py | 328-564 | `verify_structural_feasibility()` | Returns feasible=False; orchestrator runs feasibility_restoration | Neither (correct) | Keep | LOW |
| fail_fast/post_intake_fail_fast/fail_fast.py | 22-176 | Test-mode flag groups; raise only when CONVERGENCE_TEST_MODE=true AND POST_INTAKE_FAIL_FAST_ENABLED=true | Production silently passes; test mode raises | A in production (production has no parallel escalation surface for these named flags) | Document or remove test-mode flags that have no production counterpart. | LOW |

**Category 5 summary:** 19 metric-level hard_fails and 8 metric-level warns are correctly designed (validator.py raises and routes). The schedule_sanity layer (4 checks: wage, productivity, debt rate, capex/PPE) is the contradiction — all four are pure warn-only with no escalation path. The schedule warnings sit in payload and the caller (orchestrator/finalize) does not currently route them. This is exactly anti-pattern A.

---

### Category 6 — Adaptation cascade tier ladder

Doctrine: adaptation should be ISSUE-AWARE — a detected issue maps to a specific remediation family with specific levers. Doctrine REJECTS "progressively loosen tolerances until something passes."

| Tier | Name | Entry | What it does | Issue-aware or progressive-loosen? | If progressive-loosen, what loosens? | Severity |
|---|---|---|---|---|---|---|
| 1 | gpt_band_relaxation | Tier 0 fail or starting_tier directive | Reverts GPT-calibrated driver bands to Python defaults ONLY when retained-band width < 25% floor | Issue-aware (band over-amendment), but defensive — should be no-op if R2 buffer rule is enforced upstream | n/a | MEDIUM |
| 2 | cohort_fallback | Tier 1 fail | Walks back ALL cohort_matched drivers to NAICS cascade baseline; updates provenance to `naics_cascade_for_adaptation` | Progressive-loosen (blanket revert; no issue specificity) | All cohort-matched drivers reverted regardless of which one is failing | MEDIUM |
| **3a** | **target_tolerance_widened (warn)** | Tier 2 fail | Widens ALL warn-gate target tolerances by 1.5x from target midpoint | **Progressive-loosen** | 1.5x band widening on every warn metric | **HIGH** |
| **3b** | **target_tolerance_widened (hard_fail)** | Tier 3a fail | Widens ALL hard_fail-gate target tolerances by 1.5x | **Progressive-loosen — primary contradiction** | 1.5x band widening on every hard_fail metric, NOT just the failing one | **CRITICAL** |
| **4** | **supplementary_levers_used** | Tier 3 fail | Rebuilds influence_map with `targeting_allowed=True` forced globally | **Progressive-loosen** | Drops the targeting_allowed safety filter for every lever | **HIGH** |
| **5** | **planning_mode_shifted** | Tier 4 fail OR original_mode != "turnaround" | Re-invokes inner_runner with `planning_mode="turnaround"` | **Progressive-loosen + violates cash-pass-funding-only** | Forces turnaround posture globally; rebuilds revenue/payroll/cash assumptions | **CRITICAL** |
| **6** | **stage_family_widened** | Tier 5 fail AND stage can widen | Advances stage_family (startup→early→operational), rebuilds stage_ramp_contract, re-invokes inner_runner with `planning_mode="turnaround"` + new stage | **Progressive-loosen + violates cash-pass-funding-only** | Stage advancement; alters revenue/payroll ramps and operating model | **CRITICAL** |
| **7** | **generic_fallback_no_calibration** | Tier 6 fail (always lands) | Resets envelope to pure NAICS cascade (discards GPT/cohort calibration), widens targets by **2.0x**, forces `mode=turnaround` + `stage=operational`, sets `success=True` regardless of residuals | **Progressive-loosen MAXIMAL — accepts residuals** | Full envelope reset, 2x widening, turnaround+operational forced; **success declared with residuals still present** | **CRITICAL** |

**Category 6 summary:** Tiers 3, 4, 5, 6, 7 are progressive-loosen, not issue-aware. The cascade is organized by *loosening mechanism* (bands → cohorts → targets → levers → mode → stage → reset) instead of by *issue family* (revenue achievability → margin compression → headcount feasibility → working capital → leverage → cash runway). Only Tiers 1 and 2 are partially issue-aware. Tier 7's `success=True` with residuals directly contradicts the doctrine ("hard fail = adaptation required before client output").

**Missing adaptation families** (gaps): revenue_achievability, margin_compression, payroll_ratio_excess, working_capital_inversion, leverage_excess, cash_runway, formula_consistency. Each should be its own tier with targeted lever moves, replacing the current generic-loosen ladder.

---

### Category 7 — Realism table metric coverage

Doctrine: every realism metric should carry `issue_family`, `remediation_family`, `primary_levers`, `secondary_levers`, `stage_sensitivity`, `deadline_quarter`.

Out of 27 metrics in [post_intake_realism/lookup.py:101-625](../python/client_intake_and_finmo/post_intake_realism/lookup.py#L101-L625):

| Doctrine field | Coverage |
|---|---|
| issue_family | **0/27** |
| remediation_family | **0/27** |
| primary_levers | **0/27** |
| secondary_levers | **0/27** |
| stage_sensitivity | 0/27 (formal field); 1 informal mention (ebitda_margin notes) |
| deadline_quarter | **0/27** |

| Currently present | Coverage |
|---|---|
| metric_key, finmo_line_label, derivation_formula_key, quarter_aggregation, tolerance_bps_*, gate_kind, notes, active | 27/27 |
| governs_model_input_lever_id | 17/27 (63%) |
| applicability_rule_key | 9/27 (33%) |

**No orphan metrics** — all 27 are evaluated by validator.py.

**Partial issue-code mapping** lives in validator.py:288-293 (`_REALISM_METRIC_BELOW_BAND_TO_ISSUE_CODE`) covering only 4 metrics (ebitda_margin, net_income_margin, operating_margin_percent, gross_margin_percent → `mature_loss_state` / `early_revenue_under_run_rate`). This mapping should move into lookup.py rows so it is visible to all consumers.

| Severity tier | Metrics |
|---|---|
| **CRITICAL** (core metrics missing remediation routing) | cogs_percent_of_revenue, gross_margin_percent, marketing_percent_of_revenue, rent_percent_of_revenue, sga_percent_of_revenue, depreciation_percent_of_revenue, ebitda_margin, prepaid_expenses_percent_of_revenue, deferred_revenue_percent_of_revenue, owners_capital_percent_of_assets, operating_cash_flow_margin, capex_percent_of_revenue |
| **HIGH** | r_and_d_percent_of_revenue, payroll_percent_of_revenue, effective_tax_rate, operating_margin_percent, net_income_margin, ar_days_dso, ap_days_dpo, total_assets_to_revenue, debt_to_equity, debt_to_assets, distributions_percent_of_net_income |
| **MEDIUM** | inventory_days, current_ratio, quick_ratio, advertising_percent_of_revenue |

**Schema gap:** the SQL table at lookup.py:77-99 has no columns for `issue_family`, `remediation_family`, `primary_levers`, `secondary_levers`, `deadline_quarter`. Phase B will require schema migration.

---

### Category 8 — Industry target profile completeness

Doctrine implies a unified industry profile per business covering revenue scale, gross margin, SG&A, payroll ratio, marketing, R&D, working capital, capex/depreciation, leverage, cash buffer.

| Dimension | Loaded? | From | Unified? | Stage-aware? | Severity |
|---|---|---|---|---|---|
| Revenue scale (cap categories) | ✓ | cohort_band_resolver.py:196-221 (business_profile-keyed) | Unified | ✓ (stage + revenue → small/mid/large) | LOW |
| Gross margin | ✓ | post_intake_realism/lookup.py:247; cohort_band_resolver.py:80 | Unified (single metric_key) | ✓ (cascade tiered) | LOW |
| SG&A ratio | ✓ | lookup.py:307; cohort_band_resolver.py:65,81-82,84 | Unified | ✓ | LOW |
| **Payroll/personnel ratio** | ✓ | lookup.py:319 (NAICS cascade only) | **Fragmented** — no cohort column; workforce metrics (avg_wage_per_fte, revenue_per_fte) on separate track | **✗** | **HIGH** |
| Marketing/advertising | ✓ | lookup.py:259-268 → maps to sga_percent column | Unified (via SGA convention) | ✓ | HIGH (fragmentation through SGA proxy) |
| R&D | ✓ | lookup.py:282; cohort_band_resolver.py:64,83; applicability gate | Unified | ✓ (NAICS-2 applicability) | MEDIUM |
| Working capital (DSO/DIO/DPO) | ✓ | lookup.py:405-442; cohort_band_resolver.py:70-72,88-90 | Unified (3 metric_keys) | ✓ (inventory NAICS-2 gated) | LOW |
| **Capex/depreciation** | ✓ | lookup.py:330-340,556-566; cohort_band_resolver.py:96-97 | Unified | **✗** (no startup-capex-heavy → mature-capex-light variance) | MEDIUM |
| **Leverage / debt ratio** | ✓ | lookup.py:516-538; cohort_band_resolver.py:93-94 | Unified | **✗** (startup tolerable D/E ≠ mature) | HIGH |
| **Cash buffer / minimum cash** | ✗ | post_intake_mapping.py:55-150 (hardcoded DEFAULT_CASH_POLICY_ROWS keyed by cash_strategy + debt_position) | **Fragmented** — not from NAICS at all | ✗ (policy-driven) | **CRITICAL** |

**Inventory of industry-related call sites:**

| Site | What it pulls |
|---|---|
| driver_movement_assembler.py:104 | `post_intake_industry_baseline_for_naics(metric_key, naics_6)` — primary cascade entry |
| driver_movement_assembler.py:142 | `resolve_cohort_band(metric_key, business_profile)` — cohort-first |
| driver_movement_assembler.py:183 | `post_intake_baseline_applicability_for_naics2(metric_key, naics_2)` |
| output_target_assembler.py:71, 128 | Same two entry points |
| finmo_bridge.py:406 | `post_intake_industry_baseline_for_naics()` |
| post_intake_balance_sheet/contextual_seed.py:362 | `post_intake_industry_baseline_for_naics()` |
| lookup.py:147-159 | `post_intake_industry_metric_registry_row(metric_key)` (49 active rows) |

The cascade resolver + cohort resolver pair is a **strong foundation**. Two structural gaps: (1) cash buffer is entirely orthogonal to NAICS (policy table only); (2) payroll and leverage are queried from NAICS but not stage-adjusted. There is no single "get_industry_profile(naics_6, stage, target_revenue) → dict of all 10 dimensions" — callers loop one metric at a time (correct but inefficient).

---

### Category 9 — GPT call surface

Doctrine: max 4 GPT calls per planning run. Python-first detection, options computation, and application. GPT chooses only when ambiguity requires it.

**Reality:** 13–21 calls per planning run. Three consultants each loop per item:

| Consultant | File | Loop | Calls/run |
|---|---|---|---|
| Band shaping | consultant_band_shaping.py:254-287 | per applicable, non-locked lever | 3–5 |
| Target shaping | consultant_target_shaping.py:200-229 | per metric | 8–12 |
| Conflict adjudication | consultant_conflict_adjudication.py:331-371 | per detected intake-vs-band conflict | 2–4 |
| **Total per run** | | | **13–21 (typical ~16)** |

**Helper:** `call_gpt_with_schema_or_fallback()` in [_gpt_critic_io.py:95-236](../python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py#L95-L236).

**Orchestrator call sites** (one each, looped consultants invoked beneath them): orchestrator.py:622-628, 637-646, 661-667.

| File | Line(s) | What it asks GPT | Category | Per-run count | Severity |
|---|---|---|---|---|---|
| consultant_band_shaping.py | 254-287 | Per lever: keep/tighten/widen NAICS band, or flip applicability | LEGITIMATE CONSULTANT (genuine ambiguity per lever) | 3–5 | HIGH (count, not category) |
| consultant_target_shaping.py | 200-229 | Per metric: tighten (mature) vs widen (early-stage / turnaround) | LEGITIMATE CONSULTANT (stage-aware judgment) | 8–12 | HIGH (count, not category) |
| consultant_conflict_adjudication.py | 331-371 | Per conflict: keep_intake / keep_band / split | LEGITIMATE CONSULTANT (data integrity vs valid variance) | 2–4 | HIGH (count, not category) |

**Categorization is correct** — these are genuine human-judgment decisions. **Frequency violates doctrine** — the per-item loop pattern produces 4× to 5× the doctrine cap.

**Doctrine rewrite needed:** Python-first proposal pattern. Python computes a deterministic proposal for every lever/metric/conflict. GPT is invoked once at the consultant level (not once per item) to *critique the batch*: "Of these 12 metric proposals, which 0–4 do you disagree with and why?" That collapses 8–12 calls into 1.

**No GPT calls found in deterministic territory** (formula validation, ratio math, scanning every quarter). The mis-categorization is at the *frequency* layer, not the *content* layer.

---

### Category 10 — The 1% unit_price ramp and other ramp mechanisms

| File | Line(s) | Mechanism | Trigger | Shape produced | Drivers | Path-aware? | Severity |
|---|---|---|---|---|---|---|---|
| **orchestrator.py** | **1176-1258** | **1% unit_price ramp (Phase 8)** | **Post-cascade** | **GENERIC LINEAR (1.01^(q-1))** | **Unit Price ONLY** | **NO** | **CRITICAL** |
| post_intake_contracts/runner.py | 1842-2084 | `_estimate_stage_ramp_contract_with_gpt()` | Pre-convergence | PATH-AWARE (s-curve, turnaround, glidepath, capacity expansion, convergence decay — GPT chooses per planning_mode + stage_family + distress) | Designs `quarter_ramp_grid` per-quarter revenue/utilization/cost/profitability bounds | YES | LOW (correct) |
| quarter_grid.py | 870-942 | stage_ramp_contract loading and policy | Before quarter-grid planning | PATH-AWARE (per-Q1–Q20 bounds) | All drivers (capacity, unit price, utilization, COGS%, Marketing%, R&D%, G&A%, Lease%, ni_floor) | YES | LOW (correct) |
| quarter_grid.py | 1096-1105 | `_quarter_grid_stage_maturity_row()` | Per quarter during grid planning | PATH-AWARE (per-quarter row lookup) | Cost % caps, utilization caps, ni_floor | YES | LOW (correct) |
| quarter_grid.py | 2362-2507 | `_enforce_composite_revenue_ramp_inside_envelopes()` | After GPT grid response | PATH-AWARE (enforces stage_ramp_contract bounds, priority Utilization→Capacity→Unit Price) | Repairs revenue path | YES | LOW (correct) |

**Key finding:** Path-aware ramp infrastructure already exists end-to-end in `stage_ramp_contract.quarter_ramp_grid` and is enforced inside the convergence loop. The 1% unit_price ramp is a Phase 8 patch that runs *after* the cascade and *outside* the enforcement loop. It modifies only Unit Price (one of three revenue formula factors: Revenue = Capacity × Unit Price × Utilization), uses a hardcoded 1.01-per-quarter formula, and does not consult `stage_ramp_contract` for the right shape. If the ramp creates a new conflict (e.g., Utilization at cap, total revenue overshoots `revenue_qoq_max`), `_enforce_composite_revenue_ramp_inside_envelopes()` does not re-run.

**Verdict:** The Phase 8 ramp is a band-aid. The path-aware mechanism (stage_ramp_contract) is the doctrinally-correct primary trajectory and should be the only revenue trajectory mechanism. The 1% ramp should either be deleted (let stage_ramp_contract own all trajectory shaping post-cascade too) or refactored to consult stage_ramp_contract and apply across all three revenue factors with re-validation.

**Q: Is the 1% ramp the *only* revenue trajectory for Sunny today?** No — `stage_ramp_contract.quarter_ramp_grid` is primary and runs first. The 1% ramp is a reactive patch applied when the solver flattens unit_price post-cascade, in violation of the contract.

**Q: Which ramp shapes EXIST in code?** All six doctrine shapes are produced inside `stage_ramp_contract.quarter_ramp_grid`. None are produced outside it.

**Q: Which ramp shapes are MISSING?** None are missing from the code — they are missing from the *post-cascade application path*. The 1% ramp ignores them.

---

## 4. Recommended Phase B–E ordering

Findings are interlocked. Some fixes block others.

### Phase B — Path-shaped solver writes

**Why first:** Cat 2 + Cat 10 are the same root issue: the solver writes flat values and then a band-aid patches one driver. Until the solver is path-aware, every Cat 6 cascade tier and every Cat 7 metric remediation is constrained by the underlying flat-write contract.

**Scope:**
1. Replace `_build_apply_lever_callable()` (orchestrator.py:103-131) with a path-aware writer that consults `stage_ramp_contract.quarter_ramp_grid` for the appropriate shape per driver.
2. Delete the 1% unit_price ramp (orchestrator.py:1176-1258) once path-aware writes cover Unit Price.
3. Re-run `_enforce_composite_revenue_ramp_inside_envelopes()` after every solver lever movement (not just before).
4. Add a per-driver "shape kind" registry: rent → flat; payroll/COGS/marketing/G&A/SG&A → glidepath; capacity → capacity_expansion; unit_price → industry_convergence_decay or s_curve; utilization → s_curve.

**Blocker for:** Phase C, D, E (everything else assumes the underlying writes are correct).

### Phase C — Realism metric metadata + issue-aware cascade

**Why second:** Cat 6 cascade tiers are progressive-loosen because Cat 7 metrics carry no remediation metadata. Add metadata first; refactor cascade tiers second.

**Scope:**
1. Schema migration: add `issue_family`, `remediation_family`, `primary_levers`, `secondary_levers`, `stage_sensitivity`, `deadline_quarter` columns to `post_intake_finalize_realism_check_lookup`.
2. Populate all 27 rows. Move the partial mapping in validator.py:288-293 into lookup.py rows.
3. Refactor adaptation_cascade.py from 7 progressive-loosen tiers into N issue-aware families: revenue_achievability, margin_compression, payroll_ratio_excess, working_capital_inversion, leverage_excess, cash_runway, formula_consistency.
4. Tier 7 (generic_fallback_no_calibration) — replace `success=True with residuals` with explicit "manual review needed" terminal OR (depending on user decision) hard-fail and route to Cat 1 doctrine cause #6.
5. Tier 3 (target_tolerance_widened) — narrow to the specific metric in `final_hard_fails` instead of all metrics.

**Blocker for:** Phase D's stage waiver removal (Cat 4 fixes need adaptation routing in place).

### Phase D — Stage waivers, schedule warnings, industry profile unification

**Scope:**
1. Eliminate stage-based waivers at post_intake_mapping.py:3111-3132. Either:
   - (a) Mode policy applies uniformly (waivers deleted), or
   - (b) Floor *values* vary by stage in planning_mode_policy SQL table (encode stage-specificity in data, not in code branches).
   *Decision required from user — see open questions.*
2. Wire schedule_sanity warnings (Cat 5: wage, productivity, debt rate, capex/PPE) into the Phase C cascade families. Pick one of: route-to-adaptation, stage-tolerate-with-reason, or accept-with-documented-exception.
3. Add stage-aware payroll and leverage envelopes (cohort_band_resolver.py).
4. Unify cash buffer into the industry profile: NAICS-keyed working_capital_buffer metric replacing the hardcoded DEFAULT_CASH_POLICY_ROWS table.
5. Remove the 5 `business_stage`-as-hint usages (Cat 4: financials_year1.py:1372-1374, 1460-1467; post_intake_headcount/schedule.py:2027-2029).

### Phase E — GPT call budget reduction

**Why last:** The Phase 3 consultants are correctly categorized but over-frequent. Once Cat 2 + Cat 7 are fixed, Python's deterministic proposal is much stronger and GPT critique becomes batch-able.

**Scope:**
1. Convert each consultant from per-item loop to per-batch critique:
   - Band shaping: 1 call reviewing all proposed lever bands at once.
   - Target shaping: 1 call reviewing all metric targets at once.
   - Conflict adjudication: 1 call reviewing all conflicts at once.
2. Add the doctrine cap as a hard runtime check: if a planning run issues > 4 GPT calls, raise (Cat 1 doctrine cause #6 — architectural violation).
3. Optional 4th call slot: reserve for a final realism critique on the assembled plan.

---

## 5. Open questions (doctrine clarifications needed before code can change)

These contradictions cannot be fixed without a decision from the user.

### Q1 — Stage waivers: which fix?
post_intake_mapping.py:3111-3132 contains 5 waivers that skip mode-policy floors when family ∈ {startup, early} OR distress context. Two viable replacements:
- **(a)** Mode floors apply uniformly to all stages. Eliminate waivers entirely. A startup in `rebalance` mode must hit Q1 ≥ 0.
- **(b)** Mode floors vary *by value* per stage in the planning_mode_policy SQL table. A startup in `rebalance` may have `profitability_floor_q1_q4 = -0.30`; a mature business in same mode has `profitability_floor_q1_q4 = 0.00`.

(b) preserves current semantic behavior in a doctrine-aligned way. (a) is stricter.

### Q2 — Tier 1 (gpt_band_relaxation): keep or remove?
Tier 1 is a defensive no-op when the R2 buffer rule is enforced upstream. Should it be removed entirely? Keeping it as belt-and-suspenders is fine but adds noise to the cascade.

### Q3 — Deadline_quarter scope
Doctrine specifies Q5 / Q11 deadlines for EBITDA. Do other metrics also have deadline_quarters? Examples:
- Working capital (AR days, AP days, inventory days) — when must they be in band?
- Leverage (D/E, D/A) — when must steady-state apply?
- Payroll ratio — when must mature ratio apply?
Or is `deadline_quarter` only meaningful for profitability metrics?

### Q4 — GPT budget allocation
Doctrine says max 4 calls per run. With 3 consultants × per-item loops collapsing into 3 per-batch calls, that leaves 1 free slot. Allocation options:
- (a) Reserve for a final realism critique on the assembled plan.
- (b) Reserve as overflow for a deep-dive on the most uncertain conflict.
- (c) Cap at 3 (one per consultant) and remove the slack.

### Q5 — Tier 7 success-with-residuals
Today Tier 7 declares `success=True` even when residuals remain. Doctrine says hard_fail = adaptation required before client output. Three options:
- (a) Tier 7 raises a "manual review needed" terminal (expand the doctrine's 6 terminal causes to add a 7th, or fold into cause #6).
- (b) Tier 7 succeeds only when residuals are below a documented "accept-with-exception" threshold; raise otherwise.
- (c) Keep current behavior with explicit doctrine-level acceptance that `mode=turnaround + stage=operational + 2x widening` is "always acceptable as last resort."

### Q6 — stage_ramp_revenue_bridge_failed terminal
fail_fast/post_intake_fail_fast/fail_fast.py:650 raises `RuntimeError("quarter_grid_stage_ramp_revenue_bridge_failed: …")` when `not fail_fast_enabled`. Is this:
- (a) FINMO formula integrity failure (terminal cause #4) — keep as terminal,
- (b) An adaptation-routable issue — route to revenue_achievability family in Phase C cascade refactor.

### Q7 — Schedule_sanity warnings classification
schedule_sanity.py emits 4 warn-only checks (wage, productivity, debt rate, capex/PPE). For each, which doctrine path:
- Route to adaptation (which family?)
- Stage-tolerate with reason (under which stages?)
- Accept-with-documented-exception (with what reason template?)

### Q8 — sanity_assertion residual_violations escalation
post_intake_solver/sanity_assertion.py:96-219 returns dict with violations; current callers do not raise. Phase 2 spec said callers should raise on residual_violations. Confirm: is the policy "any residual violation = adaptation required" or "residual violations are warnings"?

### Q9 — Should cash buffer leave the policy table?
Today cash buffer is policy-driven (cash_strategy × debt_position). Industry profile would make it benchmark-driven (NAICS-keyed working_capital_buffer). Is that the intent, or is cash buffer deliberately policy-only? If both: how do they compose?

### Q10 — Hint-usage of business_stage in non-policy sites
financials_year1.py:1372-1374 adds business_stage to GPT context_signals for narrative. financials_year1.py:1460-1467 soft-triggers r_and_d_setup_check based on stage. post_intake_headcount/schedule.py:2027-2029 passes stage/mode to GPT headcount consultant. Are these acceptable hint usages, or must every consumption be deterministic policy application?

---

## 6. Discipline notes

- **No code changes were made during this audit.** Pure inspection.
- **No "fixes while there"** — typos and obvious bugs are documented (none found severe enough to warrant separate flag).
- **Dead code** (e.g., legacy convergence runner directory, deprecated finmo_bridge net debt placeholder) is documented in row form, not deleted.
- All cited line numbers reflect the working tree at commit `d95fb1a` (Phase 8 complete; `intake-stable` branch).
