# Module 3: GPT Contract NAICS Bounds + Finalize Realism Gate

**Status:** not_started
**Scope:** post-intake only.
**Depends on:** Module 1 (resolver must exist).
**Unblocks:** Modules 5 and 6 (both rely on the contract-bound machinery and the realism gate).

## Why this module

Two related additions land together because they share the realism-substrate:

1. **GPT contract NAICS bound injection.** Today, GPT contracts in `post_intake_gpt_contract_lookup` have `min_value`/`max_value` columns that are populated for some fields but not all (e.g., maintenance capex is hardcoded "2 to 15" prose; balance sheet seed has universal mapping bounds, not NAICS). Phase 3 of the master diagnostic populates these columns from the NAICS cascade at prompt-build time. Mapping-table absolute bounds remain the outer envelope; NAICS becomes the inner narrowing envelope.
2. **Finalize realism gate.** The biggest realism gap in the system today: a run can produce `cogs_percent = 0.95` or `current_ratio = 0.1` and `all_cleared = true` will still print. There is no industry-typical-band check in the finalize validator. This module builds it.

Together they're the realism layer's teeth: bounds tighten what GPT can pick; the gate fails-fast when produced ratios fall outside NAICS bands.

**Master-diagnostic references to read before starting:**
- Part 3 §P2 (no finalize realism gate), §P7 (balance sheet seed bounds), §P8 (payroll bounds), §P9 (maintenance capex)
- Part 5 Phase 3 (GPT contract bound injection), Phase 4 (finalize realism gate)
- Part 6.1 (every FINMO line gets a realism band, ~30 line-level checks)
- Part 6.2 (schedule sanity bands at finalize)
- Part 8.5 (every reduction lands as a driver, never a statement patch)
- Part 12 (Tier A/B/C/D — what intake captures vs. what finalize must validate)

## Dependencies

- **M1 must be complete.** This module reads the resolver constantly — both at prompt-build time (bound injection) and at finalize time (band check).

## Pre-flight

- [ ] Confirm M1 complete; both E2Es still pass.
- [ ] Read master-diagnostic Parts 3 (P2, P7, P8, P9), 5 (Phases 3-4), 6.1-6.2, 12.
- [ ] Read `python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py` end-to-end (642 lines).
- [ ] Read `python/client_intake_and_finmo/post_intake_mapping.py:post_intake_build_prompt_from_contract` and the contract field row schema (DDL at `_ensure_gpt_contract_lookup_table` line 3853).
- [ ] Read the per-metric registry — confirm `governs_model_input_lever` is populated for the metrics that map cleanly to model_input drivers.

## Task 3.1 — Add NAICS-baseline columns to the GPT contract lookup

- [ ] Add columns to `post_intake_gpt_contract_lookup` via DDL in `post_intake_mapping.py:_ensure_gpt_contract_lookup_table`:
  - `naics_baseline_metric_key VARCHAR(128) NULL` — when set, `min_value`/`max_value` are populated at prompt-build time from this metric's NAICS cascade
  - `naics_baseline_band_kind VARCHAR(32) NULL` — `min_target_max` (full band) or `target_only` (use benchmark_target as the central point and let `min_value`/`max_value` widen by a configured tolerance)
  - `naics_baseline_min_quantile DECIMAL(6,4) NULL` — defaults to 0.10 if NULL (use benchmark_min)
  - `naics_baseline_max_quantile DECIMAL(6,4) NULL` — defaults to 0.90 if NULL (use benchmark_max)
  - `mapping_table_outer_envelope TINYINT(1) NOT NULL DEFAULT 1` — keep mapping-table absolute min/max as the outer envelope
- [ ] Migration is additive; existing rows get NULL for the new columns.
- [ ] Document the column semantics inline in the table-ensure DDL.

## Task 3.2 — Build NAICS bound injection at prompt-build time

- [ ] Edit `python/client_intake_and_finmo/post_intake_mapping.py:post_intake_build_prompt_from_contract` (and the schema-build helpers `post_intake_gpt_contract_openai_schema`, `post_intake_gpt_contract_prompt_field_spec`).
- [ ] At schema build time, for each contract field row where `naics_baseline_metric_key` is set:
  - Resolve via M1's `post_intake_industry_baseline_for_naics(metric_key, naics_6)`
  - Compute the effective `min_value` and `max_value` from the resolver payload
  - When `mapping_table_outer_envelope = 1`, intersect with the static row `min_value`/`max_value` (NAICS narrows; mapping caps)
  - Inject the resulting `min_value`/`max_value` into the OpenAI JSON schema for the field
- [ ] Carry the NAICS-band metadata in a debug field of the rendered prompt: `_naics_band: {metric_key, naics_level_used, confidence_tier, source_min, source_max}` so the prompt trace and the workbook can see which bound came from where.

## Task 3.3 — Populate `naics_baseline_metric_key` for the high-impact contract fields

Per master diagnostic Part 6.1 + Part 7.2:

- [ ] `maintenance_capex_percent.maintenance_capex_percent` row → `naics_baseline_metric_key = "maintenance_capex_percent_of_revenue"`. (Note: M5 will delete this GPT call entirely. Until then, NAICS-bound the prompt prose.)
- [ ] `balance_sheet_contextual_seed.*` rows for AR balance, AP balance, inventory, prepaid, deferred revenue → set `naics_baseline_metric_key` to the corresponding days/percent metric, with `naics_baseline_band_kind = "min_target_max"`.
- [ ] `stage_ramp_contract.revenue_qoq_growth_target_min/max` rows → `naics_baseline_metric_key = "startup_qoq_growth_typical"` etc. per stage_family. (M2 already wires the stage policy itself; this populates the contract bounds for GPT.)
- [ ] `payroll_headcount_schedule.target_payroll_percent_of_revenue` → `naics_baseline_metric_key = "payroll_percent_of_revenue"`. **Reasonableness target only** — does not clip payroll (Golden Rule preservation).
- [ ] `unified_convergence_decision.lever_adjustments[]` rows that target ratio metrics (cogs%, marketing%, sga%, r_and_d%) — set per-lever `naics_baseline_metric_key`.

## Task 3.4 — Build the finalize realism check lookup table

- [ ] Create new SQL table `post_intake_finalize_realism_check_lookup`. Columns:
  ```
  id BIGINT UNSIGNED PRIMARY KEY
  metric_key VARCHAR(128) NOT NULL                  -- e.g. 'cogs_percent_of_revenue'
  finmo_line_label VARCHAR(128) NOT NULL            -- which FINMO line this check covers
  derivation_formula_key VARCHAR(128) NOT NULL      -- named formula in registry: 'cogs_dollars / revenue_dollars', 'ar_dollars / revenue_dollars * 90', etc.
  quarter_aggregation VARCHAR(32) NOT NULL          -- 'per_quarter' | 'year_one_aggregate' | 'horizon_average'
  applicability_rule_key VARCHAR(64) NULL           -- e.g. 'inventory_when_business_has_inventory', 'deferred_revenue_when_business_has_recurring'
  tolerance_bps_high_confidence INT NOT NULL        -- e.g. 1500 = +/- 15pp around target
  tolerance_bps_medium_confidence INT NOT NULL      -- e.g. 2500
  tolerance_bps_low_confidence INT NOT NULL         -- e.g. 4000
  tolerance_bps_generic_default INT NULL            -- NULL = skip when only generic default exists
  gate_kind VARCHAR(32) NOT NULL                    -- 'hard_fail' | 'warn' | 'skip_if_no_coverage'
  governs_model_input_lever_id VARCHAR(128) NULL    -- for provenance / diagnostic surface
  notes LONGTEXT NULL
  active TINYINT(1) NOT NULL DEFAULT 1
  created_at, updated_at
  UNIQUE KEY (metric_key, quarter_aggregation)
  ```
- [ ] Add the table-ensure function in `post_intake_mapping.py`.
- [ ] Add it to `_post_intake_snapshot_source_tables()` so the golden preflight watches it.
- [ ] Add lookup function `post_intake_finalize_realism_check_rows()` and a row-finder by `metric_key`.

## Task 3.5 — Populate the finalize realism check rows for ~30 line-level checks

Per master diagnostic Part 6.1, populate one row per FINMO line that has a NAICS metric. Initial mode: `gate_kind = "warn"` for all rows so observation phase doesn't block runs. The sweep:

**P&L (16 rows):**
- [ ] `cogs_percent_of_revenue` — per_quarter
- [ ] `gross_margin_percent` — per_quarter (derived)
- [ ] `payroll_percent_of_revenue` — per_quarter and year_one_aggregate (separate rows)
- [ ] `revenue_per_fte` — year_one_aggregate
- [ ] `marketing_percent_of_revenue` — per_quarter
- [ ] `advertising_percent_of_revenue` — per_quarter (with applicability check; usually included in marketing)
- [ ] `r_and_d_percent_of_revenue` — per_quarter (applicability rule: only when r_and_d_applicability is true)
- [ ] `rent_percent_of_revenue` + `lease_percent_of_revenue` + `occupancy_total_percent_of_revenue` — per_quarter
- [ ] `sga_percent_of_revenue` — per_quarter
- [ ] `depreciation_percent_of_revenue` — per_quarter
- [ ] `effective_tax_rate` — year_one_aggregate
- [ ] `stock_based_compensation_percent_of_revenue` — per_quarter (applicability: equity-comp businesses only)
- [ ] `operating_margin_percent`, `ebitda_margin`, `net_income_margin` — per_quarter

**Balance sheet (12 rows):**
- [ ] `ar_days_dso` — per_quarter
- [ ] `ap_days_dpo` — per_quarter
- [ ] `inventory_days` — per_quarter (applicability: inventory businesses only)
- [ ] `prepaid_expenses_percent_of_revenue` — per_quarter
- [ ] `deferred_revenue_percent_of_revenue` — per_quarter (applicability: recurring/subscription/deposit businesses)
- [ ] `ppe_percent_of_revenue` — year_one_aggregate
- [ ] `total_assets_to_revenue` — year_one_aggregate
- [ ] `owners_capital_percent_of_assets` — year_one_aggregate
- [ ] `current_ratio`, `quick_ratio` — per_quarter (warn-only; weak NAICS variation)
- [ ] `debt_to_equity`, `debt_to_assets` — per_quarter (applicability: debt > 0)

**Cash flow (4 rows):**
- [ ] `operating_cash_flow_margin` — per_quarter
- [ ] `capex_percent_of_revenue` — year_one_aggregate
- [ ] `maintenance_capex_percent_of_revenue` — year_one_aggregate
- [ ] `distributions_percent_of_net_income` — year_one_aggregate (applicability: distributions > 0)

## Task 3.6 — Implement `validate_industry_realism_bands` in finalize

- [ ] Edit `python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py`. Add a new validator function `validate_industry_realism_bands(model_input_json, finmo_json, business_naics_6, ...)`.
- [ ] Walk every active row of `post_intake_finalize_realism_check_lookup`.
- [ ] For each row:
  1. Apply `applicability_rule_key` — skip the check if the rule says not applicable for this business
  2. Compute the actual ratio per the `derivation_formula_key` from FINMO output and model_input data
  3. Aggregate per `quarter_aggregation` (per_quarter walks all 20 forecast quarters; year_one_aggregate sums Q1-Q4)
  4. Resolve NAICS band via M1's resolver
  5. Pick tolerance from the matching `tolerance_bps_<confidence_tier>` column
  6. Skip the check if `confidence_tier_used = generic_default` and `tolerance_bps_generic_default IS NULL`
  7. Compare actual to band ± tolerance
  8. On out-of-band:
     - If `gate_kind = "hard_fail"`: raise `RuntimeError("post_intake_finalize_realism_band_violation: metric={metric_key} actual={x} band=[{min}..{max}] tol_bps={tol} naics_level_used={n} confidence_tier={ct} governs_lever={l} quarter={q}")`
     - If `gate_kind = "warn"`: append to a `realism_warnings` list returned in the validation payload
     - If `gate_kind = "skip_if_no_coverage"`: as named, skip
- [ ] Wire the new validator into the existing finalize sequence so it runs after the formula-reconciliation checks but before the final stage transition.
- [ ] Persist the realism warnings list into the planning-run payload so the workbook and operator can see them.

## Task 3.7 — Add formula registry entries for the derivation formulas

- [ ] For each unique `derivation_formula_key` referenced in 3.5, add an entry to the deterministic formula registry that the validator dispatches on. Examples:
  - `cogs_dollars_div_revenue_dollars`
  - `ar_dollars_div_revenue_dollars_times_90`
  - `payroll_dollars_div_revenue_dollars_year_one_sum`
  - `ebitda_dollars_div_revenue_dollars`
- [ ] These belong in the existing formula registry pattern used by the mapping table — Python executes the named formula; SQL selects the key.

## Task 3.8 — Schedule sanity cross-checks at finalize (Part 6.2)

In addition to the line-by-line ratio checks in 3.5-3.7, add the schedule sanity checks per master-diagnostic Part 6.2:

- [ ] **Wage realism** (payroll schedule): produced average wage per supporting-staff FTE compared to NAICS `avg_wage_per_fte` band. Out-of-band → flag with `wage_positioning_tier_implausible` and the produced wage. Does not override; surfaces the issue.
- [ ] **Productivity realism** (payroll schedule): produced revenue per total FTE compared to NAICS `revenue_per_fte`. Same flag pattern.
- [ ] **Debt rate realism** (debt schedule): produced quarterly interest rate compared to NAICS `sba_initial_interest_rate` band. Plus cross-check with intake-anchored implied rate `annual_interest_payment / total_debt_outstanding`.
- [ ] **Capex / PPE / depreciation realism** (depreciation schedule): produced `capex_percent_of_revenue`, `ppe_percent_of_revenue`, `depreciation_percent_of_revenue` against NAICS bands.

## Task 3.9 — Promotion of warnings to hard_fail

- [ ] After two clean E2E runs (NexGen + ValueMart) with `gate_kind = "warn"`, review the warnings.
- [ ] Identify metrics where the warnings consistently match expected variance (no false positives) AND have NAICS coverage at level 6/5/4/3 with confidence_tier high or medium → flip those to `gate_kind = "hard_fail"`.
- [ ] Initial promotions to hard_fail (per master diagnostic Phase 4):
  - `cogs_percent_of_revenue` (n=1,686 rows, strong)
  - `ar_days_dso` (derived from industry_metrics_raw, strong)
  - `ap_days_dpo` (strong)
  - `ebitda_margin` (strong)
  - `effective_tax_rate` (n=1,519, strong)
- [ ] Keep warn-only for: `current_ratio`, `quick_ratio` (universal, weak NAICS variation); anything that resolves to `generic_default` consistently; `payroll_percent_of_revenue` (workforce metric with known cross-source coverage gap).
- [ ] Re-run both E2Es after each promotion. If a regression appears, demote and investigate.

## Files Touched (expected)

- `python/client_intake_and_finmo/post_intake_mapping.py` (contract DDL, table-ensure for new realism table, lookup functions, snapshot source list)
- `python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py` (new validator)
- A new formula-registry file or extension for the derivation formulas
- Test files for the validator and for at least 2-3 NAICS-cascade band checks

## Files NOT Touched

- Mapping table formula registry semantics — unchanged (only adding new derivation formulas; not changing the mapping rows)
- Payroll, debt, depreciation schedules — unchanged
- Stub 0 — never validated by realism gate (per master-diagnostic Part 9)
- FINMO calc — unchanged
- The realism gate must NOT rewrite drivers or statements. It fails-fast or warns. Per Part 8.6.

## Verification

- [ ] All Task 3.x checkboxes complete
- [ ] Initial run with all checks at `gate_kind = "warn"`: NexGen + ValueMart E2Es pass with `all_cleared`. The validation payload includes a `realism_warnings` array; eyeball it for sanity.
- [ ] After 3.9 promotions: NexGen + ValueMart E2Es still pass (no false positives on hard-fail metrics).
- [ ] Synthetic test: a deliberately broken intake that produces `cogs_percent = 0.95` for a NAICS where COGS typical is 30-50%. Confirm finalize fails-fast with `post_intake_finalize_realism_band_violation`.
- [ ] Synthetic test: a NAICS-2 with no NAICS-6 coverage for a metric. Confirm the gate uses `generic_default` tolerance (or skips if `tolerance_bps_generic_default IS NULL`).
- [ ] Workbook output: confirm the realism-warnings section is present and shows produced ratios vs. NAICS bands with `naics_level_used` and `confidence_tier` annotation.

## Exit Criteria

- All Task checkboxes complete
- Both regression E2Es pass with the realism gate active (mix of warn/hard_fail per 3.9)
- Synthetic broken-intake test fails-fast as expected
- Workbook surfaces realism warnings cleanly
- Index file Status updated: M3 = `completed`

## Risk Notes

- **Tolerance tuning is the hard part.** Set tolerances too tight and legitimate edge-case businesses fail-fast incorrectly. Too loose and the gate accepts implausible numbers. Start with the suggested values (1500/2500/4000 bps for high/medium/low confidence) and tune empirically.
- **Applicability rules matter.** Inventory check on a software business should skip, not fail-fast. Deferred revenue check on a restaurant should skip. Get the applicability table right before promoting to hard_fail.
- **The realism gate must surface, not patch.** When a metric is out of band, the gate fails-fast with the produced value, the band, the source, and the upstream lever — but does NOT rewrite the lever. The operator decides whether to re-run with different intake or accept the deviation.
- **Promotion to hard_fail is empirical.** Run a few diverse intakes (different NAICS, different sizes, startup vs operating) at warn-mode first and confirm warnings match expectation. Only then flip to hard_fail.
- **Don't validate stub 0.** Per Part 9.4, stub 0 is intake fact and cannot fail the realism gate by definition. Confirm in code that the gate skips Q0.

## Notes from a future session

(Empty.)
