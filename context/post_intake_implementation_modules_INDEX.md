# Post-Intake Implementation Modules — INDEX

This index breaks the master diagnostic ([context/post_intake_master_diagnostic_2026-05-05.md](post_intake_master_diagnostic_2026-05-05.md)) into 6 implementation modules. Scope: post-intake only.

Each module is self-contained — a fresh session can pick up any module by reading just its file plus the relevant master-diagnostic parts referenced inside.

## Module status

| # | Module | File | Status | Depends on |
|---|---|---|---|---|
| 1 | Industry Baseline Resolver + Producer-Side Substitution | [post_intake_module_1_industry_baseline_resolver.md](post_intake_module_1_industry_baseline_resolver.md) | in_progress (impl complete; full E2E verification deferred) | none (foundation) |
| 2 | Convergence Determinism + NAICS-Tightened Stage Ramp | [post_intake_module_2_convergence_determinism.md](post_intake_module_2_convergence_determinism.md) | in_progress (Tasks 2.2/2.4/2.5/2.6 landed; 2.1/2.3/2.7/2.8 deferred) | M1 |
| 3 | GPT Contract NAICS Bounds + Finalize Realism Gate | [post_intake_module_3_finalize_realism_gate.md](post_intake_module_3_finalize_realism_gate.md) | completed (v1+v2+v3: 8 NAICS-bound contract rows, 28 realism check rows, 4 schedule sanity validators, 5 metrics promoted to hard_fail, 73/73 tests green) | M1 |
| 4 | Hardcoded Constants → Tables (cash policy, planning-mode, sequence-row columns) | [post_intake_module_4_table_migrations.md](post_intake_module_4_table_migrations.md) | completed (4 cash policy columns, 5 sequence-row columns, new planning_mode policy table, 7 legacy Python constants deleted, 90/90 tests green) | none (parallel-safe) |
| 5 | GPT Reductions (Python proposer + GPT critic for the nuanced calls; delete + short-circuit for the unambiguous ones) | [post_intake_module_5_gpt_reductions.md](post_intake_module_5_gpt_reductions.md) | completed (5.1 maintenance_capex deleted, 5.2 R&D NAICS-2 lookup, 5.3 balance_sheet_seed proposer+critic, 5.4 solver short-circuit verified, 5.5 cash_strategy_review proposer+critic [legacy retry loop removed], 5.6 verification proposer+critic, 23/23 tests green) | M1, M3 |
| 6 | Marketing Schedule Subsystem (SQL registration + workbook tab) | [post_intake_module_6_marketing_schedule.md](post_intake_module_6_marketing_schedule.md) | not_started | M1, M3 |

## Recommended landing order

```
M1 ─┬─> M2 ────┬─> M5 ──> M6
    │         │
    └─> M3 ───┘
M4 (parallel, independent)
```

M1 unblocks M2, M3, M5, M6. M4 can run any time. M5 and M6 both need M3's contract-bound machinery and M1's resolver.

## Per-module status values

- `not_started` — no work begun
- `in_progress` — at least one task checked off, exit criteria not yet met
- `verifying` — all tasks checked off, running the verification suite
- `completed` — exit criteria met, both regression E2Es still green
- `blocked: <reason>` — paused on an external dependency or unexpected finding

## Working a module

1. Open the module file.
2. Read the "Why this module" and "Dependencies" sections first.
3. Read the master-diagnostic parts referenced inside before touching code.
4. Work the task checklist top-to-bottom. Mark each `[ ]` → `[x]` as it completes.
5. When all tasks check off, run the "Verification" steps.
6. When exit criteria are met, update this index's Status column from `in_progress` → `completed` and commit both files.

## Cross-cutting invariants (apply to all 6 modules)

These are the Golden Rule preservations from master diagnostic Parts 8 and 9. Every module must respect them or the work is wrong:

1. **Drivers → Schedules → Mapping formulas → FINMO calc → Statements.** Never anything else, never anything around it.
2. **Stub 0 (Q0) is intake fact.** Never written, never normalized, never NAICS-substituted, never validated by the realism gate.
3. **No module writes statement rows directly.** All work lands as driver values in `model_input_json` and flows through the chain.
4. **Payroll schedule preservation.** Exact OEWS titles selected by GPT from the Python-built NAICS catalog; FTE-primary causality (FTE → capacity → revenue ↔ payroll); key-person wages from intake injected first.
5. **Debt schedule preservation.** `amortizing_remaining_balance` method; SBA-backed interest rate sourcing; declining principal; layered new borrowing.
6. **Mapping table is authority.** Formulas selected by SQL, executed by Python from the deterministic registry. Never invent a formula.
7. **Sequence controller authority.** Every step runs through `PostIntakeSequenceController`; declared context inputs and produced outputs in `post_intake_process_context_lookup`; respect `final_for_stage` output finality.
8. **The numeric solver stays.** Strengthens, doesn't weaken. Module 5's direct-fit short-circuit gives the solver more work, not less.

## Regression baseline

Two E2Es passed cleanly on 2026-05-05 and are the regression baseline:

- **NexGen Software Solutions Inc.** (NAICS 51): final draft `442e0577341a4968aaabac409196c867`, `all_cleared`, `remaining_issue_count = 0`, runtime ~365s
- **ValueMart Superstores** (NAICS 455211): final draft `ec8b23cffeeb4d7c8df3e7ae9a324ca0`, `all_cleared`, `remaining_issue_count = 0`, runtime ~133s

Every module's verification step requires both E2Es still pass with `all_cleared`. If either regresses, the module is not done.

## Contact between modules and the master diagnostic

The master diagnostic is the *reference architecture*. The modules are the *implementation playbooks*. When the diagnostic and a module disagree, the master diagnostic wins — update the module to match. When new findings emerge during implementation, append them to the master diagnostic and reflect them in the module.

When all 6 modules are complete, the realism layer described in master-diagnostic Parts 1–13 is fully in place. Phase 10+ (the optional "Python proposes, GPT repairs" architecture flip from master-diagnostic Part 7.3) is a separate decision to be made with empirical data from post-M6 runs.
