# Module 6: Marketing Schedule Subsystem

**Status:** not_started
**Scope:** post-intake only.
**Depends on:** Module 1 (resolver), Module 3 (contract NAICS bound machinery + finalize realism gate).
**Unblocks:** none. Final realism module.

## Why this module

Marketing percent is currently a one-shot intake-time derivation in `_compute_marketing_model_json` / `_fallback_marketing_estimate`. It already does schedule-like math (reachable market → expected entities → capture rate → percent) but freezes a single annual percent rather than producing per-quarter driver values. Per master-diagnostic Part 13, promoting this to a real Q1-Q20 schedule subsystem parallel to payroll/debt/depreciation:

- Produces per-quarter marketing percent from audience × CAC math
- Eliminates one of the GPT-authored dimensions of `quarter_grid_openai`
- Captures stage-aware ramp behavior (high CAC pre-revenue, retention-heavy operating) deterministically
- Provides finalize realism check against NAICS marketing% band per stage
- **Preserves the chain exactly:** the schedule writes a `percent_of_revenue` driver row to `model_input_json` (same shape as today), not dollars. FINMO calc unchanged.

**Master-diagnostic references:**
- Part 13 (entire) — schedule design, comparison vs. today, chain fit, SQL registration, Excel workbook tab
- Part 8 (drivers → schedules → mapping → FINMO chain — preservation invariant)
- Part 12.6 — marketing is Tier D; intake never asks; post-intake derives

## Dependencies

- **M1 must be complete.** The schedule reads the resolver constantly for CAC, marketing%, advertising% bands.
- **M3 must be complete.** The finalize realism gate must catch out-of-band marketing percents the schedule produces; the gate framework is reused for the marketing band check.

## Pre-flight

- [ ] M1 + M3 at status `completed`. Both regression E2Es passing.
- [ ] Read master-diagnostic Part 13 (all sub-sections 13.1 through 13.11) end-to-end.
- [ ] Read `python/api_handlers/intake_consult.py:_compute_marketing_model_json` (line 3365) and `_fallback_marketing_estimate` (line 3205) to understand the existing audience-derivation chain.
- [ ] Read `python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py` and `python/client_intake_and_finmo/post_intake_headcount/schedule.py` to confirm the schedule subsystem shape (table-backed policy, deterministic math, writes driver rows, sidecar provenance payload).

## Task 6.1 — Build the marketing policy table

- [ ] Create new SQL table `post_intake_marketing_policy_lookup` per master-diagnostic Part 13.9. Columns:
  ```
  id BIGINT UNSIGNED PRIMARY KEY
  policy_code VARCHAR(64) NOT NULL UNIQUE                          -- 'default' initially
  model_input_driver VARCHAR(128) NOT NULL                         -- 'expenses::Marketing'
  schedule_storage_field VARCHAR(128) NOT NULL                     -- 'marketing_schedule' column in intake_consult_drafts
  forecast_horizon_quarters INT NOT NULL DEFAULT 20

  -- Audience and acquisition policy
  naics_marketing_metric_key VARCHAR(128) NOT NULL                 -- 'marketing_percent_of_revenue'
  naics_advertising_metric_key VARCHAR(128) NULL                   -- 'advertising_percent_of_revenue'
  naics_cac_back_derivation_method VARCHAR(64) NOT NULL            -- 'naics_marketing_pct_x_revenue_per_typical_acquisitions'
  repeat_units_per_entity_by_cadence_json LONGTEXT NOT NULL        -- replaces hardcoded 6 / 2.5 / 1.2 / 2.0
  churn_rate_default_by_business_model_json LONGTEXT NOT NULL      -- per business_model_pattern

  -- Stage modulation
  stage_cac_modifier_pre_revenue DECIMAL(10,4) NOT NULL DEFAULT 1.40
  stage_cac_modifier_early_operating DECIMAL(10,4) NOT NULL DEFAULT 1.10
  stage_cac_modifier_operating_scaling DECIMAL(10,4) NOT NULL DEFAULT 0.85
  stage_cac_modifier_mature DECIMAL(10,4) NOT NULL DEFAULT 1.00

  -- Override patterns for non-audience-driven business models
  business_model_pattern_overrides_json LONGTEXT NULL              -- e.g. {b2b_referral_dominant: {marketing_percent_min: 0.01, marketing_percent_max: 0.03}}

  -- Validation policy
  naics_band_confidence_tier_priority_json LONGTEXT NOT NULL       -- ordered: ['high', 'medium', 'low', 'generic_default']
  finalize_realism_band_kind VARCHAR(32) NOT NULL DEFAULT 'warn'   -- 'hard_fail' | 'warn' | 'skip_if_no_coverage'

  notes LONGTEXT NULL
  policy_status VARCHAR(32) NOT NULL DEFAULT 'active'
  created_at, updated_at
  ```
- [ ] Add table-ensure function. Add to `_post_intake_snapshot_source_tables()` (becomes the eighth frozen table).
- [ ] Populate the default row by migrating values from the existing hardcoded chain in `_fallback_marketing_estimate`:
  - `repeat_units_per_entity_by_cadence_json`: `{"weekly": {"b2c": 6.0, "b2b": 10.0}, "monthly": {"b2c": 2.5, "b2b": 6.0}, "annual": 1.2, "default": {"b2c": 2.0, "b2b": 3.0}}`
  - `churn_rate_default_by_business_model_json`: starts conservative — `{"b2c_subscription": 0.05, "b2c_transactional": 0.30, "b2b_recurring": 0.03, "b2b_project": 0.50, "default": 0.10}` (quarterly churn rates; tune empirically)
  - `business_model_pattern_overrides_json`: `{"b2b_referral_dominant": {"marketing_percent_floor": 0.01, "marketing_percent_ceiling": 0.03}, "professional_services_referral": {"marketing_percent_floor": 0.005, "marketing_percent_ceiling": 0.025}}`
- [ ] Add lookup function `post_intake_marketing_policy_lookup(policy_code='default')` returning the parsed row.

## Task 6.2 — Build the marketing schedule package

- [ ] Create new package `python/client_intake_and_finmo/post_intake_marketing_schedule/`
- [ ] Add `__init__.py` exporting the public functions
- [ ] Add `schedule.py` with three primary functions, parallel to `post_intake_debt_schedule/schedule.py`:
  ```python
  def build_marketing_schedule_plan(*, business_facts, marketing_model_json, financials_year1_json, model_input_json, finmo_payload, business_naics_6, business_stage, planning_mode, stage_ramp_contract) -> Dict[str, Any]:
      """Compute Q1-Q20 marketing schedule. Returns sidecar payload."""

  def apply_marketing_schedule_to_model_input(*, schedule_payload, model_input_json) -> Dict[str, Any]:
      """Write per-quarter marketing PERCENT to expenses::Marketing driver row."""

  def validate_marketing_schedule_band(*, schedule_payload, business_naics_6) -> List[Dict[str, Any]]:
      """Finalize-stage cross-check against NAICS marketing% band per quarter."""
  ```

## Task 6.3 — Implement the schedule math

Per master-diagnostic Part 13.3 / Part 13.6:

- [ ] **Inputs gathered from existing data:**
  - `reachable_market` (B2C, B2B, combined) — from `marketing_model_json` already populated by intake
  - `repeat_units_per_entity` — from policy table by `unit_cadence` and `market_basis_type`
  - `unit_price` — Tier A intake from ops_json
  - `quarterly_revenue_q1_to_q20` — from `model_input_json` revenue lever rows × stage ramp shape
  - `business_stage` — Tier B intake (computed from start_date)
  - `planning_mode` — post-intake-determined
  - `naics_marketing_band` — M1 resolver call with `metric_key="marketing_percent_of_revenue"`
  - `naics_typical_acquisitions_per_revenue` — derive from advertising/marketing % data per NAICS

- [ ] **Per quarter Q1-Q20 method:**
  ```
  required_entities_q = revenue_q / unit_price / repeat_units_per_entity
  retained_entities_q = entities_q-1 × (1 - churn_rate)            # Q1 retained = 0
  new_entities_q      = max(0, required_entities_q - retained_entities_q)
  required_acquisitions_q = new_entities_q / capture_conversion_rate
  cac_q = naics_cac_target × stage_cac_modifier(business_stage)
  marketing_dollars_q = required_acquisitions_q × cac_q
  marketing_percent_q = marketing_dollars_q / revenue_q
  ```

- [ ] **Sanity ceiling enforcement.** When `marketing_percent_q > naics_marketing_pct_max × tolerance`, flag with `acquisition_demand_exceeds_industry_band` and apply ceiling as the final value (the realism gate at 6.5 will surface the conflict).

- [ ] **Business model pattern overrides.** Before applying the formula, check if the business matches a pattern in `business_model_pattern_overrides_json` (e.g., B2B referral-dominant). When matched, override the formula output with the pattern's `marketing_percent_floor`/`ceiling` band.

- [ ] **CAC back-derivation.** Implement `naics_cac_target` as: when SEC EDGAR data has both marketing% and revenue/typical-acquisitions per NAICS → use directly; otherwise back-derive as `marketing_percent_target × revenue_per_typical_business / new_acquisitions_per_typical_business` from the data the registry provides. Document the back-derivation method in the sidecar payload.

## Task 6.4 — Sidecar provenance payload

Per master-diagnostic Part 13.3:

- [ ] Build a sidecar `marketing_schedule_payload` (parallel to `payroll_headcount_schedule` and `debt_schedule` payloads). Fields per quarter Q1-Q20:
  - `quarter_index`
  - `revenue_q`, `required_entities_q`, `retained_entities_q`, `new_entities_q`, `required_acquisitions_q`
  - `cac_q`, `marketing_dollars_q`, `marketing_percent_q`
  - `naics_marketing_band: {min, target, max}`, `naics_cac_band`
  - `stage_cac_modifier`, `business_model_pattern_override_applied` (or null)
  - `confidence_tier`, `naics_level_used`, `data_source`
  - `applicability_rule`, `in_band_flag`
- [ ] Persist the payload into `intake_consult_drafts.marketing_schedule` column (add the column if it doesn't exist).
- [ ] Make the payload available to the workbook export (Task 6.7).

## Task 6.5 — Wire the schedule into the sequence controller

Per master-diagnostic Part 13.9.A:

- [ ] Add three new rows to `post_intake_process_sequence_lookup`:
  - `post_intake_marketing_schedule_compose` (initial_grid phase, top-level), executor `compose_marketing_schedule`
  - `post_intake_marketing_schedule_apply` (initial_grid phase, child of compose), executor `apply_marketing_schedule_to_model_input`
  - `post_intake_marketing_schedule_finalize_check` (finalize phase, top-level), executor `validate_marketing_schedule_band`
- [ ] Each row populates `required_lookup_tables_json` (includes `post_intake_marketing_policy_lookup` and `post_intake_industry_baseline_lookup`), `required_context_keys_json` (`marketing_model_json`, `financials_year1_json`, `business_facts.naics`, `stage_ramp_contract`, etc. per Part 12.5), `produced_output_keys_json` (`marketing_schedule_payload`, model_input write to `expenses::Marketing`), `output_storage_json`, `output_finality`, `timeout_seconds`, `recompute_triggers_json`.
- [ ] Add corresponding rows to `post_intake_process_context_lookup` declaring each context key the schedule reads.
- [ ] Wire the runner side: `prepare_initial_grid_for_draft` calls the marketing compose step at the right point (after the payroll headcount schedule, before convergence). The finalize step runs in `run_finalize_post_intake_validation`.

## Task 6.6 — Apply to model_input as PERCENT (critical: same row shape as today)

Per master-diagnostic Part 13.5 — **the marketing driver row stays `percent_of_revenue` shape**. The schedule does dollars math internally and converts at the boundary.

- [ ] In `apply_marketing_schedule_to_model_input`, for each quarter Q1-Q20:
  - Read `marketing_percent_q` from the schedule payload (already a percent — `marketing_dollars_q / revenue_q`)
  - Write to the `expenses::Marketing` driver row in `model_input_json` at the corresponding quarter column
- [ ] **Do not write dollars.** Do not change the mapping-table formula on this row. Do not change FINMO calc. The percent driver row is consumed by FINMO's `percent_of_revenue` formula exactly as today.
- [ ] Replace the silent-zero substitution path from M1 Task 1.5 (which was the interim measure) with the schedule path. Document removal in the M1 file's "Notes from a future session" section.
- [ ] Add a guard: if M1's substitution path still fires for marketing in any code path, fail-fast with a "marketing schedule not run" diagnostic.

## Task 6.7 — Excel workbook tab

Per master-diagnostic Part 13.10:

- [ ] Read `python/client_statements_output_excel/export_client_workbook.py` to learn the existing schedule tab conventions (payroll, debt, depreciation tabs).
- [ ] Add a new "Marketing Schedule" tab parallel to those tabs. Sections per Part 13.10:
  - Header section (business name, NAICS, marketing_basis_type, reachable market totals, confidence_tier, naics_level, source data tag)
  - Inputs block Q1-Q20 (revenue per quarter linked from Model Inputs, required entities, retained, new entities required, required acquisitions, CAC per quarter, stage CAC modifier)
  - Computation block Q1-Q20 (marketing dollars per quarter, marketing percent per quarter, NAICS band check min/target/max, in-band flag)
  - Output block Q1-Q20 (`marketing_percent_of_revenue` per quarter — the cell linked into Model Inputs marketing driver row)
  - Provenance footer (NAICS CAC band, business model pattern override applied, confidence tier, data source, derivation formula, applicability rule)
- [ ] Match the layout convention used by the existing payroll / debt / depreciation schedule tabs. Operator-edit semantics: edit a cell on the schedule tab → Model Inputs updates by reference → FINMO recalculates.
- [ ] Add tab links: "Marketing Schedule" appears in the workbook nav bar; Model Inputs marketing row cells link to the schedule tab's output block.

## Task 6.8 — Realism gate integration

- [ ] In M3's `validate_industry_realism_bands` (or as a standalone validator wired in parallel), add the marketing-specific check:
  - Per quarter: produced `marketing_percent_q` against NAICS `marketing_percent_of_revenue` band
  - Year-1 aggregate: `sum(marketing_dollars_q1_to_q4) / sum(revenue_q1_to_q4)` against the band
- [ ] Use the policy row's `finalize_realism_band_kind` to decide warn vs. hard_fail. Initial mode: `warn`.
- [ ] Apply confidence-tier-aware tolerance from the policy row's `naics_band_confidence_tier_priority_json`.

## Task 6.9 — Schedule-vs-current divergence run (Phase 11a from master diagnostic)

Master-diagnostic Part 13.7 phase 11a: produce the schedule alongside the existing GPT marketing path; finalize gate runs both and warns on divergence. This is the data-gathering phase before the schedule becomes the source of truth.

- [ ] Add a feature flag (env var or sequence-row column) `marketing_schedule_authoritative TINYINT`. When `0`, the existing GPT path remains the source of truth and the schedule runs as a shadow producer logged for comparison. When `1`, the schedule writes to model_input.
- [ ] Run NexGen + ValueMart E2Es with flag at `0` and log the schedule-vs-GPT divergence per quarter. Confirm divergences are within reason (no order-of-magnitude differences).
- [ ] Run two more E2Es on diverse business types (a B2B services business and a B2C subscription business if drafts are available).
- [ ] Once divergences look reasonable across the four runs, flip the flag to `1` and re-run NexGen + ValueMart. Confirm both still produce `all_cleared`.

## Task 6.10 — Snapshot refresh

- [ ] After Task 6.9 confirms the schedule is authoritative without regressions, refresh `post_intake_lookup_table_snapshot`. The new policy table, the new sequence rows, and the new context rows all go into the snapshot.

## Files Touched

- `python/client_intake_and_finmo/post_intake_marketing_schedule/schedule.py` (new)
- `python/client_intake_and_finmo/post_intake_marketing_schedule/__init__.py` (new)
- `python/client_intake_and_finmo/post_intake_mapping.py` (new policy table DDL, new sequence rows, new context rows, snapshot source list)
- `python/client_intake_and_finmo/post_intake_initial_grid/runner.py` (call the new schedule compose/apply steps)
- `python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py` (wire the band check)
- `python/client_intake_and_finmo/finmo_bridge.py` (remove the M1 marketing silent-zero path now that schedule owns it)
- `python/client_statements_output_excel/export_client_workbook.py` (new tab)
- `intake_consult_drafts` schema (add `marketing_schedule` column)

## Files NOT Touched

- The intake-side `_compute_marketing_model_json` and `_fallback_marketing_estimate` stay — they still compute the audience reach inputs the schedule consumes. The schedule replaces what these functions produced (the single annual percent), not what they consumed.
- The model_input `expenses::Marketing` driver row shape — unchanged. Still `percent_of_revenue`.
- The mapping table formula on the marketing row — unchanged.
- FINMO calc — unchanged.
- Stub 0 — never written by schedule.
- Payroll, debt, depreciation schedules — untouched. Marketing is parallel.
- Sequence controller — adds rows; does not modify controller behavior.

## Verification

- [ ] All Task 6.x checkboxes complete (including Task 6.9's divergence runs)
- [ ] NexGen Software E2E with `marketing_schedule_authoritative = 1` passes with `all_cleared`
- [ ] ValueMart Superstores E2E passes
- [ ] Workbook output includes the Marketing Schedule tab with all sections populated; Model Inputs marketing row cells link to the schedule tab
- [ ] Synthetic test: a B2B referral-dominant business hits the `business_model_pattern_overrides` and produces a low marketing percent (1-3%) regardless of audience math
- [ ] Synthetic test: a pre-revenue startup produces higher Q1-Q4 marketing percent than Q17-Q20 (stage CAC modifier doing its job)
- [ ] Synthetic test: a NAICS with sparse marketing% coverage falls through to generic_default and the realism gate logs the lower confidence tier
- [ ] Snapshot refreshed; preflight green
- [ ] Marketing percent values per quarter visible in the workbook are within NAICS band for the test cases

## Exit Criteria

- All Task checkboxes complete
- Both regression E2Es pass with the schedule authoritative
- Workbook tab renders correctly across diverse intakes
- Pattern overrides and stage modifiers behave as expected on synthetic tests
- Realism gate catches out-of-band marketing percents
- Index file Status updated: M6 = `completed`

## Risk Notes

- **Churn rate is the biggest unknown.** The initial defaults (5% B2C subscription, 3% B2B recurring, 30% B2C transactional, 50% B2B project, 10% default) are educated guesses. The schedule output is sensitive to churn — high churn → high required acquisitions → high marketing percent. Mark all churn defaults with `confidence_tier = "low"` in the policy table notes; tune empirically.
- **CAC back-derivation circularity.** The clean break: when SEC EDGAR data permits direct CAC derivation, use it; otherwise back-derive carefully and document the method. Don't let CAC depend on acquisitions which depend on CAC.
- **Audience-driven model breaks for some industries.** Software with viral organic growth, restaurants in tourist locations, professional services with referral-only acquisition. The `business_model_pattern_overrides_json` is the escape hatch; populate it carefully for known patterns.
- **The percent boundary is critical.** Model_input gets a percent. The mapping table formula expects a percent. FINMO calc expects a percent. If the schedule ever writes dollars to the marketing driver row, the entire chain misbehaves. Code-review this carefully.
- **Existing E2Es will produce different marketing numbers.** Both passing E2Es from 2026-05-05 had GPT-authored marketing. The schedule will produce different per-quarter values. Task 6.9's divergence run is exactly to surface this and confirm the new numbers are reasonable.
- **Don't promote `finalize_realism_band_kind` to `hard_fail` immediately.** Run in `warn` mode for several E2Es first; only flip to hard_fail after confirming no false positives.

## Notes from a future session

(Empty.)
