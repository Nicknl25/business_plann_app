# DCF VALUATION — what we can GROUND vs. what must be assumed (2026-08-19)

Status: RESEARCH ONLY. NOTHING BUILT. Every claim below was probed live — the
FRED API (14 calls), the Alpha Vantage API (5 calls, free-tier confirmed), the
real MySQL warehouse, and the actual Bellweather workbook built this morning.

---

## THE ANSWER IN ONE PAGE

**Of the eight DCF inputs, four are already real, one becomes real with a wiring
job, one becomes *partly* real after a 20-day backfill but only for a quarter of
our clients, and two are irreducibly assumptions.**

| # | Input | Verdict | Source / basis |
|---|---|---|---|
| 1 | Unlevered free cash flow | **HAVE** | every component is a live FINMO cell (EBIT row now exists) |
| 2 | Effective tax rate | **HAVE** | `Model Inputs!Taxes` = 26.94% (Bellweather) — *read the quarterly cell, see §7* |
| 3 | Cost of debt | **HAVE** | SBA 7(a) median, NAICS+state matched, n=106 → 7.975% |
| 4 | Capital-structure weights | **HAVE** | model balance sheet (but see the net-cash trap, §6) |
| 5 | **Risk-free rate** | **PULLABLE** | FRED `DGS10` — live today **4.72%**. Loader is dead in this tree; ~1 day of work |
| 6 | **Beta → cost of equity** | **PARTLY PULLABLE** | Alpha Vantage `OVERVIEW` returns `Beta` — **and our pipeline already calls that endpoint and discards it.** But n≥5 comparables exist for only **25% of drafts** |
| 7 | Equity risk premium | **ASSUMPTION** (sourced) | FRED has no ERP series (searched, 0 hits). Use a named, dated external figure |
| 8 | Terminal value | **SPLIT** | growth **ceiling is groundable** (4.3% nominal GDP); **exit multiple is not** |

**The one discovery worth acting on:** `python/data_pull/pull_ticker_industry_sector_official.py:59-75`
already calls Alpha Vantage `OVERVIEW` for all 3,704 tickers and persists **3 of
the 55 fields returned**. `Beta`, `EVToEBITDA`, `EVToRevenue`,
`SharesOutstanding` and a *dated* market cap are being fetched and thrown away.
Capturing them costs **zero additional API budget** going forward.

**This corrects `docs/WORKBOOK_ANALYTICS_RESEARCH.md:268`** ("beta… zero hits
repo-wide"): true of the database, but false of the API we already pay calls to.

---

## 1. HAVE — the cash flows (confirmed on the live workbook)

Every UFCF term is a cell on FINMO today. Read from the Bellweather workbook
built this morning (Q1 / Y1 / Y5):

| Term | FINMO row | Q1 | Y1 | Y5 |
|---|---|---|---|---|
| EBITDA | 16 | 33,054 | 138,273 | 190,452 |
| Depreciation | 18 | 9,315 | 37,726 | 41,382 |
| **EBIT** (new — the ratios section) | 89 | 23,739 | 100,547 | 149,070 |
| Capital expenditures | 52 | 1,294 | 6,978 | 925 |
| Δ current assets | 49 | −4,390 | −6,644 | −4,577 |
| Δ current liabilities | 50 | 665 | −789 | −1,010 |
| Cash | 23 | 70,972 | 127,623 | 251,982 |
| Total debt / Net debt | 83 / 84 | 97,737 / 26,765 | 83,124 / −44,499 | 0 / **−251,982** |
| Total equity | 42 | 158,939 | 211,185 | 288,588 |

`UFCF = EBIT × (1 − t) + D&A − capex − ΔNWC` is therefore a pure cell formula,
quarter by quarter, with no new data and no engine change.

**Two honest cash-flow caveats, both already evidenced:**
- **D&A ≫ capex.** Y1: 37,726 vs 6,978, with PPE running down. A naive UFCF adds
  back depreciation the business never reinvests and inflates value. Fix: a
  **maintenance-capex floor**, defaulted from the warehouse
  (`maintenance_capex_percent_of_revenue` = 2.80% for NAICS 811111) and disclosed.
- **Owner compensation sits inside payroll** (prior ruling). A main-street buyer
  values *seller's discretionary earnings* — EBITDA **plus** owner comp. Whether
  to show an SDE line beside EBITDA is a ruling, not a data question (Q4 below).

## 2. HAVE — tax rate and cost of debt

- **Tax rate**: `Model Inputs!Taxes` = **0.269425**, flat across all 21 periods
  (Bellweather), sourced from the doctrinal tax cascade. Real.
- **Cost of debt**: `derived_driver_policies.debt_interest_rate_policy` —
  **7.975% annual / 1.9938% quarterly**, median SBA 7(a) initial rate, NAICS-6
  811111, Wisconsin, FY2021-25, **n=106** (`finmo_bridge.py:1133-1290`). This is
  a genuinely grounded cost of debt and is directly usable in WACC.

## 3. PULLABLE — the risk-free rate (FRED)

**Groundable today. The plumbing is the only work.**

Live values probed 2026-08-19:

| Series | Latest | Value | Frequency |
|---|---|---|---|
| **DGS10** (10-yr CMT) | 2026-08-17 | **4.72%** | daily |
| GS10 (monthly twin) | 2026-07-01 | 4.60% | monthly |
| DGS30 / DGS5 / DGS2 | 2026-08-17 | 5.31 / 4.38 / 4.19% | daily |
| T10YIE (10-yr breakeven inflation) | 2026-08-18 | 2.30% | daily |
| DFII10 (10-yr real) | 2026-08-17 | 2.44% | daily |

Consistency check ties out: 4.72 − 2.44 = 2.28 vs T10YIE 2.30.

**Use DGS10.** A 5-year DCF with a terminal value discounts a perpetual stream —
the duration being discounted is far longer than five years — and every published
ERP is quoted against the 10-year, so pairing a 5-year risk-free with a
10-year-based ERP silently mis-states the cost of equity. DGS5 belongs only in a
secondary "explicit forecast, no terminal value" sensitivity.

**State of the plumbing:** `python/data_pull/fred_macro_loader.py` pulls only
GDP, CPI and PCE, and **is dead in this tree** — `get_project_root()` requires a
parent folder literally named "Business Plan Generator" and raises otherwise
(`:17-22`), which is why `fred_macro_quarterly` stops at 2025Q2 (5 quarters
stale) and why **nothing in `python/` reads it**. Rate limits are a non-issue:
120 requests/minute, no daily cap; a daily rates loader would use ~14.

**Wiring shape** (three modules, each copying a pattern already proven here):
a `fred_rates_loader.py` sibling; a `market_rates.py` reader shaped exactly like
`_sba_business_loan_interest_rate_and_source` (module cache, structured source
dict, **never raises** — returns a stamped fallback); and consumption inside a
`finmo_dcf.py` **pure post-process**, exactly like `finmo_break_even.py`, with
`dcf: Optional[Dict]` on `FinmoOutputContract`. **Not** through
`derived_driver_policies` — that path is for values that drive the model, and
the risk-free rate drives nothing upstream.

**Reproducibility is the whole point of the stamp:** freeze the resolved rate
into `finmo_json["dcf"]["assumptions"]` at build time. Rebuilding a six-month-old
draft must reproduce the six-month-old valuation, not silently re-value the
business at today's yield.

## 4. ASSUMPTION — the equity risk premium

**Not on FRED.** Searched rather than assumed: `search_text=equity risk premium`
returns **count = 1**, and that hit is a Chicago Fed leverage sub-index, not an
ERP; `risk premium stock market` returns **0**.

What FRED *can* give — BAA10Y (1.69%), AAA10Y (1.24%) — are **credit** spreads.
Using a debt spread as an equity premium is a category error.

**Honest handling:** a versioned constant in code, carrying its source and
as-of date (Damodaran's monthly implied ERP, currently ~4.3–5.0%; Kroll's
recommended US ERP, currently 5.0%), rendered as a labelled assumption cell.
Same treatment for the **size / illiquidity premium** a 3-FTE business needs and
which exists in no dataset we hold.

## 5. PARTLY PULLABLE — beta, and the honest limits

**The data exists at the API and is being discarded.** Live `OVERVIEW` values:

| Ticker | NAICS | Beta | EV/EBITDA | Market cap (live) | Market cap (our DB) |
|---|---|---|---|---|---|
| MNRO | 811111 | **1.052** | 9.61 | 361,413,000 | 528,646,000 (−31.6% stale) |
| DRVN | 811111 | **0.965** | 10.69 | 2,126,590,000 | 2,225,066,000 |
| TSCO | 444240 | **0.452** | 13.18 | 18,090,514,000 | 27,815,164,000 (−35.0% stale) |
| GRWG | 444240 | **2.547** | −1.54 | 113,572,000 | 90,364,000 |

**But comparable depth is the binding constraint, and it is worse than it looks:**

| Coverage threshold | NAICS meeting it | **Share of real drafts** |
|---|---|---|
| ≥1 ticker at NAICS-6 | 36/60 | 38% |
| **≥5 tickers at NAICS-6** | 17/60 | **25%** |
| ≥5 at NAICS-4 prefix | 30/60 | 47% |
| ≥5 at NAICS-3 prefix | 54/60 | 98% |

Bellweather (811111) has **n=2**. Kestrelbrook (444240) has **n=2** — and those
two are TSCO at β 0.452 and GRWG at β 2.547, a **5.6× spread inside one
"industry."** Our busiest client NAICS, 561730 landscaping (674 drafts), has
**zero** tickers at six digits. The 3-digit fallback that reaches 98% of drafts
is precisely the fallback that destroys the meaning of "industry": it puts a solo
law firm in a 631-ticker bucket with software and consulting.

**Derivation recipe, and what each step still needs:**

| Step | Have it? |
|---|---|
| comparable set by NAICS | **yes** (`alpha_match_naics_industry`, with a confidence column to filter on) |
| levered β per comparable | **no in DB / yes via API** — 1 call per ticker; ~20 days to backfill the 493 client-relevant tickers at 25/day |
| comparable D/E at market | **partly** — debt yes (`alpha_data.shortLongTermDebtTotal`); market equity is a **stale undated snapshot**; and the stored `debt_to_equity` is total-liabilities ÷ book equity — **the wrong ratio for Hamada, do not use** |
| comparable tax rate | **weak** — quarterly effective rates swing negative (DRVN −55%); needs TTM aggregation |
| client D/E and tax rate | **yes** — from the model |
| rf + ERP to close CAPM | rf **pullable** (§3); ERP **assumption** (§4) |

Worked illustration (811111, live betas, live caps, t=26%): median unlevered
β = **0.506**, re-levered at a client D/E of 1.5 → β ≈ **1.07**, and at rf 4.72%
+ ERP 5.5% → **Ke ≈ 10.6%**.

**Verdict:** ship beta as a **defaulted, overridable, sourced input cell** that
prints its comparable count and vintage on its face — and **refuses to present
itself as derived when n < 5**, falling back to a stated industry-typical range.
Never a silent constant.

## 6. TERMINAL VALUE — ceiling grounded, multiple not

**Perpetuity growth: the CEILING is groundable.**

```
real GDP trend (GDPC1, 20-yr CAGR)      1.98%   ≈ 2.0%
+ market-implied inflation (T10YIE)     2.30%
= long-run nominal ceiling              4.28%   ≈ 4.3%
   cross-check: nominal GDP 20-yr CAGR  4.39%
```
Recommended rules: hard ceiling **g ≤ 4.3%** (a perpetuity growing faster than
the economy eventually *is* the economy); **default g = 2.3%** — inflation only,
no permanent real share gain for a single-location business; and enforce
**WACC − g ≥ 3pp** or the Gordon denominator explodes on rounding.

**Exit multiple: not derivable. It stays a disclosed assumption.**
- `sba_loan_7a_raw` holds **35,773 change-of-ownership loans** (811111: 797,
  avg $809,852) — but there is **no purchase price and no target earnings** in
  the file. `GrossApproval` is the *loan*, typically 75–90% of a financed price
  and often bundled with working capital. It grounds a **deal-size prior**, not
  a multiple.
- `sec_edgar_facts`: 49 concepts, **zero valuation concepts** — no shares
  outstanding, no price, no EV.
- Alpha's `EVToEBITDA` is real but is a **public-company** multiple: median
  10.15× on n=2 large levered chains, against the 2–3× SDE range main-street
  brokers actually transact at. Applying 10× to a 3-FTE shop overstates value by
  roughly 3–4×, and **we hold no data that would prove the discount**.

## 7. WACC assembly — and the trap this business exposes

WACC = Kd(1−t)·w_d + Ke·w_e, with weights from the model's balance sheet. Two
things must be ruled, because Bellweather breaks the naive version:

1. **Terminal net cash.** By Q20 debt is **0** and cash is **251,982** — net debt
   is **−251,982**. Book weights then make WACC = cost of equity outright, and
   the equity bridge *adds* a quarter-million of cash. Both are arithmetically
   right and jointly mean **the valuation is dominated by the terminal
   assumption** — which is exactly why both TV methods and a sensitivity grid
   are mandatory, not decorative.
2. **Current vs target weights.** Q1 weights (D/E ≈ 0.6) and Y5 weights (D/E = 0)
   give materially different discount rates. Standard practice is a *target*
   structure; that is a disclosed judgment.

## 8. Where GPT may legitimately speak — the Lane A / Lane B line

Applying the rule already ruled in `WRITING_PHASE_RESEARCH_2.md` §3:

| Allowed (Lane B — framing) | Forbidden (Lane A — must trace) |
|---|---|
| "Owner-operated auto repair businesses typically change hands in the low single-digit multiples of seller's discretionary earnings" | "This business's exit multiple is 3.2×" |
| "A discount rate for a business this size normally carries a premium over public-company costs of equity, because the buyer cannot sell the position quickly" | "Your beta is 1.07" (unless it *is* derived and the sheet says from what, with n) |
| Explaining what break-even, WACC or terminal value mean, and why a valuation is sensitive to them | Any number in a cell — every one traces to the model, a named table, or a labelled assumption |

The mechanical test is unchanged: a sentence containing a figure must cite a
fact id; an `[E]` sentence carries no digits. **Every assumption cell prints its
basis beside it** — that is what keeps a DCF honest rather than authoritative.

## 9. Two defects found while researching (fix belongs in a build turn)

Both are in the ratios section shipped this morning; both are cheap:

1. **ROIC's tax factor silently resolves to an empty cell.**
   `finmo_ratios.py:144` uses `local_ref(ctx.model_input_row("is::Taxes"), col)`
   — a *same-sheet* reference. Model Inputs' "Taxes" is row 22; FINMO's row 22
   is the "Balance Sheet" section header. So `(1 − D22)` = `(1 − blank)` = 1 and
   ROIC is computed **pre-tax**. Fix: `ref("Model Inputs", row, col)`.
2. **Rate rows are SUMMED in the annual columns.** `Model Inputs!Taxes` shows
   **1.0777** for Y1 (0.269425 × 4) because `add_annual_formulas` sums income-
   statement rows. Any annual consumer of a *rate* cell — including the DCF —
   must use the quarterly cell or derive the effective rate as taxes ÷ pre-tax
   income. (ROIC's annual figures, 60%→407%, are the visible symptom of these
   two combining with a shrinking invested-capital denominator.)

---

## RECOMMENDED SEQUENCE (X5, if ruled)

1. **Capture what we already fetch** — persist `Beta`, `EVToEBITDA`,
   `EVToRevenue`, `SharesOutstanding` and a **dated** market cap on the existing
   OVERVIEW pass. Zero extra API cost; ~20 days to backfill the client-relevant
   493 tickers at free-tier throughput.
2. **Revive FRED and add a rates loader** — fix the dead root-path bug, add the
   `market_rates.py` reader with its stamped fallback.
3. **Fix the two ratio defects** (§9) — the DCF depends on the tax rate being
   read correctly.
4. **Build the DCF as a pure post-process + sheet** — UFCF schedule, WACC block,
   both terminal methods side by side with each showing the other's implied
   value, the equity bridge, and two sensitivity grids (WACC × g, WACC ×
   multiple), every assumption cell labelled with its basis and vintage.

## OPEN QUESTIONS FOR RULING

- **Q1** Risk-free: DGS10 (recommended) or the more conservative DGS30?
- **Q2** ERP source: Damodaran implied (~4.3–5.0%) or Kroll recommended (5.0%)?
  Either way it is a versioned constant with an as-of date — which one do we cite?
- **Q3** Beta: ship it only where n ≥ 5 comparables (25% of drafts) and fall back
  to a stated range elsewhere — or don't ship a derived beta at all in v1 and
  make cost of equity a single disclosed build-up? (Recommend the former.)
- **Q4** Do we show **SDE** (EBITDA + owner compensation) beside EBITDA, given
  main-street buyers price on it and owner comp is inside payroll?
- **Q5** Exit multiple: show the method at all, given no defensible small-business
  multiple data exists? (Recommend: show it, default conservatively, let the
  sensitivity grid carry the honesty — and never present it as sourced.)
- **Q6** WACC weights: current, target, or both as a sensitivity?

Nothing built.
