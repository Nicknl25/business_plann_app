# Phase 9 Realism Audit — ExpressLogix Test Run

**Run timestamp:** 2026-05-09 11:41 (local)
**Source draft:** `4fd50ce10bc4421898a5523b45b2fc0e` (ExpressLogix Shipping Services, NAICS 488)
**Cloned draft (this run):** `398986f44cec43589a0db2ac001d4a03`
**Planning run id:** `aa20a7c1afac429b9c21bbc38a003c4c`
**Gate version:** `phase_9_g_v1`
**Audit commits validated:** `10964fe` → `72c1c51`

---

## Headline

| | Pre-fix | Post-fix |
| --- | --- | --- |
| Acceptance gate verdict | 16/16 (passed=True) | **13/16 (passed=False)** |
| `realism_memo.results` populated rows | 0 (array empty / not flowing) | **476** |
| `out_of_band_hard_fail` rows visible to gate | 0 | **193** |
| Trajectory checks present | not wired | **6 rows, all `in_band`** |
| `per_year_aggregate` rows | 0 (Bucket B not wired) | **25 (5 metrics × 5 years)** |

The gate is now telling the truth. The pre-fix 16/16 was the silent-pass artifact described in the audit doc. ExpressLogix is **not** clean against the calibrated bands — the fixes simply made the verdict observable.

---

## Failed acceptance checks (3 of 16)

### 1. `realism_gate_no_hard_fail_violations` — failed

The verdict surfaces 10 hard-fail violations under this check (only `cogs_percent_of_revenue` Q1–Q10), but the underlying `realism_memo.results` array now contains **193** `out_of_band_hard_fail` rows across **13** distinct metrics (see breakdown below). The gate currently only reports the first metric/quarter window in `acceptance_verdict.checks[].detail.hard_fail_violations`; the full set lives in `realism_memo_json.realism_gate.line_level.results`.

### 2. `net_income_trajectory_viable` — failed
- `q5_ni_margin = 0.2685`, `q11_ni_margin = 0.2867`
- `q5_to_q11_delta = 0.0182`, threshold `0.02`
- Margin is improving but not by enough to satisfy the post-recovery progression rule.

### 3. `balance_sheet_growth_plausible` — failed
- `q20_cash_to_quarter_opex = 7.65`, threshold `5.0`
- Cash balance grows to 7.65× quarterly opex by Q20 — flagged as an unrealistic cash hoard, consistent with the calibrated bands wanting more cash deployment / capital return.

---

## Realism memo results breakdown (`realism_memo_json.realism_gate.line_level.results`)

**Total rows:** 476
**Status counts:** `in_band: 195`, `out_of_band_hard_fail: 193`, `skipped: 88`, `hard_fail (vanilla): 0`, `soft_fail: 0`

### Hard-fails by aggregation (193 rows)

| Aggregation | Rows | Metrics |
| --- | --- | --- |
| `per_quarter` | 179 | cogs_percent_of_revenue (20), current_ratio (20), debt_to_assets (19), debt_to_equity (19), ebitda_margin (20), gross_margin_percent (20), net_income_margin (20), operating_margin_percent (20), payroll_percent_of_revenue (1), quick_ratio (20) |
| `per_year_aggregate` | 13 | distributions_percent_of_net_income (Y1, Y4, Y5), owners_capital_percent_of_assets (Y1–Y5), total_assets_to_revenue (Y1–Y5) |
| `year_one_aggregate` | 1 | distributions_percent_of_net_income |

### Hard-fail metrics — representative row each

| Metric | Agg | Actual (sample) | Effective band | Target | Band source |
| --- | --- | --- | --- | --- | --- |
| `cogs_percent_of_revenue` | per_quarter Q1 | 0.3195 | [0.6720, 1.0663] | 0.8658 | phase_3_calibrated |
| `current_ratio` | per_quarter Q1→Q20 | 2.74 → 29.81 | [1.0333, 2.4087] | 1.4895 | phase_3_calibrated |
| `debt_to_assets` | per_quarter Q1 | 0.2296 | [0.2383, 0.7346] | 0.4502 | phase_3_calibrated |
| `debt_to_equity` | per_quarter Q1 | 0.4548 | [0.5147, 1.4066] | 0.8184 | phase_3_calibrated |
| `distributions_percent_of_net_income` | per_year_aggregate Y1 | 1.3242 | [-0.2906, 1.1322] | 0.4198 | phase_3_calibrated |
| `distributions_percent_of_net_income` | per_year_aggregate Y4 | 2.0288 | [-0.2906, 1.1322] | 0.4198 | phase_3_calibrated |
| `distributions_percent_of_net_income` | per_year_aggregate Y5 | 4.3933 | [-0.2906, 1.1322] | 0.4198 | phase_3_calibrated |
| `distributions_percent_of_net_income` | year_one_aggregate | 1.3242 | [-0.2906, 1.1322] | 0.4198 | phase_3_calibrated |
| `ebitda_margin` | per_quarter Q1 | 0.3492 | [0.0, 0.3020] | 0.0882 | phase_3_calibrated_with_planning_mode_floor |
| `gross_margin_percent` | per_quarter Q1 | 0.6805 | [-0.0663, 0.3281] | 0.1342 | phase_3_calibrated |
| `net_income_margin` | per_quarter Q1 | 0.2732 | [0.0, 0.2392] | 0.0282 | phase_3_calibrated_with_planning_mode_floor |
| `operating_margin_percent` | per_quarter Q1 | 0.3491 | [0.0, 0.2808] | 0.0427 | phase_3_calibrated_with_planning_mode_floor |
| `owners_capital_percent_of_assets` | per_year_aggregate Y1 | 0.8962 | [0.1796, 0.5296] | 0.3546 | phase_3_calibrated |
| `payroll_percent_of_revenue` | per_quarter Q1 | 0.1769 | [-0.1743, 0.1757] | 0.0007 | phase_3_calibrated |
| `quick_ratio` | per_quarter Q1 | 2.5258 | [1.0138, 1.7526] | 1.3675 | phase_3_calibrated |
| `total_assets_to_revenue` | per_year_aggregate Y1 | 0.5703 | [0.6408, 0.9908] | 0.8158 | phase_3_calibrated |

### Skipped rows (88 total) — reasons

| Count | Reason |
| --- | --- |
| 22 | `formula_returned_none` |
| 20 | `skip_deferred_revenue_not_applicable_naics2_48` |
| 20 | `skip_inventory_not_applicable_naics2_48` |
| 20 | `skip_r_and_d_not_applicable_to_business` |
| 6 | `skip_pretax_income_nonpositive` |

The applicability skips (`naics2_48` deferred revenue/inventory; `r_and_d_not_applicable_to_business`) are the Bucket D audit fix working correctly: NAICS 488 is freight/shipping, none of those metrics should run, and they're now skipping with named reasons rather than silently passing as `in_band`.

### Trajectory checks (6 rows, all `in_band`) — Phase 9 audit fix #7+#8

| Metric | Actual | Band |
| --- | --- | --- |
| `ebitda_positive_by_q11` | 0.3777 | [0.0, ∞) |
| `ebitda_recovery_trend_q5_q11` | 0.0201 | [0.0, ∞) |
| `fixed_cost_burden_reduced_or_scaled_by_q11` | 0.3945 | [0.0, ∞) |
| `gross_margin_supports_ebitda_recovery` | 0.4867 | [0.0, ∞) |
| `loss_window_funded_through_q5` | 506,678.60 | [0.0, ∞) |
| `no_post_recovery_relapse_q11_q20` | 0.3777 | [0.0, ∞) |

These are firing (not "missing") and all passing — the floor is real. Pre-fix these rows were not in the array.

---

## What changed vs. the pre-fix run

### Newly visible hard-fails (all 193 were silently passing pre-fix)

Every `out_of_band_hard_fail` row above is "new" in the sense that **none** of these were reaching the verdict before — the gate was looking at an empty / not-populated `results` array and the status string `out_of_band_hard_fail` was not in its accept-as-failure set. Audit fix #1 (`accept "out_of_band_hard_fail" as hard_fail status`, commit `e426232`) is the dominant reason the verdict moved.

### `per_year_aggregate` rows (Bucket B fix, commit `53d5c40`)

13 hard-fails came in via `per_year_aggregate` and 1 via `year_one_aggregate`. Pre-fix this aggregation bucket was filed under `year_one_aggregate` only (Y1 single point); now it spans Y1–Y5, which is why Y4 distributions (2.03×) and Y5 distributions (4.39×) are now visible — the company is paying out 2–4× net income in distributions in years 4 and 5, which the previous aggregation never inspected.

### Trajectory floors (Bucket fix #7+#8, commit `5a2a696`)

`gross_margin_supports_ebitda_recovery` and `fixed_cost_burden_reduced_or_scaled_by_q11` are now real metrics in the array. Both currently `in_band` for ExpressLogix.

### R&D applicability (Bucket D fix, commit `72c1c51`)

`skip_r_and_d_not_applicable_to_business` is firing 20× with a named reason. Pre-fix this would have either been silently `in_band` or absent. ExpressLogix is NAICS 488 (freight) — neither software nor professional services — so this skip is the **correct** behavior. The Bucket D fix is wired but its effect on ExpressLogix is "no false R&D fails." It would need a software-NAICS test draft to demonstrate the inverse.

---

## Interpretation

The gate is telling the truth and the truth is: ExpressLogix's plan is structurally inconsistent with NAICS 488 (freight/shipping) calibrated bands.

The dominant shape of the failures is **"too profitable, too cash-rich, too lightly levered for a freight company":**
- COGS is ~32% of revenue; calibrated band wants 67–107% (i.e. low-margin freight, not high-margin services).
- Gross margin 68%; band wants -7% to +33%.
- EBITDA margin 35%; band ceiling is 30%.
- Current ratio drifts from 2.7 → 30+ over Q1–Q20; band ceiling is 2.41.
- Owners' capital reaches 90%+ of assets; band ceiling is 53%.
- Distributions hit 132%, 203%, 439% of net income in Y1, Y4, Y5; band ceiling is 113%.

Either:
1. The model is generating numbers that don't match the industry ExpressLogix is in, **or**
2. The calibrated bands for NAICS 488 are too narrow, **or**
3. ExpressLogix's intake describes a business that isn't actually freight-like (asset-light brokerage, etc.) and the NAICS-3 lookup is mis-classifying.

That triage is the next decision, not part of this run.

---

## Files referenced

- Test runner: [Test Files/run_persisted_system_run.py](Test%20Files/run_persisted_system_run.py)
- Saved persisted-state report: `C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Test Runs Data\05-09-2026 -- 398986f44cec43589a0db2ac001d4a03.txt`
- New Runner report: `C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\New Runner\05-09-2026 -- 398986f44cec43589a0db2ac001d4a03.txt`
- Audit doc: [docs/phase_9_realism_audit.md](docs/phase_9_realism_audit.md)
