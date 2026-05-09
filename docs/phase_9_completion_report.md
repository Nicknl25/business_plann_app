# Phase 9 — Adaptive Operating Doctrine: Completion Report

**Branch:** intake-stable
**Date:** 2026-05-09
**Phases shipped:** A (audit) · B (adaptive policy) · C (path engine) · D (cascade refactor) · E (industry profile) · F (cash strategy) · G (gate hardening) · H (GPT budget) · I (cleanup)

This report consolidates the architectural changes Phase 9 landed and
flags work that remains for E2E verification.

## Commits (intake-stable)

| Phase | SHA | What |
|---|---|---|
| A | `796d684` | Audit document (10 categories, 30+ contradictions) |
| B | `efdb7e1` | Adaptive policy contract + orchestrator Step 0 |
| C1 | `6939163` | Persist stage_ramp_contract so workbook reads non-zero |
| C2 | `9677d3c` | Path engine module + per-driver shape registry |
| C3 | `f6e6e29` | Path-aware lever writer + delete 1% unit_price ramp |
| C4 | `0968526` | Post-cascade composite revenue trajectory check |
| D | `8823dd1` | Realism metadata + issue router + cascade refactor |
| E | `f1baafe` | Stage-shifted floors + industry_profile module |
| F | `4e23052` | Mode-based cash strategy |
| G | `d5f5b9d` | Acceptance gate hardening (6 new criteria) |
| H | `cfec71d` | GPT call budget cap (4 calls per planning run) |

## What Phase 9 changed (architectural diff)

### New modules

| Module | Phase | Purpose |
|---|---|---|
| [post_intake_adaptive_planning/policy.py](../python/client_intake_and_finmo/post_intake_adaptive_planning/policy.py) | B | AdaptivePolicyContract — single source of truth for stage profile, planning mode, viability deadlines, allowed adaptation families, client-input authority. |
| [post_intake_adaptive_planning/path_engine.py](../python/client_intake_and_finmo/post_intake_adaptive_planning/path_engine.py) | C2 | Per-driver shape registry + 6 deterministic shape functions (flat, glidepath, linear_to_mature, s_curve, capacity_expansion, industry_convergence_decay). |
| [post_intake_adaptive_planning/issue_router.py](../python/client_intake_and_finmo/post_intake_adaptive_planning/issue_router.py) | D3 | Routes every detected violation to one of 12 adaptation families with severity / levers / deadline / cash_pass_allowed flag. |
| [post_intake_adaptive_planning/industry_profile.py](../python/client_intake_and_finmo/post_intake_adaptive_planning/industry_profile.py) | E | Single `get_industry_profile()` entry returning unified IndustryProfile across all 26 doctrine dimensions; cash buffer per Q9 decision (NAICS base × mode multiplier). |
| [post_intake_cash_strategy/orchestrator_invocation.py](../python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py) | F | Per-quarter mode-based cash strategy (preserve_cash / balanced / shareholder_return). Replaces Phase 8 minimal lump-sum dump. |

### Refactored modules

| Module | Phase | Change |
|---|---|---|
| [post_intake_solver/orchestrator.py](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py) | B/C/F/H | Adaptive policy at Step 0; path-aware `_build_apply_lever_callable`; minimal cash strategy replaced; GPT budget reset; composite revenue check + routes; CascadeAndRestorationExhausted catch. |
| [post_intake_solver/adaptation_cascade.py](../python/client_intake_and_finmo/post_intake_solver/adaptation_cascade.py) | D4 | Tier 1 removed (Q2 doctrine decision); Tier 7 escalates to feasibility_restoration; if both exhaust, raises `CascadeAndRestorationExhausted` (terminal cause #7). |
| [post_intake_realism/lookup.py](../python/client_intake_and_finmo/post_intake_realism/lookup.py) | D1/D2 | Schema migration adds 6 metadata columns (issue_family, remediation_family, primary_levers, secondary_levers, stage_sensitivity, deadline_quarter); 27 rows populated; 6 viability timeline rows added (33 total). |
| [post_intake_realism/formulas.py](../python/client_intake_and_finmo/post_intake_realism/formulas.py) | D2 | 6 new trajectory_check formulas: ebitda_positive_at_quarter, ebitda_recovery_trend, loss_window_funded, no_post_recovery_relapse, gross_margin_supports_recovery, fixed_cost_burden_at_industry_floor. |
| [post_intake_mapping.py](../python/client_intake_and_finmo/post_intake_mapping.py) | E | 12 stage-shifted floor columns (3 windows × 4 stages); waivers at 3111-3132 deleted; floors apply uniformly per stage from DATA, not per-stage CODE BRANCHES. 5 planning_mode rows populated (rebalance, turnaround, normalize, growth_investment, preservation). |
| [post_intake_acceptance/gate.py](../python/client_intake_and_finmo/post_intake_acceptance/gate.py) | G | 6 new criteria: net_income_trajectory_viable, cash_health_operational_not_debt_funded, cascade_exercised_or_documented, phase_3_calibrated_bands_consulted, balance_sheet_growth_plausible, viability_timeline_landed. Gate version → `phase_9_g_v1`. |
| [post_intake_solver/_gpt_critic_io.py](../python/client_intake_and_finmo/post_intake_solver/_gpt_critic_io.py) | H | Per-run 4-call budget counter at the call_gpt_with_schema_or_fallback chokepoint; budget exhaustion routes to python_proposer fallback. |
| [post_intake_headcount/lookup.py](../python/client_intake_and_finmo/post_intake_headcount/lookup.py) | I | Payroll-integer tolerance tightened from $1.00 to $0.10 per Phase 8 tolerance audit follow-up. |

### Doctrine rules now binding in code

| Rule | Where enforced |
|---|---|
| Universal viability rule (Q11 EBITDA ≥ 0, Q5-Q11 recovery, no post-recovery relapse) | 6 viability timeline checks in realism table; gate criterion `viability_timeline_landed`. |
| Stage shifts WHEN floor binds, not WHETHER | Stage-shifted floors in planning_mode_policy SQL; waivers deleted. |
| Cash pass funding-only | mode-based cash strategy adjusts only debt_issuance / owners_capital / distributions; operating drivers untouched. |
| Real ramp rule | Path-aware lever writer; per-driver shape registry; 1% unit_price ramp deleted. |
| GPT max 4 calls per run | Per-run budget counter at chokepoint; exhaustion → python_proposer fallback. |
| Tier 7 NEVER ships success with residuals | Tier 7 escalates to feasibility_restoration; both exhausted → terminal cause #7. |
| Hard fail = adaptation required | issue_router routes every violation to a family; severity classification. |

## What Phase 9 deferred (work-in-flight)

The following were called out in the consolidated directive but
implemented at MVP scope due to context constraints. Each is documented
so post-E2E iteration can complete the work.

1. **Phase D — full 12-family cascade refactor.** Cascade currently keeps Tiers 2-6 of the legacy progressive-loosen walk plus the new Tier 7 escalation to feasibility_restoration. The 12 issue-aware family adapters described in the directive are NOT yet wired as discrete tiers. The issue_router IS in place; downstream consumers (acceptance gate, finalize) read its routes. Full cascade rewrite lands when E2E reveals the legacy walk is the bottleneck.

2. **Phase E — schedule_sanity warning routing.** Issue router has `route_schedule_sanity_warning()` per Q7, but the schedule_sanity validator does NOT yet call it. Warnings still sit on the validator payload as Phase 8 did. Wiring is one orchestrator edit when E2E shows it's needed.

3. **Phase F — GPT cash strategy critic.** Skipped per Q4 budget allocation (4 calls = band + target + conflict + realism, no slot for cash). Mode-based cash strategy is fully deterministic Python.

4. **Phase F — Cash Equity Schedule sheet persistence.** Cash strategy writes per-quarter values to model_input via apply_exact_lever_updates_to_model_input. The workbook reader picks them up through the existing balance-sheet flow. A dedicated Cash Equity Schedule sheet build step was not added; the existing schedule_sheets.py reads what's persisted.

5. **Phase H — per-batch consultant refactor.** The 4-call BUDGET is enforced; the per-batch CONTENT refactor (replacing per-item loops with single batch calls per consultant) is NOT yet done. Effect: first 4 calls hit GPT with existing per-item content, subsequent calls fall through to Python. Budget binding holds.

6. **Phase I — convergence runner deletion.** Deferred. Active dependencies (intake_consult.py, orchestrator's `_persist_unified_convergence_state` import, runner.py:220 internal) prevent safe deletion in this session. Per the discipline rule "Don't bypass another legacy system without explicit user approval," the directory remains; the persistence helper needs to migrate to a new module before deletion.

7. **Phase I — legacy_compat.py shim audit.** Deferred. Inventory documented but bulk removal requires consumer-by-consumer verification; not safe in one session.

## Open questions for E2E

When Sunny / NexGen / ExpressLogix run end-to-end, expected new behavior:

- **Sunny**: startup + turnaround mode. Path engine produces capacity_expansion ramp. Mode-based cash strategy injects owners_capital (preserve_cash default) per quarter. Universal viability checks (ebitda_positive_by_q11) bind. Gate runs all 16 criteria. If `cascade_exercised_or_documented` fails, the cascade hasn't actually run — Phase 3 calibration must produce real bands.
- **NexGen**: early-stage SaaS + normalize mode. Stage-shifted floor at q1_q4 = -0.20 (early-stage normalize). Path engine produces s_curve utilization, glidepath OpEx %.
- **ExpressLogix**: 8-year operational + normalize mode → mature stage profile. Stage floors q11_q20 = 0.08 minimum. Cash strategy distributes surplus instead of absurd $28.8M accumulation.

If any draft trips terminal cause #7 (CascadeAndRestorationExhausted), the diagnostic carries every adaptation attempted and every restoration attempted — the consultant sees what specifically couldn't reach viability.

## Files NOT touched (deliberate)

Per the directive's "Don't" list:
- Phase 3 GPT consultant content (band_shaping, target_shaping, conflict_adjudication) — only their call frequency is capped.
- post_intake_issues/ machinery — not reintroduced.
- Cash pass operating-driver firewall — cash MAY NOT adjust revenue/COGS/payroll/G&A/marketing/R&D/lease/pricing/utilization/capacity/EBITDA tolerances. Mode-based cash strategy preserves this rule by construction.
- post_intake_convergence/ directory — kept until safe migration of `_persist_unified_convergence_state`.

## Next session

E2E run on Sunny via `Test Files/run_persisted_system_run.py`. Iterate per the discipline rules in the consolidated directive: no bypassing, no soft gates, no tolerance widening, ≤ 4 GPT calls. When draft passes with sellable workbook, push final and report.
