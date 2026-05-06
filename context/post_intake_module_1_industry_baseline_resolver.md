# Module 1: Industry Baseline Resolver + Producer-Side Substitution

**Status:** not_started
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

- [ ] Create new package directory `python/client_intake_and_finmo/post_intake_industry_baseline/`
- [ ] Add `__init__.py` exporting the resolver function
- [ ] Add `lookup.py` with the public function:
  ```python
  def post_intake_industry_baseline_for_naics(
      *, metric_key: str, naics_6: str
  ) -> Dict[str, Any]:
      ...
  ```
- [ ] Implement the cascade walk: 6 → 5 → 4 → 3 → 2 → 0 (`generic_default`) → `no_coverage`
  - At each level, query: `SELECT benchmark_min, benchmark_target, benchmark_max, confidence_tier, data_source, sample_size, naics_level FROM post_intake_industry_baseline_lookup WHERE metric_key = ? AND naics_code = ? AND naics_level = ? AND active = 1 ORDER BY confidence_tier ASC, sample_size DESC LIMIT 1`
  - Stop at the first hit; truncate `naics_6` to the level being queried (`naics_6[:5]`, etc.); use `'*'` for level 0
- [ ] Return payload: `{benchmark_min, benchmark_target, benchmark_max, naics_code_used, naics_level_used, data_source, source_year, sample_size, confidence_tier, trust_flag, fallback_chain_attempted}`
- [ ] Implement confidence-tier downgrade per cascade level (high resolved at NAICS-3 fallback → medium; capped at low at NAICS-3; capped at low at NAICS-2; `generic_default` at L0)
- [ ] Add `trust_flag` enum: `naics_6_direct | naics_5_fallback | naics_4_fallback | naics_3_fallback | naics_2_fallback | generic_default | no_coverage`
- [ ] Read `post_intake_industry_metric_registry` lookup (cache it on first call — only 49 rows). Expose `fail_if_no_coverage` flag. When `no_coverage` and registry says `fail_if_no_coverage = 1`, raise `RuntimeError("post_intake_industry_baseline_no_coverage: metric_key={...} naics_6={...} fallback_chain_attempted={...}")`.
- [ ] Add helper `post_intake_industry_metric_governs_lever(metric_key) -> Optional[str]` returning the `governs_model_input_lever` field for substitution callers.

## Task 1.2 — Resolver unit tests

- [ ] Create `Test Files/test_industry_baseline_resolver.py`
- [ ] Test ValueMart NAICS 455211 cascade for these documented cases:
  - `effective_tax_rate` resolves to NAICS-5 IRS_SOI, sample_size 12,226, confidence_tier high (downgrades to medium because resolved at L5)
  - `cogs_percent_of_revenue` resolves to NAICS-6 industry_metrics_raw, sample_size 78, confidence_tier high (stays high at L6 direct)
  - `payroll_percent_of_revenue` resolves to L0 generic_default, expert_default
  - `avg_wage_per_fte` resolves to NAICS-3, BLS_OEWS
- [ ] Test NexGen software NAICS 511210 cascade for at least:
  - `deferred_revenue_percent_of_revenue` (SEC EDGAR, n>=200 expected)
  - `marketing_percent_of_revenue` (SEC EDGAR)
  - `sga_percent_of_revenue`
- [ ] Test confidence-tier downgrade: a high-confidence NAICS-6 metric resolved via the NAICS-3 cascade should report `confidence_tier = medium` (or low at L3+).
- [ ] Test `no_coverage` path: pick a metric with sparse coverage and a NAICS that misses every level. Confirm payload returns `trust_flag = "no_coverage"`. Confirm `fail_if_no_coverage = 1` raises.
- [ ] Test caching of the metric registry: assert only one DB query for the registry across multiple resolver calls.
- [ ] Test idempotence: same `(metric_key, naics_6)` returns identical payload on repeat calls.

## Task 1.3 — Wire `cogs_percent_of_revenue` substitution

- [ ] Edit `python/client_intake_and_finmo/finmo_bridge.py:324-341` (`_cogs_ratio_from_financials`): when both explicit ratio and dollar-derived ratio are missing or zero, call resolver with `metric_key="cogs_percent_of_revenue"` and `naics_6` from business context. Use `benchmark_target`. Carry provenance.
- [ ] Edit `python/client_intake_and_finmo/quarter_grid.py:107-121` (`_cogs_dollars_from_financials`): same substitution pattern when revenue > 0 and ratio is None.
- [ ] Add a small provenance helper that returns the seed metadata dict: `{seed_source: "naics_cascade", metric_key, naics_level_used, confidence_tier, data_source, sample_size}`.
- [ ] Pass provenance through to the model_input driver row metadata so the workbook can surface it.
- [ ] **Stub 0 unchanged.** Substitution applies to forecast Q1-Q20 only.

## Task 1.4 — Wire AR / AP / inventory substitution

- [ ] Edit `python/client_intake_and_finmo/finmo_bridge.py:3470` (`ar_balance_seed`): when intake omitted AR balance and live revenue exists, compute `ar_balance_q = revenue_q × (ar_days_dso / 90)` from resolver `metric_key="ar_days_dso"`. Apply per quarter.
- [ ] Edit `python/client_intake_and_finmo/finmo_bridge.py:3472` (`ap_balance_seed`): when intake omitted AP balance and operating expense base exists, compute `ap_balance_q = expense_base_q × (ap_days_dpo / 90)` from resolver `metric_key="ap_days_dpo"`.
- [ ] Edit `python/client_intake_and_finmo/finmo_bridge.py:3471` (`inventory_balance_seed`): when intake omitted inventory and inventory applies (NAICS-2 applicability check — see Task 1.7), compute `inventory_balance_q = cogs_q × (inventory_days / 90)` from resolver.
- [ ] Edit the matching seed sites at `finmo_bridge.py:1808-1810`, `finmo_bridge.py:3586-3597` for parallel patterns.
- [ ] **Stub 0 unchanged.** Substitution applies to forecast Q1-Q20 only.
- [ ] **Tier A intake values win.** When intake gave a non-zero AR / AP / inventory at stub 0, the forecast walks from that anchor — not from the NAICS substitution (per Part 9.1 / 10.3).

## Task 1.5 — Wire marketing% and taxes% substitution

- [ ] Edit `python/client_intake_and_finmo/finmo_bridge.py:946-948, 3364-3368, 3410, 3447` (marketing seed paths): when all explicit sources are None, call resolver with `metric_key="marketing_percent_of_revenue"` and use `benchmark_target`. Carry provenance.
- [ ] Edit `python/client_intake_and_finmo/finmo_bridge.py:970, 3461` (taxes seed paths): when `taxes_percent` is None, call resolver with `metric_key="effective_tax_rate"`. Carry provenance.
- [ ] Note: marketing % will be replaced by the marketing schedule in Module 6. This wiring is the interim path that prevents silent zeros until M6 lands. Document in code comment: `# replaced by marketing schedule in Module 6`.

## Task 1.6 — Wire deferred revenue and prepaid expenses (Tier D — never asked at intake)

- [ ] Identify the seed sites for deferred revenue and prepaid expenses in the `post_intake_balance_sheet/contextual_seed.py` flow.
- [ ] Add NAICS substitution: `deferred_revenue_balance_q = revenue_q × deferred_revenue_percent_of_revenue` and `prepaid_balance_q = revenue_q × prepaid_expenses_percent_of_revenue`.
- [ ] Apply the applicability check (Task 1.7) before substituting deferred revenue.
- [ ] Both metrics are CLOSED via SEC EDGAR (n=745 and n=827 respectively) — confidence is medium at NAICS-2/3.

## Task 1.7 — Build the NAICS-2 applicability lookup

- [ ] Per master diagnostic Part 9.1: distinguish "stub 0 = 0 because client legitimately has none" (legitimate zero) from "stub 0 = 0 because client omitted" (silent zero). The decision is the applicability check.
- [ ] Create a small lookup function `post_intake_baseline_applicability_for_naics2(metric_key, naics_2) -> {applicable: bool, reason: str, confidence: str}`.
- [ ] Initial table-backed defaults (could be code constants for now, table later):
  - `inventory_days`: NAICS-2 sectors 31-33 (Manufacturing), 42 (Wholesale), 44-45 (Retail), 72 (Accommodation/Food) → applicable
  - `deferred_revenue_percent_of_revenue`: NAICS-2 sectors 51 (Information), 54 (Professional/Scientific/Technical), 53 (Real Estate), 52 (Finance/Insurance) → applicable; sectors 44/45/72/81 → not_applicable; everything else → optional (defer to GPT tiebreaker eventually, default applicable=False for now)
  - `r_and_d_percent_of_revenue`: NAICS-2 sectors 51, 54, 32-33 (Manufacturing of pharma/industrial/computer/transportation) → applicable; consumer-facing sectors → not_applicable
- [ ] When applicability is `not_applicable`, do not substitute; keep the value at zero (legitimate zero).

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

- [ ] All Task 1.x checkboxes complete
- [ ] `Test Files/test_industry_baseline_resolver.py` passes
- [ ] NexGen Software E2E still passes (`all_cleared`, `remaining_issue_count = 0`, runtime within 20% of baseline)
- [ ] ValueMart Superstores E2E still passes
- [ ] **New synthetic E2E with deliberately sparse intake** (a draft where AR / AP / marketing / taxes / deferred revenue are explicitly null in financials_json): confirm `model_input_json` Q1-Q20 has non-zero NAICS-cascaded seeds for those drivers. Confirm `seed_source = "naics_cascade"` provenance is present.
- [ ] Run `scripts/post_intake_golden_preflight.py` — confirm no snapshot drift (Module 1 should not change any of the seven frozen lookup tables).

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

(Leave this section empty. Add findings, surprises, or cleanup items here as Module 1 work progresses. These notes feed back into the master diagnostic on completion.)
