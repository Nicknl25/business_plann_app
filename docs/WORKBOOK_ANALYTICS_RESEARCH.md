# THE WORKBOOK AS AN ANALYTICS PRODUCT — research for Nick's ruling (2026-08-18)

Status: RESEARCH ONLY. NOTHING BUILT. Every capability claim below was probed
empirically — written with openpyxl 3.1.5, opened in real Excel 16.0 via COM,
recalculated, values read back — not assumed. Palette claims were run through the
dataviz validator, not eyeballed. Repo facts are cited file:line.

---

## THE ANSWER IN ONE PAGE

1. **The design system is the foundation and must land first.** Today the builder
   has 27 ad-hoc colors (19 of them raw Office swatches), 24 typography
   treatments, three competing number-format sniffers and 58 sites that bypass
   the style helpers. Every sheet added on top of that inherits the mess. One
   module (`design.py`) + a guard test is the fix.
2. **Break-even/CVP moves to its own sheet.** It is a page, not a footnote under
   the P&L.
3. **A full ratio sheet is buildable today with zero new data** — 27 ratios,
   every one a live formula over existing cells, plus a real industry benchmark
   column from the plan's own cohort bands.
4. **A DCF is buildable and worth it — with an honest assumption block.** Cash
   flows, tax rate and cost of debt are real data. Beta, ERP, risk-free, cost of
   equity and the exit multiple have **zero** data behind them anywhere in the
   codebase or the 68-table warehouse. They become labelled inputs, disclosed.
5. **The dashboard toggle works, macro-free — verified.** Data-validation
   dropdown + INDEX/MATCH/OFFSET/CHOOSE against a hidden Calc sheet: probed with
   the driver flipped three times, all eight dependents recalculated correctly.
6. **Power Pivot is not merely unavailable — it is actively dangerous.** openpyxl
   has no API to create it, and a round-trip over a real data-model workbook
   silently deleted `xl/model/item.data` + `xl/connections.xml` (88,827 → 9,351
   bytes) and produced a file **Excel refuses to open**. Verdict: never, and the
   builder must never touch a client's model workbook.
7. **The workbook as a sold product** changes six things — editable-but-protected
   inputs, a how-to-use page, print/PDF setup, versioning on the cover,
   self-containment, and no macros ever.

**Build order (dependencies are real, not preference):**

| # | Turn | Depends on | R32 cost |
|---|---|---|---|
| **X1** | Design system module + restyle every existing sheet + cover sheet (no formulas on it) | — | **NEUTRAL** |
| **X2** | Structural move: break-even/CVP → own sheet; sheet order; nav | X1 | **one re-bless** |
| **X3** | Ratio Analysis sheet | X1 (+X2 for order) | one re-bless |
| **X4** | Hidden Calc sheet + dashboard period/year toggle | X1 | one re-bless |
| **X5** | DCF Valuation sheet + assumption/disclosure block | X1, X3 | one re-bless |
| **X6** | Product finish: protection, how-to-use, print/PDF, Pillow logo | X1–X5 | NEUTRAL |

X2–X5 each move the formula grid; **batch adjacent ones to pay fewer re-blesses**
(X2+X3 together is one; X4+X5 together is one). X1 and X6 are free.

---

## 1. DESIGN SYSTEM — the foundation everything is built through

**Answer: one module, `client_statements_output_excel/design.py`, owning the
palette, type scale, number formats, layout geometry and the *only* functions
allowed to create a sheet, a header, a row style or a chart — plus a guard test
that fails the build if any cell or chart bypasses it. That test is what makes
"premium by default" structural instead of aspirational.**

### 1.1 What is wrong today (audited, cited)

| Problem | Evidence |
|---|---|
| 27 distinct colors, ~19 raw Office swatches used as an ad-hoc palette | `excel_utils.py:34-47` + 18 inline literals across 5 modules |
| Role collisions | green = "linked formula" (font `008000`) **and** "schedule output" (fill `E2F0D9`); four different "bad" reds; two different table-header colors for one role |
| No font family anywhere except 4 lines in Diagnostics | output inherits each reader's Excel default → different on every machine |
| 24 distinct type treatments for ~8 semantic roles | `excel_utils.py` vs `diagnostics_sheet.py` vs `dashboard_sheet.py` style the same role three ways |
| Three competing number-format decision surfaces | `schedule_sheets.py:48-58`, `model_inputs_sheet.py:40-48`, and a literal column-index switch at `schedule_sheets.py:332` |
| Inline formats conflict with the constants | chart axes use `"$#,##0"` / `"0%"` while the cells they plot use `CURRENCY_FORMAT` / `PERCENT_FORMAT` (1 decimal) |
| 58 bypass sites | `dashboard_sheet.py` 25, `diagnostics_sheet.py` 17 (a wholly parallel style system), `break_even_sheet.py` 9, `checks_sheet.py` 5, `schedule_sheets.py` 2 |
| Dead code | `write_formula_row`, `style_used_range`, `MULTIPLE_FORMAT`, `FONT_RED`, `INTEGER_FORMAT` (imported twice, applied zero times) |
| Absent entirely | cover sheet, print setup, page margins/footers, defined names, `NamedStyle`, cell notes, data validation, zoom, chart palette |

### 1.2 The palette (validated, not eyeballed)

Run through `dataviz/scripts/validate_palette.js` against the workbook's real
surface (white). **Chrome** (contrast computed):

| Role | Hex | Contrast | Use |
|---|---|---|---|
| Primary navy | `#12314B` | 13.4:1 w/ white | title bands, cover, section headers, tabs |
| Navy tint 1 | `#E8EEF4` | 13.0:1 w/ ink | KPI tiles, subtotal bands |
| Navy tint 2 | `#F4F7FA` | 14.1:1 w/ ink | section wash, helper blocks |
| Primary ink | `#1A2733` | 15.2:1 | body text, values |
| Secondary ink | `#5B6B7B` | 5.5:1 | row notes |
| Muted ink | `#71808F` | 3.6:1 | axis labels, footnotes (≥3:1 floor) |
| Hairline | `#DDE3E9` | — | gridlines, borders |
| Rule / axis | `#C3CCD5` | — | axis lines, dividers |

**Series** — the dataviz reference order, unchanged, because the *ordering itself*
is the colorblind-safety mechanism: `#2a78d6` blue → `#eb6834` orange → `#1baf7a`
aqua → `#eda100` amber → `#e87ba4` magenta → `#008300` green → `#4a3aa7` violet →
`#e34948` red. Validated on white: lightness band PASS, chroma PASS, worst
adjacent CVD ΔE 9.1 PASS, worst adjacent normal-vision ΔE 19.6 PASS; contrast
WARN on aqua/amber/magenta → those slots ship with visible labels or the legend
(the relief rule), never color alone.

**Semantic assignments** (fixed meanings, validated *all-pairs*, which is stricter):
revenue/base = blue, cost/uses = red `#e34948`, break-even & attention = amber
`#eda100` — together: CVD ΔE 15.3 PASS, normal-vision 20.8 PASS. Reference lines
(planned revenue, judged band, targets) are **chrome, not series**: muted dashed —
a threshold, the one legitimate use of a dash. Status (`#0ca30c` good, `#fab219`
warning, `#ec835a` serious, `#d03b3b` critical) is reserved and always paired
with a word.

> Tested and rejected: blue + orange + amber for the CVP chart **FAILS** the
> normal-vision floor (amber↔orange ΔE 13.7 < 15). This is exactly why the
> validator runs instead of taste.

### 1.3 Typography — one family, ten roles

One explicit family (Aptos Narrow → Calibri fallback) everywhere, and a fixed
scale: cover title 28 bold navy · sheet title 16 bold navy · subtitle 10 italic
secondary · section header 11 bold white-on-navy · column header 10 bold
white-on-navy · row label 11 ink · row note 9 italic secondary · value 11 ink ·
KPI value 20 bold navy · footnote 8 italic muted. Nothing outside the scale.

### 1.4 Number formats — one set, applied by role

`$#,##0;($#,##0);"—"` money · `+$#,##0;-$#,##0;"—"` signed delta · `0.0%;(0.0%);"—"`
percent · `0.00"x"` ratio/multiple · `#,##0.0;(#,##0.0);"—"` units · `#,##0" days"`
days · `mmm yyyy` dates. Today's `[Red]` fires on every negative — including
ordinary financing outflows — so a lender reads routine cash movement as an
error. **Red becomes a status color only.**

### 1.5 The chart helper — the single door

`design.styled_chart(...)` returns a chart that by construction has: no chart or
plot-area border, **`varyColors=False`**, `axis.delete=False` on every axis,
hairline solid gridlines on the value axis only, legend bottom (or none for a
single series), palette colors in fixed slot order, 2.25pt lines, ≥8px markers,
number formats from §1.4, and data labels **only where asked**. Every chart is
created through it; no bare `LineChart()` left in a sheet module.

This one helper fixes all four defects Nick saw, and they have single root causes:

| Defect | Root cause | Fix in the helper |
|---|---|---|
| Headcount chart = rainbow of 20 legend entries | `varyColors` defaults on → Excel legends every **point** | always `varyColors=False` |
| Revenue bars in 20 colors | same | same |
| Missing/colliding axis labels | openpyxl hides axes unless `delete=False` (empirically confirmed: "highest-frequency gotcha") | always set it |
| Dated pie with 0%/2% slivers | pie used for 8 close values | helper refuses pie > 6 slices → sorted horizontal bar, one hue, labels at the tips |
| Label collisions on cash/debt & sources-uses | a label on every point; labels inside short bars | endpoint-only labels; `dLblPos="outEnd"`; tick-label skip when > 12 categories |

Two empirically-confirmed traps the helper must encode: **`dLbls.numFmt` is
ignored by openpyxl** (workaround: set `number_format` on the *source cells* —
labels inherit it), and **openpyxl's documented secondary-axis recipe is broken**
(it points the secondary axis at the primary category axis; Excel silently
collapses the series onto one scale). We should not use dual-axis charts at all —
the dataviz rule is explicit that they invent correlations — but the working fix
is recorded in the probe notes if ever forced.

### 1.6 Layout, cover, enforcement

Fixed geometry (label col 34, note col 30, period cols 12, annual 13, one spacer
row between blocks, freeze panes on every sheet, gridlines off, page setup with
repeated title rows and a footer). A **cover sheet**: navy band, business name at
28pt, "Financial Model & Analysis", period covered, prepared-on date, model
version + run id, logo placeholder, a hyperlinked contents list, and a four-row
legend of the cell conventions. **It must carry no formulas** — a formula-bearing
cover adds a new key to the R32 grid and moves the digest; a text-only cover is
free.

Enforcement (this is the anti-"garbage on garbage" mechanism):
1. `design.py` owns every constant; sheets import roles, never raw hex.
2. Sheet/section/row/tile/chart creation goes through design helpers.
3. **A guard test walks the built workbook and fails on any cell whose fill,
   font or number format is outside the tokens, and any chart not produced by
   the helper.** W3+ physically cannot regress the standard without going red.

---

## 2. BREAK-EVEN / CVP → ITS OWN SHEET

**Answer: yes — a dedicated `Break-Even` sheet immediately after FINMO. The block
leaves the P&L entirely (three clean statements again), the CVP helper range goes
with it, and the sheet gains what never fit underneath a P&L.**

Contents: title + one-sentence plain definition · **KPI strip** (break-even
revenue Y1, break-even quarter, margin of safety, break-even volume) · the 11-row
block by quarter and year (unchanged logic, new home) · **volume table** per line
(unit price, planned units, contribution per unit, mix share, break-even units —
no line-standalone break-even; that ruling stands) · the **CVP chart** full-width
beside it, LOSS/PROFIT as chart annotations rather than floating series labels ·
a **sensitivity grid** (price ±10/±5/0/+5/+10% × COGS ±5pp) as plain formulas —
Excel What-If Data Tables are impossible, openpyxl cannot emit `{=TABLE()}` ·
a **methodology note** (fixed vs variable, owner comp inside payroll, depreciation
and interest as balance-driven approximations, the three bases named).

Cost: removing the block shifts the Balance Sheet / Cash Flow rows back up → R32
moves. Batch with X3 so the restructure costs one re-bless, not two.

---

## 3. RATIO ANALYSIS SHEET

**Answer: 27 ratios, all buildable today as live formulas over existing cells,
zero new data — plus a real benchmark column from the plan's own cohort bands.
Five caveats the sheet must state rather than hide.**

Convention: `IS()/BS()/CF()` = `ctx.finmo_row(statement,label)` on FINMO; `MI!` =
Model Inputs; `DQ` = `FINMO!row 6` (Days in Quarter).

| Block | Ratios (all COMPUTABLE) |
|---|---|
| **Liquidity** | current, quick, working capital $, cash as months of opex |
| **Leverage** | total debt, debt/equity, debt/assets, equity multiplier, net debt, debt/EBITDA |
| **Coverage (the lender block)** | EBIT (derived), interest coverage, **DSCR**, fixed-charge coverage, debt service $ |
| **Profitability** | gross, EBITDA, operating (EBIT), net margin; ROA, ROE, ROIC |
| **Efficiency** | asset turnover, DSO, inventory days, DPO, cash conversion cycle, revenue/FTE\*, payroll % of revenue\* |
| **Growth** | revenue QoQ\*, revenue YoY, EBITDA YoY, revenue CAGR Y1→Y5 |

\* already built elsewhere in the workbook — the ratio sheet links, never recomputes.

**DSCR** = `IS(EBITDA)/(IS(Interest)+CF(Debt Repayment)+CF(Capital Lease Principal
Payments))`. Scheduled principal per quarter is available and unambiguous
(`Debt Schedule!Actual Debt Repayment`, mirrored into the cash-flow row). Do **not**
use `Debt Schedule!Total Debt Service` — that row is debt-only interest+principal
while `IS(Interest)` is debt **plus** lease; mixing them double-counts.

**The five caveats (state them, don't hide them):**
1. **No EBIT row exists** on the P&L — EBIT is `EBITDA − Depreciation`, shown as a
   visible derived row, not buried inside coverage formulas.
2. **DPO basis mismatch.** The model builds Accounts Payable off the *opex block*,
   not COGS (`finmo_sheet.py:277`), so a textbook `AP/COGS×days` won't reconcile.
   Ruling needed: label it "Payable days (opex basis)" and stay internally
   consistent (recommended), or show the textbook basis and footnote the divergence.
3. **DSO and inventory days are circular** — AR and inventory are *defined* from
   those driver rows. Present them as assumptions linked from Model Inputs, not as
   derived findings.
4. **No Year-1 YoY** — the model has no prior year; Y1 growth cells read "—".
5. **Guards are mandatory.** Bellweather's interest hits **0 by Q20** and net debt
   turns **negative**: DSCR and interest coverage divide by zero. Every ratio ships
   wrapped in `IFERROR(...,"—")` plus an explicit zero-denominator branch. A
   lender-facing sheet printing `#DIV/0!` is worse than one omitting the row.

**Benchmarks are real and per-draft**: `post_intake_cohort_bands` (resolved per
draft: metric_key, min/target/max, confidence_tier) and the 49 metric keys in
`post_intake_industry_baseline_lookup` (including current_ratio, quick_ratio,
debt_to_equity, interest_coverage, ar_days_dso, ap_days_dpo, inventory_days,
revenue_per_fte). These are DB values → baked as **literals with source + vintage
labels**, exactly as the Dashboard bakes the judged margin band. This is what
turns a calculator into an analysis.

Layout: `[ratio | Q1..Q20 | Y1..Y5 | industry low | target | high | source]`,
six navy-banded blocks, a KPI strip of the six a lender reads first, conditional
formatting on the coverage block only (DSCR ≥1.25 / 1.0–1.25 / <1.0 — the standard
bank thresholds, always with the number beside the color).

---

## 4. DCF VALUATION SHEET

**Answer: build it, but only with an honest assumption block. The cash flows are
real, the tax rate is real, the cost of debt is real. The discount rate is not —
and neither is the exit multiple.**

| Input | Status | Source |
|---|---|---|
| EBITDA, depreciation, capex, ΔNWC, revenue | **REAL — live cells** | `IS()/CF()` rows |
| EBIT | derived | `EBITDA − Depreciation` |
| Effective tax rate | **REAL** | `MI!is::Taxes` — a genuine rate (Bellweather 26.94%, flat) |
| Cost of debt | **REAL** | `debt_interest_rate_policy`: 7.975% annual / 1.9938% quarterly, from `sba_loan_7a_raw`, NAICS 811111, WI, FY2021-25, **n=106** |
| Capital weights, net debt at horizon | **REAL** | live off the balance sheet (Bellweather Q20: **net cash −252,088**) |
| Terminal growth | **PROXY → assumption** | `judged_growth.mature_annual_growth`, stage-ramp terminal QoQ, or DB `mature_qoq_growth_typical` (811111 target 1.94% QoQ, n=31). None is a perpetuity rate |
| Risk-free, ERP, beta, cost of equity, WACC | **MUST ASSUME** | zero hits repo-wide; no column in any of the 68 tables — **CORRECTED 2026-08-19, see docs/DCF_VALUATION_RESEARCH.md**: true of the DATABASE, but the risk-free rate IS pullable from FRED (DGS10, live 4.72%) and BETA is returned by the Alpha Vantage OVERVIEW endpoint our pipeline already calls and discards. ERP remains a disclosed assumption. |
| Exit EV/EBITDA multiple | **MUST ASSUME — the weakest** | no EV data exists: `sec_edgar_facts` has no market-cap/price/EV concept; `industry_metrics_*` has market_cap but NAICS 811111 is **91 rows, one ticker** — equity cap ≠ EV, no cash bridge |

**Method**: quarterly UFCF (`EBIT×(1−tax) + D&A − capex − ΔNWC`) → discount at a
quarterly-converted WACC → **both** terminal methods side by side (perpetuity
growth and exit multiple, each showing the other's implied value — the standard
cross-check) → enterprise value → less real net debt → equity value → **two
sensitivity grids** (WACC × growth, WACC × multiple) as plain formulas.

**Two traps this business's own numbers expose:**
- **Depreciation ≫ capex** (Bellweather Y1: 37.7k vs 7.0k, PPE running 185k → 7.6k).
  A naive UFCF adds back D&A the business never reinvests and inflates value. Fix:
  a **maintenance-capex floor** input, defaulted from the warehouse
  (`maintenance_capex_percent_of_revenue` = 2.80% for 811111) and disclosed.
- **Terminal net cash** means the valuation is dominated by the terminal
  assumption — which is exactly why both TV methods and the sensitivity grids are
  mandatory, not optional.

Every assumption is an input cell with its basis stated beside it and a plain
sentence in the disclosure block. Same principle as the §9 override disclosure:
the number is allowed to be an assumption; pretending it is data is not.

---

## 5. DASHBOARD PERIOD / YEAR TOGGLE — macro-free, VERIFIED

**Answer: a data-validation dropdown driving INDEX/MATCH/OFFSET/CHOOSE against a
hidden Calc sheet. Probed end-to-end: the driver cell was flipped three times and
all eight dependent formulas recalculated correctly. No macros, no form controls,
no add-ins — opens and works everywhere.**

```python
dv = DataValidation(type="list", formula1="=ViewList", allow_blank=False)
ws.add_data_validation(dv); dv.add(ws["C3"])          # the selector cell
ws["C4"] = "=MATCH($C$3,Calc!$A$2:$A$4,0)"            # selection index
ws["C5"] = "=INDEX(Calc!$B$2:$D$4,$C$4,2)"            # sliced KPI
ws["C6"] = "=SUM(OFFSET(Calc!$A$1,$C$4,1,1,20))"      # sliced range
```
(Never set `showDropDown=True` — in OOXML that *hides* the arrow.)

**Design**: a hidden `Calc` sheet holds one row-block per view (Quarterly Q1–Q20,
Annual Y1–Y5, optionally Trailing-4Q), each block a formula pull from FINMO. The
dashboard's KPI tiles and every chart series point at a **single "active" block**
that is itself `INDEX`/`OFFSET`-driven off the selector — so charts need no
rebuilding; their `Reference` ranges never change, the values behind them do.
A second selector can scope a period range the same way.

Caveat: charts must reference a fixed-size active block (Excel chart ranges are
static), so the annual view pads to the quarterly width or uses a separate chart
pair toggled by which block is populated. Recommend: **fixed 20-slot active
block**, annual view writing 5 values + `NA()` padding so the line simply stops —
`NA()` is the correct "no data" for charts, not zero.

---

## 6. POWER PIVOT / ADVANCED EXCEL — the honest answer

**Answer: NO to Power Pivot, and stronger than "unavailable" — it is destructive.
YES to a specific portable set that is genuinely powerful.**

### 6.1 Power Pivot / data model — verdict AVOID ⛔

- openpyxl has **no API at all** to create a data model, DAX measures, slicers or
  Power Query connections.
- Empirical: a real data-model workbook was built in Excel via COM
  (`xl/model/item.data` + `xl/connections.xml`, 88,827 bytes, model-backed
  PivotTable), then round-tripped through `load_workbook()` → `save()`. openpyxl
  **silently dropped the model and the connections** (88,827 → 9,351 bytes) and the
  result was **REFUSED by Excel** — it kept the pivot parts but deleted the
  connection they depend on.
- Creating a PivotTable from scratch also produced a REFUSED file.
- Portability (general knowledge, flagged): Power Pivot is Windows-Excel-only and
  absent from Home/Standard SKUs, Excel for Mac's UI, Excel for the web, Google
  Sheets and LibreOffice.

So it is not a "nice-to-have we can't reach" — **the builder must never open or
re-save a workbook containing a data model**, or it will corrupt a client's file.

### 6.2 The portable, buildable, genuinely powerful set

| Feature | Emits? | Excel? | Verdict |
|---|---|---|---|
| Structured Tables + styles | Yes | PASS (`SUM(Tbl[Col])` works) | **USE** |
| **DV dropdown + INDEX/OFFSET/CHOOSE toggle** | Yes | PASS | **USE ⭐** |
| Conditional formatting (colorScale, dataBar, iconSet, cellIs, formula, top10, aboveAverage) | Yes | PASS (8/8 rules) | **USE** — via the `*Rule` helpers only |
| Defined names (book + sheet scope) | Yes | PASS | **USE** |
| Classic charts — line, bar (4 groupings), area, pie, doughnut, radar, scatter, bubble, stock, surface, 3D, **combo** | Yes | PASS (21/22) | **USE** |
| ~25 chart-polish knobs (fills, borders, fonts, axis scaling, gridlines, markers, gap width) | Yes | PASS | **USE** |
| Print setup — area, fit-to-width, orientation, margins, header/footer, print titles, breaks, zoom, freeze, protection, hidden sheets, outline grouping | Yes | PASS (25/25) | **USE** |
| Comments/notes, hyperlinks, rich text in cells | Yes | PASS | **USE** |
| Modern functions with `_xlfn.` prefix (XLOOKUP, LET, LAMBDA, IFS, SWITCH, TEXTJOIN…) | Yes | PASS | **USE — prefix mandatory** |
| Images (logo) | Needs **Pillow** (new dependency) | PASS with it | **NEEDS-CARE** |
| Sparklines | No API — manual XML injection only, must be the last step | PASS when injected | **NEEDS-CARE / later** |

### 6.3 "Sounds powerful — do not use"

Power Pivot / DAX / slicers / Power Query (no API, corrupts) · PivotTables from
scratch (REFUSED) · form controls & ActiveX (writer is literally an unimplemented
comment; Windows-only anyway — the DV dropdown gives the same UX at zero risk) ·
**dynamic-array spilling** (doesn't spill; `TAKE` returns `#VALUE!`; use
`ArrayFormula` with a known result size) · waterfall/treemap/sunburst/histogram/
box-whisker (no classes exist — fake a waterfall with a stacked bar + invisible
base) · `ProjectedPieChart` (REFUSED) · raw `Rule(...)` CF objects (open, then
Excel cannot save).

### 6.4 Four confirmed corruption triggers — the builder must lint for these

1. Unprefixed `=FILTER(...)` / `=SORT(...)` → file REFUSED (other unprefixed
   modern functions merely give `#NAME?`).
2. `LET`/`LAMBDA` without `_xlpm.` on parameter names → REFUSED.
3. Raw `Rule(type="dataBar")` without cfvo → opens but cannot be saved.
4. A text cell beginning `"= "` → REFUSED (already found and pinned in W2).

**We already have the right gate**: `assert_workbook_model_status_ok` opens every
generated workbook through Excel COM before delivery. It should stay mandatory —
it catches all four.

### 6.5 Performance headroom

16 sheets / 45 charts / 52,500 formulas → build 0.36s, save 0.96s, **334 KB**,
Excel recalc 0.13s. Everything proposed here fits inside ~10× that budget.

---

## 7. THE WORKBOOK AS A STANDALONE PRODUCT

**Answer: six requirements that only matter once the file is sold on its own —
all cheap now, expensive to retrofit.**

1. **Self-contained** — no external links or data connections; the hidden Audit
   Source sheet keeps the as-generated values so a buyer can always see what
   shipped. (Already true; keep it true.)
2. **Safely editable = the product promise.** A forecast generator is only a
   generator if the buyer changes a price or a wage and watches 20 quarters, the
   break-even, the ratios and the valuation move. Requires: input cells visually
   unmistakable (the convention exists), everything else **locked under sheet
   protection with no password** — verified to work — so a keystroke can't destroy
   a formula while nothing is hidden.
3. **A "How to use this model" page** — the color legend, which cells to change,
   what recalculates, what the three break-even bases mean, where the valuation
   assumptions live. Sold software ships with a manual page.
4. **Print/PDF as a first-class output** — page setup verified on all 25 checks;
   "Save as PDF" should produce a lender-ready document with no fiddling.
5. **Versioning + provenance on the face of it** — cover carries business name,
   date, model version and run id, so a regenerated v2 (the client-update flow)
   is distinguishable at a glance.
6. **No macros, ever** — .xlsm triggers security warnings, is stripped by mail
   gateways, and dies on Excel for the web. A product constraint, not a taste.

Two consequences for the analytics: each sheet must be **readable in isolation**
(a buyer may open Valuation first and never read the plan), and the workbook must
**degrade honestly** — where an input is an assumption rather than a derived fact,
it is an input cell with its basis stated, never a number buried in a formula.

---

## BUILD SEQUENCE — dependencies and cost

```
X1  DESIGN SYSTEM  (design.py + restyle all sheets + text-only cover + guard test)
    └─ depends on nothing · R32 NEUTRAL · unlocks everything below
        │
        ├─ X2  Break-even/CVP → own sheet  ─┐
        │      (needs X1 styling)           │ batch: ONE re-bless
        └─ X3  Ratio Analysis sheet        ─┘
                │
                ├─ X4  Hidden Calc sheet + dashboard toggle  ─┐
                │      (needs X1; independent of X2/X3)       │ batch: ONE re-bless
                └─ X5  DCF Valuation sheet                   ─┘
                       (needs X1; wants X3's derived EBIT/NOPAT rows)
                        │
                        └─ X6  Product finish: protection, how-to-use, print/PDF,
                               Pillow logo · R32 NEUTRAL
```

**Why this order is not negotiable:** X1 is the foundation — every sheet built
before it would need restyling afterwards, which is the "garbage on garbage"
failure Nick named. X3 before X5 because the DCF reuses the ratio sheet's derived
EBIT/NOPAT/invested-capital rows rather than duplicating them. X6 last because
protection and print setup must cover sheets that already exist.

**Interaction with the writing-phase plan (W1–W6):** independent tracks that meet
at W5 — the document's charts must reuse the design system's palette and series
definitions so the doc and the workbook never disagree. **X1 should land before
W5.** W3 (override registry) is unaffected and can proceed in parallel.

**Verification tier for each X-turn** (declared, mini audits): builder-only, no
engine math, no data change → spot-check + a **numbers-byte-identical proof**
(every pre-existing formula string and every recalculated value identical
before/after) + the Excel-COM open + the fast gate. X2–X5 additionally carry a
declared R32 re-bless with leaf-by-leaf drift purity, using the instrument built
in W2 (`Test Files/_w2_r32_drift_purity.py`).

**New dependency**: Pillow (logo on the cover). Nothing else.

---

## OPEN QUESTIONS FOR RULING

- **Q1** Palette: adopt the validated dataviz reference series order + the navy
  chrome above, or supply a brand palette to validate instead? (No brand palette
  exists in the repo today.)
- **Q2** Font family: Aptos Narrow with Calibri fallback (modern default), or pin
  Calibri for maximum consistency on older installs?
- **Q3** DPO basis (caveat 3.2): label it "opex basis" and stay internally
  consistent (recommended), or show the textbook COGS basis with a footnote?
- **Q4** DCF defaults: what discount-rate default should the assumption cells
  ship with, and do we show the exit-multiple method at all given there is no
  defensible multiple data for small businesses? (Recommendation: ship both,
  default the multiple conservatively, and let the sensitivity grid carry the
  honesty.)
- **Q5** Toggle scope: quarterly ⇄ annual only, or add trailing-4Q and a period
  range?
- **Q6** Sheet order and what opens first (recommendation: Cover → Dashboard →
  FINMO → Break-Even → Ratios → Valuation → drivers/schedules → Model Inputs →
  Checks → Diagnostics; note two existing tests pin "Dashboard immediately after
  FINMO" and `wb.active == FINMO` and will need updating with the ruling).
- **Q7** Sparklines in the KPI tiles — worth the post-processing fragility, or
  skip? (Recommendation: skip until X6, they are cosmetic and must be the last
  write.)

Nothing built.
