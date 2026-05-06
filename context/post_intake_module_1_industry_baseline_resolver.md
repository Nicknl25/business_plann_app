# Module 1: Industry Baseline Resolver + Producer-Side Substitution

**Status:** in_progress (Stages A + B complete: Tasks 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7. Verification step pending — focused integration test green; full E2E regression deferred to a later session per user direction.)
**Scope:** post-intake only.
**Depends on:** none. This is the foundation.
**Unblocks:** Modules 2, 3, 5, 6.

## Why this module

Forty-seven thousand seven hundred NAICS-keyed benchmark rows for 49 metrics exist in `post_intake_industry_baseline_lookup` — and **zero runtime call sites read them today**. Until the resolver exists and the four silent-zero sites are wired to it, every business that doesn't volunteer COGS / AR / AP / marketing / taxes via intake produces an unrealistic plan ($10M retail superstore emitting $0 taxes, etc.). This is the largest realism win available at the lowest regression risk: the substitution only fires when intake omitted a value, so the two passing E2Es with complete-enough intakes won't be affected.

**Master-diagnostic references to read before starting:**
- Part 1.4 — the four silent-zero sites
- Part 5 Phase 0 + Phase 1 — resolver design and substitution wiring
- Part 9.1 — stub 0 invariant (substitution writes Q1+ only, never stub 0)
- Part 12.5, 12.6 — what intake actually captures vs. what's Tier D
- Master diagnostic §"Industry Baseline Lookup System" coverage cascade contract

## Dependencies

None. Foundation module.

## Pre-flight (do these before opening any code)

- [ ] Run NexGen Software E2E (source draft `d087c44e0aa544eea869d7ab3f7a4f66` or equivalent) and confirm `all_cleared` + `remaining_issue_count = 0`. Record timestamp and final draft id.
- [ ] Run ValueMart Superstores E2E and confirm `all_cleared` + `remaining_issue_count = 0`. Record timestamp and final draft id.
- [ ] Confirm `post_intake_industry_baseline_lookup` has 47,700 rows (`SELECT COUNT(*) FROM post_intake_industry_baseline_lookup WHERE active = 1`).
- [ ] Confirm `post_intake_industry_metric_registry` has 49 rows.
- [ ] Run `Test Files/_verify_baseline_tables.py` against ValueMart NAICS 455211 — confirm cascade resolves as documented in master diagnostic §"Concrete cascade example".
- [ ] Read master-diagnostic Parts 1.4, 5 (Phase 0-1), 9.1, 12.5, 12.6, and §"Industry Baseline Lookup System".

## Task 1.1 — Build the resolver package

- [x] Create new package directory `python/client_intake_and_finmo/post_intake_industry_baseline/`
- [x] Add `__init__.py` exporting the resolver function
- [x] Add `lookup.py` with the public function:
  ```python
  def post_intake_industry_baseline_for_naics(
      *, metric_key: str, naics_6: str
  ) -> Dict[str, Any]:
      ...
  ```
- [x] Implement the cascade walk: 6 → 5 → 4 → 3 → 2 → 0 (`generic_default`) → `no_coverage`
  - At each level, query: `SELECT benchmark_min, benchmark_target, benchmark_max, confidence_tier, data_source, sample_size, naics_level FROM post_intake_industry_baseline_lookup WHERE metric_key = ? AND naics_code = ? AND naics_level = ? AND active = 1 ORDER BY confidence_tier ASC, sample_size DESC LIMIT 1`
  - Stop at the first hit; truncate `naics_6` to the level being queried (`naics_6[:5]`, etc.); use `'*'` for level 0
  - **Implementation note:** L6 is filtered additionally to `data_source = registry.primary_source AND confidence_tier IN (high, medium)` per the system overview cascade contract. Without this filter, the L6-direct condition would trip on any data source (e.g., alpha_data L6 for effective_tax_rate at NAICS 455211, n=151) and the L5 IRS_SOI authoritative coverage (n=12,226) would be skipped. The contract / test expectation for `effective_tax_rate` requires this filter.
- [x] Return payload: `{benchmark_min, benchmark_target, benchmark_max, naics_code_used, naics_level_used, data_source, source_year, sample_size, confidence_tier, trust_flag, fallback_chain_attempted}` — payload also includes `raw_confidence_tier` (pre-downgrade) and `metric_key` for caller convenience.
- [x] Implement confidence-tier downgrade per cascade level (high resolved at NAICS-3 fallback → medium; capped at low at NAICS-3; capped at low at NAICS-2; `generic_default` at L0)
- [x] Add `trust_flag` enum: `naics_6_direct | naics_5_fallback | naics_4_fallback | naics_3_fallback | naics_2_fallback | generic_default | no_coverage`
- [x] Read `post_intake_industry_metric_registry` lookup (cache it on first call — only 49 rows). Expose `fail_if_no_coverage` flag. When `no_coverage` and registry says `fail_if_no_coverage = 1`, raise `PostIntakeIndustryBaselineNoCoverage("post_intake_industry_baseline_no_coverage: metric_key={...} naics_6={...} fallback_chain_attempted={...}")`. (Subclass of `RuntimeError` so generic except-RuntimeError still catches; specific class so callers can selectively handle.)
- [x] Add helper `post_intake_industry_metric_governs_lever(metric_key) -> Optional[str]` returning the `governs_model_input_lever` field for substitution callers.

## Task 1.2 — Resolver unit tests

- [x] Create `Test Files/test_industry_baseline_resolver.py`
- [x] Test ValueMart NAICS 455211 cascade for these documented cases:
  - [x] `effective_tax_rate` resolves to NAICS-5 IRS_SOI, sample_size 12,226, raw_confidence_tier high (downgrades to medium because resolved at L5)
  - [x] `cogs_percent_of_revenue` resolves to NAICS-6 industry_metrics_raw, sample_size 78, confidence_tier high (stays high at L6 direct)
  - [x] `payroll_percent_of_revenue` resolves to L2 (current data: derived_CBP_SOI_rollup) OR L0 generic_default — see Notes section. Test asserts contract behavior, not a frozen numeric.
  - [x] `avg_wage_per_fte` resolves to NAICS-3, BLS_OEWS (capped at low at L3)
- [x] Test NexGen software NAICS 511210 cascade for at least:
  - [x] `deferred_revenue_percent_of_revenue` (resolves at NAICS-fallback or generic_default)
  - [x] `marketing_percent_of_revenue` (SEC EDGAR or expert_default)
  - [x] `sga_percent_of_revenue`
- [x] Test confidence-tier downgrade rules table (high → medium at L4-L5; high → low at L2-L3; generic_default at L0).
- [x] Test `no_coverage` path: monkey-patched query returns None at every level; confirm payload returns `trust_flag = "no_coverage"`. Confirm `fail_if_no_coverage = 1` raises `PostIntakeIndustryBaselineNoCoverage`.
- [x] Test caching of the metric registry: `lru_cache.cache_info()` reports hits ≥ 2, misses = 1 across 3 calls.
- [x] Test idempotence: same `(metric_key, naics_6)` returns identical payload on repeat calls.
- [x] Result: 17/17 pass against live DB.

## Task 1.3 — Wire `cogs_percent_of_revenue` substitution

- [x] Edit `python/client_intake_and_finmo/finmo_bridge.py:324-341` (`_cogs_ratio_from_financials`): kept intake-only behavior. Substitution moved to the call site in `_build_model_input_overlay` so stub 0 (= intake fact) cannot be touched.
- [x] Edit `python/client_intake_and_finmo/quarter_grid.py:107-121` (`_cogs_dollars_from_financials`): NAICS substitution fires when both explicit ratio and dollar value are missing/zero AND `ops_json.business_naics_6` is present. Threaded `ops_json` through `_build_baseline_financial_summary` callers.
- [x] Added `baseline_seed_provenance(payload)` helper in `post_intake_industry_baseline.lookup` (returns the `{seed_source, metric_key, naics_level_used, confidence_tier, data_source, sample_size, trust_flag}` dict).
- [x] Provenance is attached to the model_input row under `row["seed_provenance_json"][metric_key]` for "Cost of Goods Sold", "Marketing", "Taxes", "Accounts Receivable Days", "Accounts Payable Days", "Inventory Days", "Prepaid Expenses (% of Revenue)", "Deferred Revenue (% of Revenue)".
- [x] **Stub 0 unchanged.** Substitution applies to forecast Q1-Q20 only — verified by `test_stub_zero_invariant_preserved_for_all_substituted_rows`.
- [x] Substitution covers both `projection_mode = False` (uses `cogs_ratio_forecast` directly) and `projection_mode = True` (falls back when slot.cogs is 0 — i.e., when the quarter grid plan also failed to fill it).

## Task 1.4 — Wire AR / AP / inventory substitution

- [x] Substitution wired at the live-row level (where Days values are stored), not at the schedule seed (= stub-0 anchor). The seed at `_build_model_input_overlay`:3594-3596 keeps the intake balance for stub 0; forecast Q1-Q20 days come from the resolver when applicability allows.
- [x] AR Days: when `working_capital.dso` is None AND `ar_balance_seed = 0` AND `revenue > 0` → use NAICS `ar_days_dso` target directly as the days value.
- [x] AP Days: same pattern using `ap_days_dpo` target, gated by `ap_expense_base > 0` (forecast operating expenses must exist for AP to be a meaningful concept).
- [x] Inventory Days: gated by `cogs > 0` AND NAICS-2 applicability check — software / professional-services NAICS sectors (which legitimately have no inventory) are NOT substituted, preserving the legitimate-zero distinction from Part 9.1.
- [x] No edits at the legacy `1808-1810` site — that function reads from the schedule seeds (= stub 0) and early-returns when seeds are 0; my live-row substitution doesn't touch it. Schedule seeds remain at intake values per Part 9.1.
- [x] **Tier A intake values win.** The substitution path is the LAST fallback — explicit `working_capital.dso/dpo/inventory_days` and intake-derived `(seed/revenue) × 90` both override the NAICS substitution when present.
- [x] Verified by `test_valuemart_ar_days_substituted`, `test_valuemart_inventory_substituted`, and `test_software_inventory_NOT_substituted_legitimate_zero`.

## Task 1.5 — Wire marketing% and taxes% substitution

- [x] Marketing: substituted in `_build_model_input_overlay` for both stub-row override and live-row forecast. The dead `_operating_anchor_baseline_inputs` (line 925, has no callers anywhere in the codebase per `grep -rn _operating_anchor_baseline_inputs python/`) was NOT touched — wasted effort. Inline comment notes this is replaced by Module 6 marketing schedule.
- [x] Taxes: substituted via a new `tax_rate_forecast` variable used in both stub and forecast paths. `intake_tax_rate` (the intake-derived value) is preserved separately for traceability.
- [x] Note: marketing % will be replaced by the marketing schedule in Module 6 — code comment `# NOTE: replaced by marketing schedule in Module 6` placed inline at the substitution site.
- [x] Verified by `test_valuemart_marketing_substituted_in_forecast` and `test_valuemart_taxes_substituted_in_forecast`.

## Task 1.6 — Wire deferred revenue and prepaid expenses (Tier D — never asked at intake)

- [x] Discovered that `post_intake_balance_sheet/contextual_seed.py` is the GPT-decided seed module (Module 5's reduction territory) — the actual silent-zero in the live model_input output is at `_build_model_input_overlay` lines 3516-3535 (the "Prepaid Expenses (% of Revenue)" and "Deferred Revenue (% of Revenue)" balance-sheet rows). Substitution wired there.
- [x] Prepaid: forecast values use `prepaid_expenses_percent_of_revenue` resolver target as the % directly (the row stores the percent ratio, not a balance — finmo applies the percent × revenue downstream).
- [x] Deferred revenue: gated by both `_deferred_revenue_applicable(ops_json, financials_json)` (existing business-text gating) AND the new NAICS-2 applicability check from Task 1.7. Information / Professional-Services / RE / Finance NAICS-2 sectors substitute; retail / accommodation-food / personal-services do not (legitimate zero).
- [x] Both metrics are CLOSED via SEC EDGAR (n=745 and n=827 respectively); confidence is medium at NAICS-2/3 per the cascade downgrade rules.

## Task 1.7 — Build the NAICS-2 applicability lookup

- [x] Per master diagnostic Part 9.1: distinguish "stub 0 = 0 because client legitimately has none" (legitimate zero) from "stub 0 = 0 because client omitted" (silent zero). The decision is the applicability check.
- [x] Create a small lookup function `post_intake_baseline_applicability_for_naics2(metric_key, naics_2) -> {applicable: bool, reason: str, confidence: str}`.
- [x] Initial table-backed defaults (code constants for now, table later):
  - `inventory_days`: NAICS-2 sectors 31-33 (Manufacturing), 42 (Wholesale), 44-45 (Retail), 72 (Accommodation/Food) → applicable
  - `deferred_revenue_percent_of_revenue`: NAICS-2 sectors 51 (Information), 54 (Professional/Scientific/Technical), 53 (Real Estate), 52 (Finance/Insurance) → applicable; sectors 44/45/72/81 → not_applicable; everything else → applicable=False (conservative default)
  - `r_and_d_percent_of_revenue`: NAICS-2 sectors 51, 54, 32-33 (Manufacturing of pharma/industrial/computer/transportation) → applicable; consumer-facing sectors → not_applicable
- [x] When applicability is `not_applicable`, do not substitute; keep the value at zero (legitimate zero). _Wiring step in Tasks 1.4/1.6._
- [x] Metrics without applicability gating (e.g., cogs_percent_of_revenue) return `applicable=True, reason="metric_has_no_applicability_gate"` so callers can apply the resolver unconditionally.

## Files Touched (expected)

- `python/client_intake_and_finmo/post_intake_industry_baseline/__init__.py` (new)
- `python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py` (new)
- `python/client_intake_and_finmo/finmo_bridge.py` (edit 6+ silent-zero sites)
- `python/client_intake_and_finmo/quarter_grid.py` (edit COGS site at 107-121)
- `python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py` (deferred revenue / prepaid wiring)
- `Test Files/test_industry_baseline_resolver.py` (new)

## Files NOT Touched (Golden Rule preservations)

- Mapping table formula registry (`post_intak_mapping_lookup`, `post_intake_driver_formulas.py`) — unchanged
- Payroll schedule (`post_intake_headcount/`) — unchanged. Exact OEWS titles preserved.
- Debt schedule (`post_intake_debt_schedule/`) — unchanged. `amortizing_remaining_balance` preserved.
- Sequence controller (`post_intake_sequence.py`) — unchanged
- Stub 0 (`model_input_json[0]` quarter column) — never written by Module 1
- FINMO calc (`build_python_finmo_json`) — drivers in, statements out, no patch
- The `balance_sheet_contextual_seed` GPT call itself — Module 1 only fills the silent-zero substitution path; the GPT call's reduction is Module 5's job

## Verification

- [x] All Task 1.x checkboxes complete
- [x] `Test Files/test_industry_baseline_resolver.py` passes (17/17)
- [x] `Test Files/test_module1_substitution_wiring.py` passes (9/9) — focused integration test that calls `build_python_model_input_json` directly with synthetic sparse intake and verifies forecast Q1-Q20 carry NAICS-cascaded values + provenance, while stub 0 stays at the intake value.
- [ ] **DEFERRED**: NexGen Software + ValueMart Superstores full E2Es (post-intake pipeline currently fragile per user direction; full E2E regression run will happen in a later session).
- [ ] **DEFERRED**: Sparse-intake synthetic E2E (the focused integration test above demonstrates the substitution behavior; a full pipeline run is deferred to the post-intake stabilization session).
- [ ] **DEFERRED**: `scripts/post_intake_golden_preflight.py` snapshot check.

## Exit Criteria

- All Task checkboxes complete
- All Verification items checked
- Both regression E2Es pass with `all_cleared`
- Sparse-intake synthetic E2E demonstrates substitution working with provenance carrying through to the workbook
- No silent zeros remain at the four named sites and the deferred/prepaid sites
- Index file Status updated: M1 = `completed`

## Risk Notes

- **Producer-side only.** Substitution fires when intake omitted the value. Both 2026-05-05 E2Es had complete-enough intakes; the new path won't fire on them. Regression risk on passing E2Es is approximately zero.
- **Stub 0 is sacred.** Every substitution writes only Q1-Q20. Verify in code review.
- **Provenance must propagate.** If `seed_source` and `naics_level_used` don't reach the workbook output, Module 3's finalize realism gate will flag every NAICS-substituted cell as missing provenance. Make sure the model_input metadata path is wired through.
- **The applicability check is conservative.** When in doubt for an ambiguous NAICS-2 sector, default to `not_applicable` (legitimate zero) rather than `applicable` (substitute). It's safer to leave a zero than to invent a non-zero value for a business where the metric doesn't apply.
- **Marketing substitution is interim.** Module 6's marketing schedule replaces this wiring. Document the temporary nature in code comments so M6 work knows where to remove the substitution path.

## Notes from a future session

### 2026-05-06 — Stages A + B landed (Tasks 1.1-1.7)

**Files added / changed:**
- (new) `python/client_intake_and_finmo/post_intake_industry_baseline/` — resolver package (Stage A)
- (new) `Test Files/test_industry_baseline_resolver.py` — 17/17 pass
- (new) `Test Files/test_module1_substitution_wiring.py` — 9/9 pass
- `python/client_intake_and_finmo/finmo_bridge.py` — wired all 6 silent-zero substitution sites (COGS%, marketing%, taxes%, AR/AP/inventory days, prepaid%, deferred revenue%); added `_naics_6_from_ops`, `_naics_substitute_ratio`, `_attach_seed_provenance`; resolver imports
- `python/client_intake_and_finmo/quarter_grid.py` — wired `_cogs_dollars_from_financials` substitution; threaded `ops_json` through `_build_baseline_financial_summary` callers
- `context/post_intake_master_diagnostic_2026-05-05.md` — Phase 0 description updated with the L6 filter clarification

**Substitution architecture summary:**
- Stub 0 (period[0] of every model_input row) stays at the intake-derived value. Verified by an explicit invariant test.
- Forecast Q1-Q20 substitute when intake omitted AND applicability allows AND a NAICS coverage cascade returns a non-zero `benchmark_target`. The applicability check (Task 1.7) prevents legitimate zeros (e.g., software-business inventory) from being silently filled.
- Each substituted row gets `row["seed_provenance_json"][metric_key] = {seed_source: "naics_cascade", metric_key, naics_code_used, naics_level_used, confidence_tier, data_source, sample_size, trust_flag}`. Module 3's finalize realism gate consumes this.
- Substitution fires both in non-projection mode (overlay-only path) AND in projection mode (when the quarter-grid plan failed to fill the slot value). The latter case is what catches silent zeros that flow through the GPT plan output.

**Two findings worth recording for future sessions:**
1. `_operating_anchor_baseline_inputs` ([finmo_bridge.py:925](../python/client_intake_and_finmo/finmo_bridge.py#L925)) is dead code — it is defined but never called anywhere in `python/`. The Module 1 spec referenced lines 945-948 and 970 as silent-zero sites; those line numbers correspond to the dead function. The active sites are inside `_build_model_input_overlay`. Worth deleting on a cleanup pass; not urgent. Module 5 (GPT reductions) is a natural opportunity.
2. The bypass technique used by `test_module1_substitution_wiring.py` (monkey-patching `apply_derived_driver_policies_to_model_input` to a passthrough) is needed because that downstream stage requires a fully-populated capacity spec the test does not provide. If a future test wants to exercise the full overlay including derived-driver enforcement, it needs realistic capacity / unit-price / utilization in the forecast slots.

### 2026-05-06 — Stage A landed (Tasks 1.1, 1.2, 1.7)

**Files created:**
- `python/client_intake_and_finmo/post_intake_industry_baseline/__init__.py`
- `python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py`
- `Test Files/test_industry_baseline_resolver.py` (17/17 pass against live DB)

**Cascade-contract clarification.** The Module spec described L6 selection as a simple `ORDER BY confidence_tier ASC, sample_size DESC LIMIT 1`. That is incomplete. The resolver implements the system overview cascade contract: L6 is filtered to `data_source = registry.primary_source AND confidence_tier IN (high, medium)` so a non-primary L6 row (e.g., alpha_data L6 for `effective_tax_rate` at NAICS 455211, n=151, high) does NOT short-circuit the authoritative L5 IRS_SOI row (n=12,226). The Module's own test expectation for `effective_tax_rate` only passes with this filter applied. Clarification added inline to the Task 1.1 checklist; consider porting the same wording back into the master diagnostic Part 5 Phase 0 if a future edit pass touches that section.

**Stale Module test expectation: `payroll_percent_of_revenue`.** The Module spec said this metric resolves to L0 generic_default for NAICS 455211. After the 2026-05-05 gap-fill load, L2 (NAICS '45') has a `derived_CBP_SOI_rollup` row (target=0.276, n=1.5M, medium → capped at low at L2). The cascade now stops there. The unit test asserts the contract behavior (`trust_flag in {naics_2_fallback, generic_default}`) rather than a frozen value, so it stays green when future gap-fill runs add or remove L2 coverage.

**Open items for Stage B (wiring).** The COGS / AR / AP / inventory / marketing / taxes / deferred-revenue / prepaid sites are still untouched. Stage A added the resolver and applicability lookup but did not wire them. Tasks 1.3-1.6 remain.

**Pre-flight E2E baseline.** Skipped re-running NexGen + ValueMart E2Es; the 2026-05-05 commit `a1c43ac` is the recorded baseline. Stage D will re-run both to verify no regression after wiring.
