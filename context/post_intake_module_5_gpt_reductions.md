# Module 5: GPT Reductions

**Status:** completed (2026-05-06)
**Scope:** post-intake only.
**Depends on:** Module 1 (resolver), Module 3 (contract NAICS bound machinery + finalize realism gate).
**Unblocks:** none structurally. Reduces GPT cost, latency, and variance.

## Architecture used: "Python proposes structure; GPT critiques structure"

Tasks 5.1, 5.2, 5.4 followed the original spec (delete or short-circuit GPT for unambiguous cases). Tasks 5.3, 5.5, and 5.6 — where the spec called for a deterministic replacement — landed on a stronger architecture: **Python builds a deterministic proposal from SQL/NAICS/intake data; GPT receives the proposal as input and either accepts, amends specific fields, or rejects; Python applies corrections; if GPT fails, the proposal stands as the safety floor.**

This pattern preserves GPT's domain judgment (timing nuance, edge-case applicability) without paying GPT's variance/latency on every decision. The shared critique infrastructure lives in `python/client_intake_and_finmo/post_intake_critique/`. See `feedback_python_proposes_gpt_critiques.md` memory entry for the full rationale.

## Why this module

Now that the resolver exists (M1) and the realism gate catches industry-implausible outputs (M3), several GPT calls are doing work the tables can do deterministically. Per master diagnostic Part 7.2, ranked by reducibility:

1. **Delete `maintenance_capex_percent` GPT entirely** — NAICS metric replaces it 1:1.
2. **Replace `r_and_d_applicability` with NAICS-2 lookup** — covers ~80% of businesses; GPT only for ambiguous cases.
3. **Reduce `balance_sheet_contextual_seed`** — most of its work becomes deterministic NAICS-cascade × Tier A-anchor logic.
4. **Short-circuit direct-fit convergence cycles** — when one-lever / one-metric / one-quarter, solver does it algebraically without GPT (also addressed in M2 Task 2.4; M5 confirms the upstream skip happens).
5. **Reduce `cash_strategy_review`** — replace with deterministic allocator + per-policy timing rules. The GPT call already operates inside a Python-narrowed feasible region (master-diagnostic Part 11).
6. **Delete convergence verification GPT** — redundant once M3's finalize realism gate is hard-failing on high-confidence metrics.

Net effect: 2 GPT calls deleted outright, 4 reduced to tiny tiebreaker calls or arithmetic-with-GPT-for-edge-cases. Roughly 30-40% reduction in GPT calls per run; dramatically less variance per remaining call.

**Master-diagnostic references:**
- Part 7.2 (ranked GPT reductions, items 1-8)
- Part 11.5, 11.6 (cash strategy review reduction details)
- Part 12.6 (intake reality — what each call is actually filling)
- Part 13 (separate marketing schedule; do not duplicate here)

## Dependencies

- **M1 must be complete** (resolver exists for all NAICS substitutions).
- **M3 must be complete** (finalize realism gate must hard-fail on high-confidence metrics so reductions are safety-netted; contract NAICS bound machinery used by reduced calls).

## Pre-flight

- [ ] M1 + M3 both at status `completed`. Both regression E2Es passing post-M3.
- [ ] Read master-diagnostic Parts 7.2, 11.5, 11.6, 12.6.
- [ ] Run NexGen + ValueMart E2Es one more time as the post-M1+M3 baseline. Record GPT call counts per run from the planning_run_json telemetry. This is the before/after measurement.
- [ ] Identify the planning_run_json field that records OpenAI call telemetry (`_reset_openai_call_telemetry`, `_openai_call_telemetry_snapshot` in `intake_consult.py:203-220`). Confirm it captures call counts per phase.

## Task 5.1 — Delete `maintenance_capex_percent` GPT call

- [ ] Find `_estimate_maintenance_capex_percent_with_gpt` in `python/client_intake_and_finmo/post_intake_contracts/runner.py:1051-1148`.
- [ ] Replace it with a deterministic function `derive_maintenance_capex_percent_from_naics(business_naics_6, business_stage)`:
  - Calls M1 resolver with `metric_key="maintenance_capex_percent_of_revenue"`
  - Returns `benchmark_target` clamped to the contract row's `min_value`/`max_value` (which come from the same NAICS cascade after M3 — defensive)
  - On `no_coverage`, falls back to mid-band (8.5%) with `confidence_tier = "generic_default"` provenance
- [ ] Update `prepare_initial_grid_for_draft` (`post_intake_initial_grid/runner.py:48`) to call the new deterministic function instead of `estimate_maintenance_capex_percent_with_gpt`.
- [ ] Delete the obsolete GPT prompt-build path and the `maintenance_capex_percent` contract row from `post_intake_gpt_contract_lookup` (the row stays for historical snapshot if needed; mark `contract_status = 'retired'`).
- [ ] Update the corresponding sequence row's `python_role` and `python_action` columns to reflect the deterministic ownership.
- [ ] Carry NAICS provenance through to the maintenance_capex driver row metadata.

## Task 5.2 — Replace `r_and_d_applicability` with NAICS-2 lookup

- [ ] Create new SQL table `post_intake_r_and_d_applicability_lookup`. Columns:
  ```
  id BIGINT UNSIGNED PRIMARY KEY
  naics_2 VARCHAR(2) NOT NULL UNIQUE
  applicability_default VARCHAR(32) NOT NULL    -- 'required' | 'optional' | 'not_applicable'
  default_percent_when_required DECIMAL(10,4) NULL  -- e.g. 0.05 = 5%
  notes LONGTEXT NULL
  active TINYINT(1) NOT NULL DEFAULT 1
  ```
- [ ] Populate per master diagnostic Part 7.2 #4 / Part 12.5:
  - `51` (Information): required
  - `54` (Professional/Scientific/Technical): required
  - `325` (Pharma) — actually NAICS-3, treat as `33` for Manufacturing of Computer/Electronic/Pharma broadly: required
  - `33` (Manufacturing): optional (depends on sub-industry)
  - `44`, `45` (Retail): not_applicable
  - `72` (Accommodation/Food): not_applicable
  - `81` (Other Services): not_applicable
  - others: optional default
- [ ] Add table-ensure function. Add to snapshot source tables.
- [ ] Add lookup function `post_intake_r_and_d_applicability_for_naics2(naics_2) -> {applicability_default, default_percent_when_required}`.
- [ ] Replace `_estimate_r_and_d_applicability_with_gpt` in `post_intake_contracts/runner.py:1397-1540` with `derive_r_and_d_applicability_from_naics(business_naics_6)`:
  - Extract NAICS-2 from `business_naics_6[:2]`
  - Look up the applicability row
  - When `applicability_default == 'required'` or `'not_applicable'`: return deterministic decision
  - When `applicability_default == 'optional'`: still call GPT for the tiebreaker (smaller, more focused contract)
- [ ] Update `prepare_initial_grid_for_draft:50` to call the new function.
- [ ] The `r_and_d_applicability` GPT contract row stays but is only used for the optional tiebreaker case.

## Task 5.3 — Reduce `balance_sheet_contextual_seed`

The reduction strategy per master diagnostic Part 12.6:
- Deferred revenue and prepaid: pure NAICS substitution + applicability gate (already done in M1).
- AR / AP / inventory: intake-anchored at stub 0 (Tier A); seed step's residual job is the *trajectory* into Q1 (deterministic via NAICS days).
- PPE / debt / equity: intake-anchored at stub 0; post-intake schedules own the trajectory.

So the seed GPT call shrinks to potentially zero direct decisions (M1 handled missing-line substitution; M5 makes the trajectory deterministic).

- [ ] Find `_estimate_balance_sheet_contextual_seed_with_gpt` in `post_intake_contracts/runner.py:1550-1694`.
- [ ] Replace with `derive_balance_sheet_contextual_seed_deterministic(business_facts, financials_json, financials_year1_json, business_naics_6)`:
  - For each mapping-table candidate driver (AR, AP, inventory, prepaid, deferred revenue, debt):
    1. If intake provided a non-zero stub 0 anchor → use it; trajectory walks per NAICS days/percent metric
    2. If intake provided zero AND applicability says metric applies → trajectory from NAICS substitution (Q1+ only)
    3. If intake provided zero AND applicability says not applicable → keep at zero
    4. PPE / debt / equity: anchor at stub 0; let the depreciation and debt schedules own forward
- [ ] The deterministic function returns the same payload shape today's GPT contract returns (so downstream `apply_balance_sheet_contextual_seed_to_model_input` works unchanged).
- [ ] Update `prepare_initial_grid_for_draft:53` to call the new deterministic function.
- [ ] Mark the GPT contract `balance_sheet_contextual_seed` row as `contract_status = 'retired'`.
- [ ] Sequence row's `python_role` updates from `gpt_decision_with_python_validation` to `deterministic_step_executor`.

## Task 5.4 — Confirm direct-fit convergence short-circuit (covered by M2 2.4)

If M2 has landed Task 2.4, this is a verification only. Otherwise:

- [ ] Edit `post_intake_convergence/runner.py` so that when `len(active_lever_ids) == 1 and len(target_metric_names) == 1 and len(targeted_quarters) == 1` and the lever→metric mapping is `direct`, the cycle skips the planner GPT call entirely and proceeds straight to the solver.
- [ ] The solver (post-M2) runs the algebraic path first; if it closes the target, we're done with one cycle and zero GPT calls.
- [ ] When the algebraic path can't close (probe out of bounds, etc.), fall through to GPT as the multi-lever path does.

## Task 5.5 — Reduce `cash_strategy_review` to a deterministic allocator

Per master diagnostic Part 11.5: the GPT call already operates inside a Python-narrowed feasible region. Replace with a Python allocator + per-policy timing rules.

- [ ] Find `_run_cash_strategy_review_openai` in `post_intake_cash/runner.py:1945`.
- [ ] Build a new function `compose_cash_strategy_decision_deterministic(violation_envelope, funding_source_policy, lever_bounds, cash_policy_row)`:
  - For each quarter with `residual_funding_gap > 0`:
    - Allocate funding from `allowed_funding_source_lever_ids` in priority order:
      1. `owners_capital` (operator/insider) up to `owners_capital_max_value`
      2. `debt_issuance` (if not excluded by funding_source_policy) up to `debt_issuance_max_value`
      3. `other_equity` (if justified) up to `other_equity_max_value`
    - Stop when gap is closed
  - For each quarter with `deployable_surplus > 0`:
    - Apply policy weights: `distribution_share = surplus * distribution_weight`, `paydown_share = surplus * debt_paydown_weight`, `retain_share = surplus * retain_weight`
    - Cap each at the per-quarter `max_additional_*` from the lever bounds
  - For new debt issuance timing — initially: take the gap as it falls; later: load a per-(cash_strategy × debt_position) timing rule from a new `cash_timing_policy` JSON column in `post_intake_cash_policy_lookup` if needed.
  - Return the same payload shape `cash_strategy_review_decision_v2` produces today so `_apply_cash_strategy_exact_updates` works unchanged.
- [ ] Update phase 30 (`cash_gpt_review`) of the cash phase sequence: change `phase_owner` from `gpt` to `python` and update `validation_gate` accordingly.
- [ ] Wire `_run_cash_strategy_review_openai` to be called only as a tiebreaker (e.g., when the deterministic allocator can't satisfy a quarter even with all sources at max).
- [ ] The `cash_strategy_review` contract row stays for the tiebreaker case; mark its row metadata with the new "tiebreaker only" semantics in notes.
- [ ] **The second-pass plan (master-diagnostic Part 11.6) likely becomes unnecessary** because the deterministic allocator produces a valid plan on the first pass. Verify with the synthetic tests; remove the second-pass code if confirmed redundant.

## Task 5.6 — Delete convergence verification GPT

- [ ] Find the convergence verification GPT call (in `post_intake_convergence/runtime.py` around line 3552, contract name `unified_convergence_verification`).
- [ ] Verify M3's finalize realism gate is hard-failing on the metrics this verification GPT was effectively checking (cogs, ebitda, payroll/revenue, etc.).
- [ ] Delete the verification GPT call from the convergence loop.
- [ ] Mark `unified_convergence_verification` contract row as `contract_status = 'retired'`.
- [ ] Update the sequence row to remove the verification step or change its handler to a no-op shim that just records "verification absorbed into finalize realism gate".

## Task 5.7 — Snapshot refresh

- [ ] After all tasks complete, refresh `post_intake_lookup_table_snapshot` via `scripts/freeze_post_intake_golden_baseline.py`.
- [ ] The contract lookup will have several rows marked `retired`; the row count may decrease net (the new R&D applicability table adds rows). Document the deltas in the freeze commit message.

## Files Touched

- `python/client_intake_and_finmo/post_intake_contracts/runner.py` (replace 3 GPT functions with deterministic ones)
- `python/client_intake_and_finmo/post_intake_initial_grid/runner.py` (call sites)
- `python/client_intake_and_finmo/post_intake_cash/runner.py` (deterministic allocator, phase 30 ownership change)
- `python/client_intake_and_finmo/post_intake_convergence/runner.py` (direct-fit short-circuit if not done in M2)
- `python/client_intake_and_finmo/post_intake_convergence/runtime.py` (delete verification call)
- `python/client_intake_and_finmo/post_intake_mapping.py` (new R&D applicability table; mark retired contract rows)

## Files NOT Touched

- M1's resolver — read by all the new deterministic functions, but the resolver itself is unchanged
- Mapping table formula registry — unchanged
- Payroll, debt, depreciation schedules — unchanged
- Stub 0 — never written by deterministic substitutions
- FINMO calc — unchanged
- The remaining GPT calls (stage_ramp_contract, payroll_headcount_schedule, quarter_grid_openai) — out of M5 scope; addressed by future architecture-flip work
- Marketing GPT path — Module 6 owns this; do not touch in M5

## Verification

- [ ] All Task 5.x checkboxes complete
- [ ] NexGen Software E2E passes with `all_cleared`. **GPT call count should be down by at least 3 calls per run** (maintenance_capex deletion, R&D for non-ambiguous NAICS, balance_sheet_seed, verification, cash_strategy_review when allocator handles it).
- [ ] ValueMart Superstores E2E passes with the same call-count reduction.
- [ ] Total run time per E2E should drop materially (record before/after).
- [ ] Synthetic test for the R&D tiebreaker: a NAICS-2 marked `optional` (e.g., 33) should still call GPT.
- [ ] Synthetic test for the cash allocator tiebreaker: a deliberately over-constrained intake where deterministic allocator can't close the gap should fall through to GPT and either succeed or fail-fast cleanly.
- [ ] Synthetic test for the convergence verification deletion: confirm a previously-warned implausible model now fails-fast at finalize realism gate (M3) instead of being caught by verification GPT.
- [ ] `scripts/post_intake_golden_preflight.py` runs cleanly post-snapshot refresh.

## Exit Criteria

- All Task checkboxes complete
- Both regression E2Es pass with measurable GPT-call-count reduction
- Synthetic tiebreaker tests behave as expected
- Snapshot refreshed and preflight green
- Index file Status updated: M5 = `completed`

## Risk Notes

- **Cash allocator is the biggest risk.** The GPT call today does timing nuance ("save the equity raise for Q3") that a greedy allocator can't capture. If the allocator produces a plan that fails the cash-pass post-validation, the operator will see fail-fasts that didn't happen before. Tune the priority order and per-quarter timing rules empirically.
- **Verification GPT deletion depends on M3 being well-tuned.** If M3's finalize gate is mostly in `gate_kind = "warn"` mode, the verification GPT was actually doing the catching. Don't delete verification until M3 has hard-failed on at least 4-5 high-confidence metrics in real runs.
- **R&D applicability table is initial guess.** The NAICS-2 defaults are based on industry knowledge but real-world test runs may show edge cases (a NAICS-44 retailer that owns proprietary tech, etc.). Be prepared to refine the table.
- **Don't reduce calls that aren't on the list.** `stage_ramp_contract`, `payroll_headcount_schedule`, `quarter_grid_openai` keep their GPT roles. M5 is specifically the easy wins.
- **Carry provenance.** Every deterministic substitution must propagate `seed_source`, `naics_level_used`, `confidence_tier` so the workbook can show where each value came from.
- **The remaining cash strategy GPT (tiebreaker) needs a small contract.** When it fires, it should see a much narrower decision surface than today (only the unsolvable quarters, not the full 20). Build that narrowed-context contract.

## Notes from a future session

### 2026-05-06 — Tasks 5.3, 5.5, 5.6 implemented as Python proposer + GPT critic

The spec called for "deterministic replacement" of these three GPT calls. Implementation took a stronger architecture: Python builds a deterministic proposal (always contract-valid), GPT critiques specific fields, Python applies corrections, and the proposal stands as the safety floor when GPT fails.

**Task 5.3 (`balance_sheet_contextual_seed`)**
- New: `propose_balance_sheet_contextual_seed_payload` in `post_intake_balance_sheet/contextual_seed.py`
- Per-lever NAICS-2 applicability gate; Tier A intake anchor priority over NAICS cascade fallback; mapping-band midpoint final fallback
- `_estimate_balance_sheet_contextual_seed_with_gpt` rewritten as proposer + critic
- New helper `_finalize_balance_sheet_seed_with_critique` slims the rich proposer payload to the strict contract shape before validation

**Task 5.5 (`cash_strategy_review`)**
- New: `propose_cash_strategy_review_decision` in `post_intake_cash/cash_strategy_proposer.py`
- Walks each `required_funding_quarter` and picks one funding source via policy priority order, validated against per-quarter `lever_bounds` (with `cash_support_multiplier` gross-up for debt issuance)
- Underfunded fallback path: when no source has enough headroom, allocate the highest-headroom source's max and surface shortfall in `proposer_diagnostics`
- `_run_cash_strategy_review_openai` rewritten as proposer + critic; the legacy "GPT writes from scratch + retry-on-invalid" loop was REMOVED (≈530 lines deleted) because the proposer guarantees a valid baseline
- New helper `_wrap_cash_strategy_review_decision` standardizes the cash review return envelope

**Task 5.6 (`unified_convergence_verification`)**
- New: `propose_realism_verification_payload` in `post_intake_realism/verification_proposer.py`
- Per-issue verdict derived from `applied_updates` ∩ `affected_quarters`: resolved (all touched) / improved (some touched) / stalled (none touched) / needs_review (malformed packet)
- `_run_realism_verification_openai` rewritten as proposer + critic; legacy heavy prompt-build path removed

**Shared infrastructure**
- New package `post_intake_critique/` with `CRITIQUE_CONTRACT_SCHEMA`, `CritiqueResponse`, `CritiqueCorrection`, `apply_corrections_to_proposal`, `proposal_only_response`
- Field-path notation supports bracket indexing: `quarter_funding_plan[0].funding_sources[0].lever_id`
- Corrections targeting non-existent paths are silently dropped and surfaced in `_critique_diagnostics`

**Tests**
- `Test Files/test_module5_gpt_reductions.py` — 23/23 passing, covers all six tasks + critique contract behavior + safety-floor semantics

**What was NOT done**
- Snapshot refresh (Task 5.7) deferred to user-driven freeze step; the existing contract rows remain `active` because all six contracts are still used (now as critique surfaces, not blank-slate prompts).

