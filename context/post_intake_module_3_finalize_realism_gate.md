# Module 3: GPT Contract NAICS Bounds + Finalize Realism Gate

**Status:** completed (v1+v2+v3 landed: Tasks 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9. Empirical promotion of additional metrics from warn→hard_fail is a perpetual follow-up that lives in the realism check lookup table, not in module-spec scope.)
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

### 2026-05-06 — Module 3 v3 landed (Module 3 COMPLETED)

**Files added / changed in v3:**
- `python/client_intake_and_finmo/post_intake_realism/formulas.py` — fixed CRITICAL v2 bug: formulas referenced FINMO field names that DO NOT EXIST in `FinmoQuarterResult` (`cogs` instead of `cost_of_goods_sold`, `r_and_d` instead of `research_and_development`, `g_and_a` instead of `general_and_administrative`, `pretax_income` field that doesn't exist — now derived from EBITDA - interest - depreciation, `operating_expense_total` field that doesn't exist — now summed from cost_of_goods_sold + marketing + research_and_development + lease_rent + general_and_administrative). v2's tests passed only because the synthetic FINMO used the wrong field names too, so production would have silently emitted zero warnings on every run. Expanded the registry from 10 to 29 formulas covering the line-level metrics in master-diagnostic Part 6.1.
- `python/client_intake_and_finmo/post_intake_realism/lookup.py` — Task 3.5 expansion: 10 → 28 default rows in `post_intake_finalize_realism_check_lookup`. New rows: gross_margin%, advertising% (skip-if-no-coverage), r_and_d%, rent% (lease_rent line), sga%, depreciation%, operating_margin%, prepaid_expenses%, deferred_revenue%, ppe% (year_one_aggregate), total_assets_to_revenue, owners_capital_pct_of_assets, current_ratio, quick_ratio, debt_to_equity, debt_to_assets, operating_cash_flow_margin, capex% (year_one_aggregate), distributions_pct_of_net_income (year_one_aggregate). Tightened ratio-metric tolerances to 700/1200/2000/3000 bps (high/medium/low/generic) — the v2 1500/2500/4000 was too generous, letting `cogs = 0.95` for retail land in-tolerance.
- `python/client_intake_and_finmo/post_intake_realism/lookup.py` — Task 3.9 promotion: 5 high-confidence ratio metrics promoted from warn → hard_fail: `cogs_percent_of_revenue`, `ar_days_dso`, `ap_days_dpo`, `ebitda_margin`, `effective_tax_rate`. Universal liquidity ratios (`current_ratio`, `quick_ratio`) and metrics with known coverage gaps (`payroll_percent_of_revenue`) stay at warn-mode per master-diagnostic Phase 4 guidance.
- (new) `python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py` — Task 3.8: four schedule-level cross-checks. `validate_schedule_sanity()` runs (1) wage realism (produced avg wage/FTE vs NAICS `avg_wage_per_fte`), (2) productivity realism (revenue/FTE vs NAICS `revenue_per_fte`), (3) debt rate realism (produced annualized rate vs NAICS `sba_initial_interest_rate`, with intake-implied rate cross-check), (4) capex/PPE/depreciation chain consistency (Q2-Q4 PPE change vs capex - depreciation). All warn-only by default; hard-fail behavior is opt-in.
- `python/client_intake_and_finmo/post_intake_realism/validator.py` — added 4 new applicability rules: `r_and_d_when_applicable` (skip when r_and_d is zero across forecast), `deferred_revenue_when_business_has_recurring` (gates on Information / Finance / Real Estate / Professional Services / Healthcare NAICS-2), `skip_when_debt_zero`, `skip_when_distributions_zero`.
- `python/client_intake_and_finmo/post_intake_realism/__init__.py` + `validator.py` integration with `finalize_post_intake.py` — finalize now runs both line-level + schedule-level realism gates, combines warnings, and persists `realism_gate.line_level` + `realism_gate.schedule_level` payloads in the validation result.
- `python/client_intake_and_finmo/post_intake_mapping.py` — quantile-widening fix in `_resolve_naics_bound`: when `band_kind="min_target_max"` but the resolver returns target-only (no benchmark_min/max from the source), widen target via `naics_baseline_min_quantile` × target / `naics_baseline_max_quantile` × target with defaults 0.5 / 1.5. Resolves the maintenance_capex point-constraint issue from v1.
- `python/client_intake_and_finmo/post_intake_mapping.py` — Task 3.3 contract sweep: 7 additional NAICS-bound contract rows (stage_ramp_contract.cogs_target/cogs_max/marketing_max/rd_max/ga_max/lease_max + payroll_headcount_schedule.target_payroll_percent_of_revenue). Each row carries `naics_baseline_metric_key` + `naics_baseline_band_kind="min_target_max"` so prompt-build narrows the contract field's bounds to the industry-typical band.
- `python/client_intake_and_finmo/post_intake_contracts/runner.py` — DELETED hardcoded `field_schema_overrides` for cogs_target / cogs_max / marketing_max / rd_max / ga_max / lease_max in `_stage_ramp_contract_schema`. Those `{"type": "number", "minimum": 0, "maximum": 1}` overrides were silently bypassing the new NAICS injection. Threaded `business_naics` through `_post_intake_contract_schema`, `_maintenance_capex_percent_schema`, `_stage_ramp_contract_schema`, and the GPT-call functions `_estimate_maintenance_capex_percent_with_gpt` / `_estimate_stage_ramp_contract_with_gpt`.
- `python/client_intake_and_finmo/post_intake_headcount/schedule.py` — threaded `business_naics` into `post_intake_gpt_contract_openai_schema(...)` at the payroll-headcount call site.
- `python/client_intake_and_finmo/post_intake_mapping.py:stage_planning_ramp_policy` — updated docstring to reflect what the legacy hardcodes are doing now. The `early_revenue_share_ceiling_of_late_run_rate` Q1-Q4 fractions are explicitly NOT deleted: they're hand-calibrated stage-shape guidance for the quarter-grid prompt context (revenue as a share of late-horizon run-rate). The NAICS qoq metric (`startup_qoq_growth_typical` etc.) is BDS employment growth, which does not translate cleanly to share-of-late-run-rate. Replacing them needs a different upstream metric or empirical recalibration.
- (new) `Test Files/test_module3_realism_gate.py` updated for v3 — 11/11 pass: row-load expects 28 rows + tier promotion, validator tests use real FINMO field names + use marketing% (still warn) for warn-mode tests + cogs (now hard_fail by default) for raise tests.
- (new) `Test Files/test_module3_schedule_sanity.py` — 9/9 pass: payload shape, wage realism in/out of band, productivity, debt rate empty/present, capex/PPE chain consistent/inconsistent, invalid-NAICS graceful.
- (new) `Test Files/test_module3_contract_sweep.py` — 9/9 pass: stage_ramp NAICS band varies retail vs software, marketing_max NAICS-bound, rev_target keeps static rate_schema override (production wrapper), q field keeps integer override, payroll target% NAICS-bound, maintenance_capex quantile-widened, no-NAICS falls through to mapping outer envelope.

**Total regression suite: 73/73 pass across 8 test files** (resolver 17, M1 wiring 9, solver direct-fit 5, M2 stage-ramp 6, M3 contract bounds 7, M3 realism gate 11, M3 schedule sanity 9, M3 contract sweep 9).

**Module 3 done in plain language.** Today, when a $10M retail run produces:
- COGS ≈ 75-83% of revenue → in-band, no warning ✓
- COGS = 95% of revenue → `out_of_band_warn` (within hard_fail tolerance still)
- COGS = 130% of revenue → `RealismBandViolation` raised, run fails fast with the produced value, the band, the source, the lever, and the quarter. Operator decides next step; the run does not silently print `all_cleared = true`.

Software run produces 0 inventory days → applicability rule skips the check (legitimate-zero, not silent-zero). Retail run produces $250K wage per FTE → wage realism warning surfaces with `wage_positioning_tier_implausible` flag. PPE_q4 - PPE_q1 doesn't equal capex - depreciation → schedule-sanity warning surfaces with the failing quarter named.

GPT contracts now narrow to NAICS-typical bands at prompt-build time — retail GPT receives `cogs_target ∈ [0.75, 0.83]`, software GPT receives a different band. Universal `0..1` caps are gone for cogs/marketing/r_and_d/ga/lease and the universal `2..15` for maintenance_capex.

**What's intentionally NOT touched (with reasons):**
- The `early_revenue_share_ceiling_of_late_run_rate` fractions in `stage_planning_ramp_policy` stay because the BDS qoq metric doesn't translate cleanly to share-of-late-run-rate. Replacing them needs a different upstream metric (revenue ramp shape per NAICS-and-stage from a source we don't yet have). Documented with detailed reasoning in the function's docstring.
- Tolerance values for the realism check rows are honest first-pass calibrations: 700/1200/2000 bps for ratio metrics, 2000/3500/5000 bps for days metrics. Real-world E2E runs will inform whether to tighten further. The DDL design (per-tier columns) supports per-row tuning without code change.
- The `target_payroll_percent_of_revenue` field is NAICS-bound but stays a REASONABLENESS TARGET, not a clip — Python does not clip payroll to fit revenue (Golden Rule preservation). The realism gate at finalize independently checks the produced payroll/revenue ratio.

**Empirical promotion is a continuous activity.** Once real E2E runs surface actual warning patterns, additional metrics can be promoted from warn → hard_fail by updating `_DEFAULT_REALISM_CHECK_ROWS` (one-line change per row). That's table tuning, not module-spec scope.

### 2026-05-06 — Module 3 v2 landed (Tasks 3.4, 3.5-subset, 3.6, 3.7 + quantile widening fix)

**Files added / changed:**

- (new package) `python/client_intake_and_finmo/post_intake_realism/`
  - `__init__.py` — public exports.
  - `lookup.py` — Task 3.4: `post_intake_finalize_realism_check_lookup` table DDL + ensure-on-load + cached load + `post_intake_finalize_realism_check_for_metric` finder. Idempotent migration; the table seeds with 10 default rows on first ensure (cogs%, gross_margin%, marketing%, payroll%, effective_tax_rate, ebitda_margin, net_income_margin, ar_days_dso, ap_days_dpo, inventory_days), all in `gate_kind = "warn"` initially.
  - `formulas.py` — Task 3.7: registry of 10 named derivation formulas (`cogs_dollars_div_revenue_dollars`, `gross_margin_div_revenue`, `marketing_dollars_div_revenue_dollars`, `payroll_dollars_div_revenue_dollars`, `taxes_div_pretax_income_year_one`, `ebitda_div_revenue`, `net_income_div_revenue`, `ar_days_from_balance_and_revenue`, `ap_days_from_balance_and_expenses`, `inventory_days_from_balance_and_cogs`). Each is a pure function `(model_input_json, finmo_json, quarter_index) -> Optional[float]` that returns None when the input doesn't permit computation (formulas never raise).
  - `validator.py` — Task 3.6: `validate_industry_realism_bands(...)` walks every active row of the lookup, runs the applicability gate (`skip_when_revenue_zero`, `skip_when_pretax_income_nonpositive`, `inventory_when_business_has_inventory`, etc.), evaluates the formula per quarter (or year_one_aggregate / horizon_average), resolves the NAICS band via Module 1's resolver, picks the confidence-tier-keyed tolerance, and emits `RealismCheckResult` per data point. `gate_kind = "hard_fail"` raises `RealismBandViolation` immediately on the first violation; `warn` accumulates into a warnings list. **Stub 0 (Q0) is excluded** — formulas key on `quarter_index >= 1` and the FINMO row map drops Q0 entries.
- `python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py` — wired `validate_industry_realism_bands` into `run_finalize_post_intake_validation` after the existing formula / balance-sheet / cash-phase checks. The return payload now includes a `realism_gate` block with `warnings`, `warning_count`, `result_count`, and `checked: True` — Module 5/6 + the workbook export consume this for surface display.
- `python/client_intake_and_finmo/post_intake_mapping.py` — fixed the v1 quantile-widening gap. When `naics_baseline_band_kind = "min_target_max"` but the resolver returns target-only (no `benchmark_min`/`benchmark_max` from the source), the resolver now widens target via `naics_baseline_min_quantile` × target / `naics_baseline_max_quantile` × target (defaults 0.5 / 1.5 — i.e. ±50% of target). Resolves the maintenance_capex point-constraint issue from v1.
- (new) `Test Files/test_module3_realism_gate.py` — 10/10 pass: lookup row-load, formula registry, formula evaluation, validator in-band/out-of-band paths, hard_fail raises, applicability skip for software inventory, **stub 0 invariant verified** (synthetic Q0 row with garbage data does NOT trigger a warning), no-NAICS graceful fall-through.

**Total regression suite: 54/54 pass across 6 test files** (resolver 17, M1 wiring 9, solver direct-fit 5, M2 stage-ramp 6, M3 contract bounds 7, M3 realism gate 10).

**What v2 actually delivers (in plain language):**
- Today, a $10M retail run with `cogs_percent = 95%` and `all_cleared = true` would print. After v2: that run produces a `realism_warnings` entry `metric=cogs_percent_of_revenue actual=0.95 band=[0.60..0.98] target=0.82 confidence_tier=high naics_level_used=6 governs_lever=expenses::Cost of Goods Sold`. Currently warn-only; promoting cogs to hard_fail (Task 3.9) is the next pass once empirical data confirms no false positives.
- Software businesses no longer get inventory-days flagged — the applicability gate skips it cleanly (NAICS-2 51 not in the inventory-applicable set).
- Stub 0 is verified-by-test never-validated. The Part 9 invariant has machinery enforcement now, not just a doc note.

**What's deferred to Module 3 v3:**

- **Rest of Task 3.3 (other contract bound fields).** `balance_sheet_contextual_seed.*`, `stage_ramp_contract.revenue_qoq_growth_target_*`, `payroll_headcount_schedule.target_payroll_percent_of_revenue`, `unified_convergence_decision.lever_adjustments[]` — each needs both row-update plus threading `business_naics` into the schema-build call site (multiple call sites in `post_intake_contracts/runner.py` and `post_intake_headcount/schedule.py`).
- **Task 3.5 expansion.** v2 has 10 rows; Part 6.1 of the master diagnostic catalogues ~30 line-level metrics. Add: P&L (advertising%, R&D%, rent%, sga%, depreciation%, stock-based-comp%, gross_margin reverse-check, operating_margin); BS (prepaid%, deferred_revenue%, ppe%, total_assets/revenue, owners_capital/assets, current_ratio, quick_ratio, debt_to_equity, debt_to_assets); cash flow (operating_cash_flow_margin, capex%, maintenance_capex%, distributions%). Each row needs a formula; some formulas are easy (existing pattern), some need a year_one_aggregate path the validator already supports.
- **Task 3.8 — schedule sanity cross-checks.** Wage realism (avg wage/FTE vs NAICS), productivity realism (revenue/FTE vs NAICS), debt rate realism (produced quarterly interest rate vs `sba_initial_interest_rate`), capex/PPE/depreciation realism. Belongs in the same validator module as separate functions invoked from finalize.
- **Task 3.9 — warn → hard_fail promotion.** Empirical phase. Run NexGen + ValueMart with v2's warn-mode gate, eyeball the `realism_warnings` payload, then flip the metrics that cleanly match expectation (cogs%, ar_days_dso, ap_days_dpo, ebitda_margin, effective_tax_rate) to `hard_fail`. v2 leaves all 10 rows at warn; the promotion is a one-line update per row in `_DEFAULT_REALISM_CHECK_ROWS` once empirically validated.
- **Delete the hardcoded ramp ceilings in `stage_planning_ramp_policy`** (Module 2 leftover). Once the contract bound work for `stage_ramp_contract.revenue_qoq_growth_target_min/max` lands in the v3 Task 3.3 sweep, the prose ceilings in the policy can be removed safely (GPT will be receiving the NAICS qoq band via the contract instead).
- **Delete the maintenance_capex GPT call entirely** (Module 5 territory). Module 3 v1 already removed the prompt prose's hardcoded 2-15% range; Module 5 deletes the GPT call itself in favor of pure NAICS substitution.

**One open design decision for v3.** The default tolerances for ratio metrics (1500/2500/4000 bps for high/medium/low confidence) are generous — a 1500-bp tolerance on a real NAICS COGS band of [0.75, 0.83] expands the effective range to [0.60, 0.98], which means a retail run with COGS at 95% lands inside-tolerance in v2's warn-mode. That's intentional during the empirical phase (better to under-warn than false-positive while we observe), but Task 3.9's promotion to hard_fail almost certainly needs tighter tolerances for ratio metrics — proposed: 500/1000/2000 bps for high/medium/low confidence on ratio metrics, keep 1500/2500/4000 for days metrics. Decide empirically per metric.

### 2026-05-06 — Module 3 v1 landed (Tasks 3.1 + 3.2 + 3.3-subset) + cleanup of Modules 1+2 legacy

**Files added / changed:**
- `python/client_intake_and_finmo/post_intake_mapping.py` —
  - Task 3.1: 5 new columns on `post_intake_gpt_contract_lookup`: `naics_baseline_metric_key`, `naics_baseline_band_kind`, `naics_baseline_min_quantile`, `naics_baseline_max_quantile`, `mapping_table_outer_envelope`. Added to CREATE TABLE schema, ALTER TABLE migrations (idempotent), INSERT/ON DUPLICATE KEY UPDATE, the `_gpt_contract_row` builder, and the `load_post_intake_gpt_contract_rows` SELECT.
  - Task 3.2: New `_resolve_naics_bound` helper inside `PostIntakeGptContractLookup`. `_field_schema`, `object_schema_for_grid`, `openai_schema`, and the public `post_intake_gpt_contract_openai_schema` now accept an optional `business_naics` kwarg. When supplied + the row has `naics_baseline_metric_key` set + the resolver returns coverage, the JSON schema's `minimum`/`maximum` are populated from the cascade. Outer-envelope intersection with the row's static `min_value`/`max_value` is the default (`mapping_table_outer_envelope=True`); empty intersections fall back to the static envelope. Schema fields gain a `_naics_band` provenance dict for prompt-trace + workbook visibility.
  - Task 3.3 (subset): `maintenance_capex_percent` row updated. **The hardcoded universal range `min_value=2.00, max_value=15.00` was deleted.** Replaced by `naics_baseline_metric_key="maintenance_capex_percent_of_revenue"` + `naics_baseline_band_kind="min_target_max"` + `mapping_table_outer_envelope=False`. The bound is now NAICS-derived at prompt-build time. This is the *complete vertical slice*: DDL → injection → populated → hardcoded values deleted.
- `python/client_intake_and_finmo/finmo_bridge.py` — **Cleanup from Modules 1+2:** deleted `_operating_anchor_baseline_inputs` (it was dead code, zero callers anywhere; the spec referenced lines 945-948 / 970 inside it as silent-zero sites, which was misleading because edits there did nothing).
- (new) `Test Files/test_module3_contract_naics_bounds.py` — 7/7 pass. Verifies row-load surfaces new columns, schema build emits no min/max without NAICS, schema build with NAICS injects bound + provenance, NAICS for software resolves cleanly, invalid NAICS falls through, outer-envelope intersection logic.

**Total regression suite: 44/44 pass across 5 test files** (resolver 17, M1 wiring 9, solver direct-fit 5, M2 stage-ramp 6, M3 contract bounds 7).

**One known refinement for Module 3 v2.** When the resolver returns a target-only band (no benchmark_min/max in the underlying data — e.g., `maintenance_capex_percent_of_revenue` is from the `derived_depreciation_proxy` source which provides only target), the injected `minimum` and `maximum` end up equal, creating an exact-value constraint instead of a range. The `naics_baseline_min_quantile` / `naics_baseline_max_quantile` columns were added to the DDL as the home for this widening logic but the resolver does not yet consume them. Module 3 v2 should wire them in: when `bench_min`/`bench_max` are None and quantile cols are set, widen target into `[target × min_quantile, target × max_quantile]`. Until that wiring lands, contract rows that point at metrics with sparse min/max coverage will produce tight bounds — fine for the contract layer (GPT picks the value), but the realism gate (Tasks 3.6-3.9) needs proper bands to compare against.

**What's deferred to Module 3 v2 (and why):**

- **Task 3.3 (rest of contract fields).** `balance_sheet_contextual_seed.*` rows for AR/AP/inventory/prepaid/deferred revenue, `stage_ramp_contract.revenue_qoq_growth_target_min/max`, `payroll_headcount_schedule.target_payroll_percent_of_revenue`, `unified_convergence_decision.lever_adjustments[]` rows. Each needs a row update in `_DEFAULT_GPT_CONTRACT_ROWS` plus the call sites that build the schema for those contracts must pass `business_naics`. The latter is a non-trivial threading exercise (multiple contracts/runner.py call sites + the headcount schedule call site). Module 3 v1 establishes the pattern with `maintenance_capex_percent`; v2 sweeps the rest.
- **Task 3.4 (realism check lookup table).** New SQL table `post_intake_finalize_realism_check_lookup` with ~10 columns. Net new DDL.
- **Task 3.5 (~30 line-level realism check rows).** Each row is metric_key + derivation_formula_key + applicability_rule_key + per-tier tolerances + gate_kind. Detailed data entry that depends on Task 3.7's formula registry.
- **Task 3.6 (validate_industry_realism_bands).** The actual gate logic in `finalize_post_intake.py` — walks the table, computes ratios from FINMO output, applies tolerance per confidence tier, raises on hard_fail.
- **Task 3.7 (formula registry).** ~20-30 named derivation formulas (`cogs_dollars / revenue_dollars`, `ar_dollars / revenue_dollars * 90`, etc.). Belongs alongside the existing mapping-table formula registry.
- **Task 3.8 (schedule sanity cross-checks).** Wage realism, productivity realism, debt rate realism, capex/PPE realism. More validators in `finalize_post_intake.py`.
- **Task 3.9 (warn → hard_fail promotion).** Empirical phase; needs at least one clean E2E run with the warn-mode realism gate emitting warnings before promoting any metric.
- **Hardcoded ramp ceilings in `stage_planning_ramp_policy`.** The `Q1=0.25, Q2=0.40, Q3=0.60, Q4=0.80` block stays in place during Module 3 v1. Module 3 v2 deletes it once the contract bound work for `stage_ramp_contract.revenue_qoq_growth_target_min/max` is in place — at that point GPT receives the NAICS qoq band via the contract rather than via the prompt prose ceilings, and the prose can be removed without leaving GPT unbounded.

**Pacing rationale.** Module 3 v1 = one complete vertical slice (DDL → injection → populated → legacy deleted) with thorough tests. The pattern is now established. Module 3 v2 = the breadth pass (apply the pattern to the other 4-5 contracts and build the realism gate machinery). Splitting the module this way gives a credible commit boundary: v1 lands a real, tested behavior change (no more hardcoded 2-15 maintenance capex bound) that can roll back cleanly; v2 builds on a known-good foundation rather than a half-done one.
