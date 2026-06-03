# Fix #1 — Viability Constructs: Data Feasibility (no scorecard design)

**Status:** feasibility only. Confirms the data exists to build the 5 clean-zone viability
constructs. **No scoring / weights / scorecard design** — that is a later pass.

**Decision (locked):** viability is built from the **operating engine only** — everything the
funding pass does NOT touch. Funding determines cash / debt / interest / equity, so every
metric involving those is OUT (no leverage, coverage, liquidity, ROE, cash-flow-statement
metrics, capex). Clean zone = P&L down to **EBITDA** + **working capital** + **cumulative
operating earnings**.

Code/data claims `file:line` / column-level. Finance concepts *(general knowledge)*.

---

## GATING DEPENDENCY — does finmo expose working-capital LINE ITEMS per quarter?

**Yes — and they are modeled deliberately (driver-based), not plugged/residual.** Constructs 1
and 3 are feasible.

Per-quarter `FinmoQuarterResult` exposes each operating-WC line item individually
([finmo_model.py:615-625](../../python/financial_model_engine/finmo_model.py#L615-L625)):
`accounts_receivable`, `inventory`, `prepaid_expenses`, `accounts_payable`, `deferred_revenue`,
plus the aggregates `current_assets` / `current_liabilities`.

Each line item is computed from an explicit balance-sheet **days/percent driver**, *(general
knowledge: this is deliberate working-capital modeling, not a balancing residual)*:
- `accounts_receivable = (AR Days / days_in_quarter) × revenue` — [finmo_model.py:491](../../python/financial_model_engine/finmo_model.py#L491)
- `inventory = (Inventory Days / days_in_quarter) × cogs` — [finmo_model.py:492](../../python/financial_model_engine/finmo_model.py#L492)
- `prepaid_expenses = revenue × Prepaid%` — [finmo_model.py:493](../../python/financial_model_engine/finmo_model.py#L493)
- `deferred_revenue = revenue × Deferred%` — [finmo_model.py:494](../../python/financial_model_engine/finmo_model.py#L494)
- `accounts_payable = (AP Days / days_in_quarter) × (marketing + r&d + lease + payroll + g&a)` — [finmo_model.py:503](../../python/financial_model_engine/finmo_model.py#L503)

**Robustness verdict (same test we applied to cash): PASS — none of AR/AP/inventory is a
residual.** They are forward-computed from named drivers, so a viability construct reading them
is reading deliberate model intent, not a plug.

**Bonus — finmo already isolates a CLEAN operating NWC (ex-cash, ex-short-term-debt):**
- `operational_current_liabilities = accounts_payable + deferred_revenue` — [finmo_model.py:571](../../python/financial_model_engine/finmo_model.py#L571)
  (explicitly **excludes** `short_term_debt`).
- `changes_in_current_assets` = −Δ(AR + inventory + prepaid) — [finmo_model.py:562](../../python/financial_model_engine/finmo_model.py#L562)
- `changes_in_current_liabilities` uses `operational_current_liabilities` — [finmo_model.py:571-572](../../python/financial_model_engine/finmo_model.py#L571-L572)

So a clean operating-NWC level and its delta are **already available without re-deriving**.

**Contamination flag (must avoid the totals):** the *aggregate* `current_liabilities =
accounts_payable + short_term_debt + deferred_revenue` includes funding-pass short-term debt
([finmo_model.py:543](../../python/financial_model_engine/finmo_model.py#L543)), and
`current_assets = cash + AR + inventory + prepaid` includes cash
([finmo_model.py:586](../../python/financial_model_engine/finmo_model.py#L586)). The clean-zone
build must use the **operating subsets** (AR + inventory + prepaid) and (AP + deferred), or the
pre-built `operational_current_liabilities` / `changes_in_*` fields — **not** the
`current_assets` / `current_liabilities` totals.

**Cohort working-capital columns are already operating-only** (short-term debt explicitly
treated as 0), so they align with the firm's clean subset
([phase_9_p3_derive_working_capital_columns.py:8-19, 74-96](../../python/scripts/phase_9_p3_derive_working_capital_columns.py#L8-L19)):
- `current_assets_minus_cash_to_revenue = dso/90 + (inventory_days/90)×cogs_percent` (ex-cash) — [:74-85](../../python/scripts/phase_9_p3_derive_working_capital_columns.py#L74-L85)
- `current_liabilities_to_revenue = (dpo/90)×cogs_percent` — STD component "NOT in cohort tables, 0" — [:16-19, 86-96](../../python/scripts/phase_9_p3_derive_working_capital_columns.py#L86-L96)

Minor definitional gap *(general knowledge)*: cohort omits prepaid (CA) and deferred (CL),
treating both as 0; the firm includes them. Core AR/inventory/AP structure aligns.

---

## FEASIBILITY TABLE — 5 constructs × (firm / cohort)

| # | Construct | FIRM side (finmo, per quarter) — deliberate? | COHORT side — existing columns vs Option-F recompute |
|---|---|---|---|
| **1** | **Operating-cash proxy = EBITDA − ΔNWC** | ✅ Feasible, deliberate. `ebitda` [finmo_model.py:609](../../python/financial_model_engine/finmo_model.py#L609); ΔNWC already built clean as `changes_in_current_assets` [:562](../../python/financial_model_engine/finmo_model.py#L562) + `changes_in_current_liabilities` (ex-STD) [:571-572](../../python/financial_model_engine/finmo_model.py#L571-L572). | ✅ **Existing columns, no recompute.** `ebitda_margin_q` (DDL [alpha_data_growth_rates.py:60](../../python/data_pull/alpha_data_growth_rates.py#L60)); ΔNWC% from Δ of `current_assets_minus_cash_to_revenue` − `current_liabilities_to_revenue` ([:89-90](../../python/data_pull/alpha_data_growth_rates.py#L89-L90)) across consecutive same-firm rows. Both operating-clean. |
| **2** | **Rule-of-40 = revenue growth% + EBITDA margin%** | ✅ Feasible, deliberate. `revenue` [finmo_model.py:601](../../python/financial_model_engine/finmo_model.py#L601) → QoQ/YoY growth; `ebitda`/`revenue` → margin. | ✅ **Existing columns, cleanest.** `revenue_growth_q` [alpha_data_growth_rates.py:55](../../python/data_pull/alpha_data_growth_rates.py#L55) + `ebitda_margin_q` [:60](../../python/data_pull/alpha_data_growth_rates.py#L60). Direct, no recompute. |
| **3** | **Working-capital intensity = NWC/revenue + trajectory** | ✅ Feasible, deliberate. Operating NWC = (AR [:491] + inventory [:492] + prepaid [:493]) − (AP [:503] + deferred [:494]); /`revenue` [:601]. | ✅ **Existing columns, no recompute.** `current_assets_minus_cash_to_revenue` − `current_liabilities_to_revenue` ([alpha_data_growth_rates.py:89-90](../../python/data_pull/alpha_data_growth_rates.py#L89-L90)); or the granular `dso`/`dpo`/`inventory_days` [:67-69](../../python/data_pull/alpha_data_growth_rates.py#L67-L69). Operating-clean. |
| **4** | **EBITDA ramp shape — time-to-breakeven, margin slope, operating leverage** | ✅ Feasible, deliberate. Per-quarter `ebitda` [:609] + `revenue` [:601]: breakeven = first quarter `ebitda ≥ 0`; margin slope = Δ(ebitda/revenue); operating leverage = Δmargin vs Δrevenue. | ⚠️ **Partial.** Margin slope + operating leverage reconstructable from consecutive same-firm `ebitda_margin_q` + `revenue_growth_q` ([:55,60](../../python/data_pull/alpha_data_growth_rates.py#L55-L60)). **BUT `time-to-EBITDA-breakeven` has NO clean cohort analog** — cohort rows are point-in-time firm-quarters not aligned to firm age, and public peers are mostly already profitable, so there is no "quarters-since-inception-to-first-positive-EBITDA" to benchmark against. Slope/leverage benchmark also age-misaligned (measures peers' QoQ change, not a startup ramp). |
| **5** | **Cumulative EBITDA (retained-earnings analog)** | ✅ Feasible, deliberate. Running sum of per-quarter `ebitda` [:609]. *(Note: absolute dollars, scale-dependent.)* | ❌ **NO clean cohort benchmark.** Cohort tables store point-in-time **ratios** only ([alpha_data_growth_rates.py:47-93](../../python/data_pull/alpha_data_growth_rates.py#L47-L93)) — no cumulative-since-inception, no retained-earnings column, and cumulative EBITDA is an **absolute** not a ratio so it can't be cohort-percentile-normalized. Even cumulative-EBITDA/cumulative-revenue is not stored; an Option-F recompute would still be awkward (public retained earnings reflect age, dividends, buybacks — not comparable). **Treat as a firm-internal trajectory metric, no peer percentile.** |

---

## SUMMARY

- **Gating dependency CONFIRMED:** finmo exposes AR / inventory / AP / prepaid / deferred as
  deliberate, days-driven per-quarter line items ([finmo_model.py:491-503, 615-625](../../python/financial_model_engine/finmo_model.py#L491-L503))
  — not residual, not just total-asset aggregates — and pre-builds a clean operating-NWC delta
  ([:562, 571-572](../../python/financial_model_engine/finmo_model.py#L562)). Constructs 1 and 3
  are feasible on both sides.
- **Constructs 1, 2, 3:** fully feasible firm + cohort from **existing precomputed columns** —
  no Option-F recompute required.
- **Construct 4:** firm fully feasible; cohort **partial** — margin slope / operating leverage
  reconstructable, but **time-to-EBITDA-breakeven has no cohort analog** and slope benchmarking
  is age-misaligned.
- **Construct 5:** firm fully feasible; **no clean cohort benchmark** (point-in-time ratio
  cohort has no cumulative / retained-earnings analog; cumulative EBITDA is an absolute, not a
  normalizable ratio).
- **Implementation flag for the build pass:** use the operating WC **subsets** (AR+inventory+
  prepaid; AP+deferred) or the pre-built `operational_current_liabilities` / `changes_in_*`
  fields — **never** the `current_assets` / `current_liabilities` totals, which are
  funding-contaminated (cash, short-term debt).
