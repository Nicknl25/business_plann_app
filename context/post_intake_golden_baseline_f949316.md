# Post-Intake Golden Baseline: f949316

This file freezes the current standard for post-intake behavior.

The historical passing commit is:

- Commit: `f949316`
- Branch: `intake-stable`
- Tag: `post-intake-golden-payroll-debt-depr-tables`
- Commit message: `payroll,, debt, and depreciation schedules as well as tables appear to have work`

The active SQL audit snapshot was refreshed on May 5, 2026 after a full sequence-controller/context-model E2E pass.

- Source commit label: `working-tree-sequence-context-controller`
- Active SQL baseline name: `post_intake_golden_f949316`
- Runtime rule: client runs validate operational lookup tables through initialize/finalize gates, not the golden snapshot table.
- Admin rule: `scripts/post_intake_golden_preflight.py` compares the current operational lookup tables to `post_intake_lookup_table_snapshot`.

## Why This Exists

This baseline is the reference point for future fixes.

If a later E2E fails, do not patch around the failure. Fix the app back toward this architecture:

- Python owns deterministic structure through lookup tables and table-backed functions.
- GPT owns judgment inside table-defined contracts only.
- FINMO calculates only from `model_input_json`.
- Payroll, debt, and depreciation schedules must be used or fail fast.
- Mapping, contracts, process sequence, GPT context, cash policy, and headcount policy must come from SQL lookup tables.

## Golden Run

The run that established this baseline:

- Source draft id: `af5c22e5c5e34a01b956a76d83e9e044`
- Final draft id: `c080282fe20f403db7a5adc8399cfdd6`
- Business: `ExpressLogix Shipping Services`
- Planning mode: `rebalance`
- Cash strategy: `balanced`
- Final planning stage: `cash_pass_completed`
- Final planning status: `completed`
- Controller status: `all_cleared`
- Remaining issue count: `0`
- Runtime: about `170632 ms`

The sequence-controller run that refreshed the active SQL snapshot:

- Source draft id: `d087c44e0aa544eea869d7ab3f7a4f66`
- Final draft id: `442e0577341a4968aaabac409196c867`
- Business: `NexGen Software Solutions Inc.`
- Final planning stage: `cash_pass_completed`
- Final planning status: `completed`
- Controller status: `all_cleared`
- Remaining issue count: `0`
- Runtime: about `365098 ms`
- Workbook: `C:\dev\Cilient Plans\NexGen Software Solutions Inc. -- 05-05-2026 15-43-18.xlsx`
- Active sequence rows: `69`
- Targeted process smoke: `69` addressable steps completed through `run_targeted_process_step(...)`

Latest verified sequence-controller pass on a different industry (retail superstore):

- Source draft id: `b6134325d26842228cad0430aa9649b3`
- Final draft id: `ec8b23cffeeb4d7c8df3e7ae9a324ca0`
- Business: `ValueMart Superstores`
- Final planning status: `completed`
- Controller status: `all_cleared`
- Remaining issue count: `0`
- Runtime: about `132762 ms`
- Workbook: `C:\dev\Cilient Plans\ValueMart Superstores -- 05-05-2026 19-40-28.xlsx`

Class-level fixes applied during this verification cycle:

- `_table_backed_formula_envelope_feasibility_errors` (post_intake_issues/runner.py) now relaxes capacity/utilization min/max in place to admit intake-derived revenue targets when the static stage-cap envelope is over-constraining (e.g., small-business intakes where the envelope min was pinned above the intake target). Hard-fail only fires if relaxation cannot reconcile. This restores the universal-business invariant in the Golden Rule.
- Convergence non-productive cycle bailout in `post_intake_convergence/runner.py` is no longer gated on `_convergence_test_mode_enabled()`. Production runs now fail-fast on stalled progress instead of burning through `_UNIFIED_CONVERGENCE_MAX_CYCLES` when the solver is oscillating. This protects the OpenAI budget on structurally non-converging intakes.

Key observed outputs:

- `payroll_headcount_present = true`
- `payroll_quarter_total_count = 20`
- `payroll_pct_min = 0.2402`
- `payroll_pct_max = 0.317`
- Q11-Q20 revenue was not flat:
  - `48262491`
  - `48701241`
  - `49139991`
  - `49578741`
  - `50017490`
  - `50456240`
  - `50894990`
  - `51333740`
  - `51772490`
  - `52211240`

## SQL Snapshot Table

The frozen lookup-table state is stored in SQL:

- Table: `post_intake_lookup_table_snapshot`
- Baseline name: `post_intake_golden_f949316`

The snapshot table stores one semantic hash per required lookup table:

- `post_intak_mapping_lookup`
- `post_intake_cash_policy_lookup`
- `post_intake_gpt_contract_lookup`
- `post_intake_gpt_context_lookup`
- `post_intake_headcount_policy_lookup`
- `post_intake_process_sequence_lookup`
- `post_intake_process_context_lookup`

Current refreshed snapshot counts:

- `post_intak_mapping_lookup`: `26`
- `post_intake_cash_policy_lookup`: `9`
- `post_intake_gpt_contract_lookup`: `157`
- `post_intake_gpt_context_lookup`: `98`
- `post_intake_headcount_policy_lookup`: `1`
- `post_intake_process_sequence_lookup`: `69`
- `post_intake_process_context_lookup`: `335`

The snapshot intentionally ignores volatile columns:

- `id`
- `created_at`
- `updated_at`

That means the baseline checks semantic table content, not incidental row metadata.

## Regression Commands

Freeze or refresh the baseline table intentionally:

```powershell
.\.venv\Scripts\python.exe scripts\freeze_post_intake_golden_baseline.py --baseline-name post_intake_golden_f949316 --source-commit working-tree-sequence-context-controller
```

Run the Golden Rule preflight:

```powershell
.\.venv\Scripts\python.exe scripts\post_intake_golden_preflight.py
```

The preflight must fail if:

- The SQL lookup snapshot is missing.
- Any frozen lookup table row count changes.
- Any frozen lookup table semantic hash changes.
- Golden Rule structural checks fail.
- Process sequence stops declaring required lookup tables.
- Required contracts/context rows are missing.
- Post-intake mapping is not SQL-backed.

## Fix Rule

When a future run fails:

1. Compare the failure to this baseline.
2. If the failure comes from legacy code, delete or convert the legacy path.
3. If a deterministic rule is missing, add it to a lookup table, then access it through a lookup function.
4. If GPT needs to decide, define the contract in `post_intake_gpt_contract_lookup` and prompt from the table.
5. Do not bypass payroll, debt, or depreciation schedules.
6. Do not patch one run in a way that violates this baseline.

Runtime initialize/finalize validation must not query or depend on `post_intake_lookup_table_snapshot`. The snapshot is for preflight, deploy, and admin audit only. Normal post-intake execution must be governed by `post_intake_process_sequence_lookup` and `post_intake_process_context_lookup`, with every step resolving required context before execution and writing outputs only to its domain storage.

This is the bar.
