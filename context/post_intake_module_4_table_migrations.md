# Module 4: Hardcoded Constants → Tables

**Status:** not_started
**Scope:** post-intake only.
**Depends on:** none. Parallel-safe with M1, M2, M3.
**Unblocks:** none structurally. Removes stitching that future modules would otherwise inherit.

## Why this module

Several deterministic policy values live as Python module constants today instead of in SQL tables. Per the Golden Rule ("if something is consistent, structural, repeatable, or contract-like, it belongs in a lookup table or a table-backed function"), these should move. This module does no behavior change beyond making the values table-driven so operators and audits can see them.

The four migration targets:

1. **Cash policy preferred-ratio constants** (master-diagnostic P10): `_CASH_STRATEGY_PREFERRED_DEBT_RATIO = 0.40` and `_CASH_STRATEGY_PREFERRED_EQUITY_RATIO = 0.60` in `post_intake_cash/runner.py:79-80`. They shape capital-structure soft guidance per quarter and currently leak through the planning/validation envelope.
2. **Convergence guard constants** (master-diagnostic P5, P13): `_CONVERGENCE_NON_PRODUCTIVE_CYCLE_LIMIT = 3`, `_CYCLE_DEADLINE_GUARD_SECONDS = 8.0`, `_PLANNER_GPT_MAX_SECONDS = 150.0`, `_VERIFICATION_GPT_MAX_SECONDS = 45.0` in `post_intake_convergence/runner.py:36-46`. (Note: M2 also addresses these. If M2 lands first, M4's part is already done; just verify.)
3. **Planning-mode policy table** (master-diagnostic P14): `planning_mode` ("rebalance", "turnaround", "normalize") flows into prompts as text but doesn't numerically constrain the convergence solver envelope. The `stage_planning_ramp_policy()` function has inline `if planning_mode ==` chains that should move to a lookup.
4. **Maintenance-capex hardcoded prompt prose** (master-diagnostic P9): "must be at least 2 and no more than 15" in `post_intake_contracts/runner.py:1100`. Move to the contract row's `min_value`/`max_value` columns.

**Master-diagnostic references:**
- Part 3 §P5 (convergence guards), P9 (maintenance capex), P10 (cash policy ratios), P13 (sequence row columns), P14 (planning-mode policy)
- Part 5 Phase 5, Phase 7
- Part 11.4 (cash hardcoded constants confirmed via direct read)

## Dependencies

None. Parallel-safe with M1 / M2 / M3.

**Coordination note:** Tasks 4.1 (convergence guards) overlap with M2 Task 2.1. Whichever module lands first does the migration; the other module verifies the columns exist and uses them.

## Pre-flight

- [ ] Both regression E2Es passing on the current main branch baseline.
- [ ] Read master-diagnostic Parts 3 (P5/P9/P10/P13/P14), 5 (Phase 5, 7), 11.4.
- [ ] Read `post_intake_cash/runner.py:77-80` and the envelope-build helpers `build_cash_planning_envelope` and `build_cash_validation_envelope` (they consume the preferred-ratio constants).
- [ ] Read `post_intake_mapping.py:stage_planning_ramp_policy` (line 2813) to see where the `if planning_mode ==` chains live.
- [ ] Read `post_intake_contracts/runner.py` around the maintenance_capex prompt build to see where the "2 to 15" bound lives.

## Task 4.1 — Cash policy preferred-ratio columns

- [ ] Add columns to `post_intake_cash_policy_lookup` via DDL in `post_intake_mapping.py:_ensure_cash_policy_lookup_table`:
  - `preferred_debt_to_assets_ratio DECIMAL(10,4) NOT NULL DEFAULT 0.40`
  - `preferred_equity_to_assets_ratio DECIMAL(10,4) NOT NULL DEFAULT 0.60`
  - `preferred_distribution_yield_target DECIMAL(10,4) NULL` (optional, may be NULL initially)
  - `preferred_min_cash_runway_months DECIMAL(10,4) NULL` (optional)
- [ ] Migration is additive; existing rows get the default values (0.40 / 0.60) immediately.
- [ ] Optionally diverge values per (cash_strategy × debt_position) cell — e.g., `preserve_cash` may want a higher equity ratio target; `shareholder_return` may want lower. Initial pass: same defaults across cells; diverge in a follow-up after observing real runs.
- [ ] Update the lookup function `post_intake_cash_policy_for(...)` to expose the new columns in the returned policy dict.

## Task 4.2 — Wire cash runner to read the policy columns

- [ ] Edit `python/client_intake_and_finmo/post_intake_cash/runner.py`. Replace `_CASH_STRATEGY_PREFERRED_DEBT_RATIO = 0.40` and `_CASH_STRATEGY_PREFERRED_EQUITY_RATIO = 0.60` constants with reads from the resolved cash policy row.
- [ ] Specifically: in `_cash_strategy_planning_violation_envelope` (line 923) and `_cash_strategy_validation_violation_envelope` (line 942), pass `preferred_debt_ratio` and `preferred_equity_ratio` from the policy row into `build_cash_planning_envelope` and `build_cash_validation_envelope`.
- [ ] Confirm the envelope builders receive these as parameters today (they do — see runner.py:935-937). The change is the source of the values, not the function signature.
- [ ] Keep `_CASH_STRATEGY_BUFFER_MONTHS = 1.0` as a fallback constant for when the policy row's `cash_floor_months` is unexpectedly null. Add a comment explaining it's a fallback only; the policy row is authority.

## Task 4.3 — Convergence guard columns (coordinate with M2)

If M2 has already landed Task 2.1, skip this. Otherwise:

- [ ] Add columns to `post_intake_process_sequence_lookup`:
  - `total_phase_budget_seconds DECIMAL(10,2) NULL`
  - `non_productive_cycle_limit INT NULL`
  - `cycle_deadline_guard_seconds DECIMAL(10,2) NULL`
  - `planner_gpt_max_seconds DECIMAL(10,2) NULL`
  - `verification_gpt_max_seconds DECIMAL(10,2) NULL`
- [ ] Populate the `unified_convergence_decision` row's new columns with current constant values (see M2 Task 2.1 for suggested values).
- [ ] Replace the module constants in `post_intake_convergence/runner.py:36-46` with reads from the sequence row via `_sequence_setting(...)`.

## Task 4.4 — Build the planning-mode policy table

- [ ] Create new SQL table `post_intake_planning_mode_policy_lookup`. Columns:
  ```
  id BIGINT UNSIGNED PRIMARY KEY
  planning_mode VARCHAR(64) NOT NULL UNIQUE     -- 'rebalance' | 'turnaround' | 'normalize'
  profitability_floor_q1_q4 DECIMAL(10,6) NULL  -- e.g. -0.10 for turnaround, 0.0 for normalize
  profitability_floor_q5_q10 DECIMAL(10,6) NULL
  profitability_floor_q11_q20 DECIMAL(10,6) NULL
  loss_allowed_latest_quarter INT NULL          -- e.g. 8 for early/turnaround
  tolerated_issue_codes_json LONGTEXT NULL      -- which issues this mode tolerates as non-blocking
  cycle_budget_multiplier DECIMAL(10,4) NOT NULL DEFAULT 1.0  -- turnaround can request 2.0x normal budget
  notes LONGTEXT NULL
  policy_status VARCHAR(32) NOT NULL DEFAULT 'active'
  created_at, updated_at
  ```
- [ ] Add table-ensure function. Add to `_post_intake_snapshot_source_tables()`. Add lookup function `post_intake_planning_mode_policy_for(planning_mode)`.
- [ ] Populate the three default rows with values that match today's hardcoded behavior in `stage_planning_ramp_policy`:
  - `rebalance`: floors 0.0 / 0.0 / 0.02, no loss-allowed window, multiplier 1.0
  - `turnaround`: floors -0.10 / 0.0 / 0.02, loss_allowed_latest_quarter = 8, tolerated_issue_codes includes mature_loss-related codes, multiplier 1.5 (or whatever today produces in practice)
  - `normalize`: floors 0.0 / 0.0 / 0.02, no loss window, multiplier 1.0

## Task 4.5 — Wire stage_planning_ramp_policy to read the planning-mode table

- [ ] Edit `python/client_intake_and_finmo/post_intake_mapping.py:stage_planning_ramp_policy` (line 2813).
- [ ] Replace the inline `if explicit_distress_context:` and `if family == "startup":` chains' planning-mode-derived values with a read from `post_intake_planning_mode_policy_for(planning_mode)`.
- [ ] The stage-family rules (the prose `stage_rules` list) stay as today — those are stage-family-specific, not planning-mode-specific. Only the numeric `validator_rules` values come from the new table.
- [ ] Convergence reads the policy via the existing pathway; no convergence-side change beyond consuming the new policy values.

## Task 4.6 — Move maintenance_capex bound from prose to contract row

- [ ] Find the `maintenance_capex_percent` row in `post_intake_gpt_contract_lookup`.
- [ ] Set its `min_value = 2` and `max_value = 15`.
- [ ] Edit `python/client_intake_and_finmo/post_intake_contracts/runner.py:1100` (and surrounding) to remove the hardcoded "must be at least 2 and no more than 15" prose. The prompt builder already renders `min_value`/`max_value` from the contract row when present (`post_intake_build_prompt_from_contract`); confirm this and rely on it.
- [ ] **Note:** M5 Task 5.1 will delete this GPT call entirely (replacing with NAICS resolver). M4's job is just the constant-to-table migration; M5 removes the call. If M5 lands first, M4 Task 4.6 is moot.

## Task 4.7 — Refresh the lookup snapshot (golden baseline)

- [ ] After all tasks land, run `scripts/freeze_post_intake_golden_baseline.py --baseline-name post_intake_golden_f949316 --source-commit <commit-sha>` to refresh the snapshot. The new columns and rows will change the row counts and content hashes for `post_intake_cash_policy_lookup`, `post_intake_process_sequence_lookup`, and the new `post_intake_planning_mode_policy_lookup`.
- [ ] Document the refresh in the commit message: "Snapshot refreshed after M4 table migration."

## Files Touched

- `python/client_intake_and_finmo/post_intake_mapping.py` (DDL for new columns + new table; lookup functions; `_post_intake_snapshot_source_tables`)
- `python/client_intake_and_finmo/post_intake_cash/runner.py` (replace cash preferred-ratio constants with policy reads)
- `python/client_intake_and_finmo/post_intake_convergence/runner.py` (replace guard constants with sequence-row reads — only if M2 hasn't done it)
- `python/client_intake_and_finmo/post_intake_contracts/runner.py` (remove maintenance_capex prose bound)
- The active rows of `post_intake_gpt_contract_lookup` (set min/max for maintenance_capex)

## Files NOT Touched

- Cash phase sequence semantics (the 11-phase order) — unchanged, still in `cash_phase_sequence_json`
- Debt schedule subsystem — unchanged
- Mapping table formula registry — unchanged
- Stage ramp validator behavior — unchanged in semantics; just sourcing values from the new table
- Stub 0 — unchanged
- FINMO calc — unchanged

## Verification

- [ ] All Task 4.x checkboxes complete
- [ ] NexGen Software E2E passes with `all_cleared`. Compare cash-pass behavior to pre-M4 baseline; the preferred-ratio values should produce identical capital-structure soft guidance because the table values match the old constants.
- [ ] ValueMart Superstores E2E passes.
- [ ] `scripts/post_intake_golden_preflight.py` runs cleanly after the snapshot refresh.
- [ ] Synthetic test: change `preferred_debt_to_assets_ratio` in the cash policy row from 0.40 to 0.50 for a test cell. Re-run an E2E. Confirm the capital-structure soft guidance reflects the new value (proves the column is actually being read at runtime, not a stale cache).
- [ ] Synthetic test: edit the planning-mode policy table for `turnaround` to set `loss_allowed_latest_quarter = 12`. Re-run a turnaround-mode E2E. Confirm the validator rule reflects the new value.
- [ ] Synthetic test for maintenance_capex: confirm the prompt rendered to GPT shows the bound coming from the contract row (not the deleted prose).

## Exit Criteria

- All Task checkboxes complete
- Both regression E2Es pass
- Three synthetic edits prove the values are read at runtime
- Snapshot refreshed and preflight green
- Index file Status updated: M4 = `completed`

## Risk Notes

- **Pure migration, behavior should be identical.** If E2E behavior changes after M4, something is wrong — either the default values in the new columns don't match the old constants, or a code path isn't reading the new column.
- **Snapshot drift is intentional.** Run the freeze script with the new baseline name only after confirming all changes are deliberate.
- **Coordinate with M2.** The convergence guard columns overlap. Land M2 first if possible; M4 just verifies.
- **The cash preferred-ratio constants currently match across all cash policy rows.** Diverging them per (cash_strategy × debt_position) is a follow-up, not part of M4. M4 just makes the migration; tuning per cell is a separate decision.
- **Don't change the planning-mode behavior in M4.** The table values must produce identical convergence behavior to today. Only the source of the numbers moves.

## Notes from a future session

(Empty.)
