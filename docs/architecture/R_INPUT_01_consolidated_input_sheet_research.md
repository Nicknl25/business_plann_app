# R-INPUT-01 — Single Consolidated Client Input Sheet

**Tier:** research only. No builder, schedule, or formula was changed. No gate
re-bless. Deliverable is this document.

**Date:** 2026-08-20 · **Author:** VS · **Branch:** intake-stable

**Scope note carried from the directive:** the acceptance gate and convergence
apply to the workbook *as built by the app*. What a client edits in a delivered
file afterwards is out of scope and is not treated as a correctness risk here.
The question is purely: how do we build a workbook whose editable drivers all
live on one sheet.

## How claims in this document are tagged

| Tag | Means |
|---|---|
| **VERIFIED** | I read the code or measured the built workbook. The method is stated. |
| **UNVERIFIED** | Reasoned from what I read but not directly measured. Treat as a hypothesis. |
| **TO-BE-TESTED** | Requires an experiment nobody has run. Named as such, never asserted. |

**Measurement basis.** Unless stated otherwise, every number comes from building
the workbook **in memory through the production builder**
(`workbook_builder.build_client_financial_model_workbook` via the gate's
`Surface._build_workbook`, no Excel round-trip) over the **frozen CareCompanions
single-line fixture**, then walking every cell of every sheet. Script:
`scratchpad/rinput_census.py` (research instrument, not committed to the app).

> **A caution that shapes this whole document.** Nick's ground truth was measured
> on **CW-038/040 Harrow Lane** (two products). My census ran on **CareCompanions**
> (one product). Row numbers and reference counts differ between them **because
> the workbook's row layout is a function of business shape**. That is not a
> discrepancy to reconcile — it is the single most important structural fact for
> this design, and it is developed in Q1.

---

## Ground truth A–H — independent verification

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| **A** | "Model Inputs" is a read-only bridge, not an input sheet | **CONFIRMED, with a material exception (B)** | VERIFIED: Model Inputs holds **1,037 formula cells** and makes **817 outbound references** to schedules (Debt 272, Working Capital 231, Revenue Drivers 105, CapEx 105, Cash Equity 84, Payroll 20). It reads *from* schedules. |
| **B** | Some Model Inputs rows *are* hardcoded | **CONFIRMED, and larger than stated** | VERIFIED: **107 hardcoded cells over 7 rows** — COGS %, Marketing, R&D, G&A, Taxes (21 cells each, full path) plus **Payroll (col C only)** and **Interest Expense (col C only)**. Nick's list omits Interest Expense. Row *numbers* differ from Harrow Lane's (see Q1). |
| **C** | Model Inputs is not a complete chokepoint | **CONFIRMED — the claim holds; the counts are shape-dependent** | VERIFIED on CareCompanions: FINMO → Model Inputs **655**, Revenue Drivers **92**, Payroll **52**, Debt **19** (818 total). Nick measured 718/310/52/19 on Harrow Lane. Payroll and Debt match exactly; the two that move are the two that scale with line count. **The structural claim is true on both.** |
| **D** | Hardcoded surface spread across six sheets | **CONFIRMED, and wider than listed** | VERIFIED. Additional hardcoded rows not in the directive's list are enumerated in Q1 — notably Debt rows 22/24/25, CapEx rows 9/13, and the fact that Working Capital's "opening seeds" are **21-column rows where only column C carries a value**. |
| **E** | Input convention exists in design.py | **CONFIRMED — but it is almost entirely unapplied** | VERIFIED: `design.INPUT_FILL="FDF3DF"`, `design.INPUT_INK="1B4F8A"`, `design.input_cell()`. **It is called in exactly three places**: `dashboard_sheet.py:110` (toggle dropdowns), `valuation_sheet.py:194` (ASSUMPTION rows), `excel_utils.set_input_style` (helper). **Not one of the 2,967 hardcoded schedule cells is styled as an input.** See the finding below. |
| **F** | No sheet protection anywhere | **CONFIRMED** | VERIFIED: no `protection`/`sheet_protect`/`password` usage in any builder (the single grep hit is a MySQL password in `valuation_sheet.py`). |
| **G** | Named-range precedent exists | **CONFIRMED** | VERIFIED: `dashboard_sheet.py:34-35,93-97` defines `PeriodQuarters` and `PeriodYears` via `DefinedName`, consumed by Dashboard data validation. |
| **H** | Column C is the stub and behaves differently | **CONFIRMED** | VERIFIED: Model Inputs Payroll and Interest Expense are **col-C-only** hardcodes while their D–W siblings are formulas; Debt C7/C18/C22/C24/C25 and CapEx C7/C9/C13 are col-C-only; Working Capital rows 15–19 carry a value in C and `0` across D–W. |

### Finding not in the ground truth: the workbook already promises a convention it does not keep

**VERIFIED.** `cover_sheet.py:39` prints this legend to the client:

> *"Amber cells are inputs — change them and the whole model recalculates"*

The amber convention is applied to Dashboard dropdowns and Valuation assumption
rows only. **Every genuine driver — unit price, capacity, utilisation, capex,
interest rate, opening balances, distributions — is an unstyled plain number on
a schedule sheet.** A client who reads the Cover and then looks for amber cells
will not find the drivers, and will find amber on two things that are not
drivers.

This is worth stating plainly because it changes the framing of this project:
**the input sheet is not a new promise. It is the delivery of one the workbook
already makes.** It is also, on its own, an existing defect in a client-facing
document — recommended for separate triage regardless of what happens to
R-INPUT-01.

---

## Q1 — Input surface census

**VERIFIED** by walking every cell of the built workbook. Totals:

| Sheet | State | Formulas | **Hardcoded** | Text |
|---|---|---:|---:|---:|
| Cover | visible | 0 | 0 | 42 |
| Dashboard | visible | 17 | 0 | 32 |
| FINMO | visible | 2,340 | 21 | 147 |
| Valuation | visible | 260 | 8 | 110 |
| Revenue Drivers | visible | 159 | **294** | 72 |
| Payroll Schedule | visible | 708 | **503** | 475 |
| Debt Schedule | visible | 332 | **110** | 69 |
| CapEx Depreciation | visible | 163 | **45** | 50 |
| Working Capital | visible | 0 | **231** | 57 |
| Cash Equity Schedule | visible | 0 | **84** | 43 |
| Model Inputs | visible | 1,037 | **107** | 124 |
| Audit Source | hidden | 0 | 1,167 | 149 |
| Calc | hidden | 2,124 | 0 | 245 |
| Checks | visible | 639 | 397 | 1,054 |
| Diagnostics | visible | 0 | 0 | 30 |
| **Total** | | **7,779** | **2,967** | **2,699** |

### The census, bucketed

Builder module is `client_statements_output_excel/`. All rows below are
**VERIFIED** as to sheet, row, cell count and written value; the
module/function attribution is **VERIFIED** by reading the builder.

#### EDITABLE — belongs on the input sheet

| Sheet | Rows | Driver | Cells | Written by |
|---|---|---|---:|---|
| Revenue Drivers | 8, 9, 10 (× per product) | Capacity, unit price, utilisation | 21 each | `schedule_sheets.build_revenue_drivers_sheet` |
| Revenue Drivers | per-line COGS % (present only when captured) | COGS % of line revenue | 21 | same |
| Revenue Drivers | 18–28 (CareCompanions) / 26–36 (Harrow) | **Stage Ramp Contract** — QoQ target/max/spike, utilisation cap, COGS/Marketing/R&D/G&A/Lease % max, NI margin floor | 21 each × 11 rows | `schedule_sheets._stage_ramp_values` → same builder |
| Payroll Schedule | B7:B12 | Wage positioning tier, multiplier, burden assumptions | 6 | `schedule_sheets.build_payroll_schedule_sheet` (`assumptions` list, line 251) |
| Payroll Schedule | 27–86 block | Per-role, per-quarter Starting FTE and Hires | ~480 | same |
| Debt Schedule | C7 | Opening debt | 1 | `schedule_sheets.build_debt_schedule_sheet` |
| Debt Schedule | 8, 9, 12 | Issuance, requested repayment, interest rate | 21 each | same |
| Debt Schedule | C18, 19, 21, C22, C24, C25 | Lease opening, principal repayments, net additions, lease interest, ROU asset opening, lease asset depreciation | mixed | same |
| CapEx Depreciation | C7, C9, C13 | Opening PPE, lease additions, opening accumulated depreciation | 1 each | `schedule_sheets.build_capex_depreciation_sheet` |
| CapEx Depreciation | 8, 10 | Capital expenditures, depreciation rate | 21 each | same |
| Working Capital | 7–12 | AR days, inventory days, AP days, prepaid %, deferred revenue %, short-term debt % | 21 each | `schedule_sheets.build_working_capital_sheet` |
| Working Capital | 15–19 | Opening balances — cash, AR, inventory, AP, short-term debt (**value in C only**) | 21 each, 1 meaningful | same |
| Cash Equity | 7, 8, 9, 12 | Owner's capital, other equity, distributions, lease | 21 each | `schedule_sheets.build_cash_equity_sheet` |
| Model Inputs | COGS %, Marketing, R&D, G&A, Taxes | Solver-produced expense ramp paths | 21 each | `model_inputs_sheet.build_model_inputs_sheet` |
| Model Inputs | Payroll (C), Interest Expense (C) | Stub-period seeds | 1 each | same |
| Valuation | 8 rows | DCF assumptions already styled as inputs | 8 | `valuation_sheet` (`input_cell=True` when basis is ASSUMPTION) |

#### PLUMBING — does not belong on the input sheet

| Sheet | What | Cells | Why |
|---|---|---:|---|
| Audit Source | Engine-produced provenance values | 1,167 | The record of what the engine produced. Editing it would destroy the audit trail's purpose. |
| Checks | Tie-out thresholds and expected values | 397 | The model's self-validation. A client-editable check is not a check. |
| FINMO | 21 cells on one row | 21 | Statement plumbing, not a driver. |
| all | Period dates, stub definition, column headers, sheet structure | — | Structural. |

### The structural fact that dominates this design

**VERIFIED.** Row numbers are **a function of business shape**. The Stage Ramp
Contract sits at rows 18–28 for a one-product business and 26–36 for a
two-product one — an 8-row shift from one extra product. Revenue Drivers rows
8–10 become 8–11 and 15–18 with a second line.

**Consequence, stated as a design constraint rather than an option:** any input
sheet must address cells by a **stable key** — the `ctx.schedule_rows` /
`ctx.model_input_rows` registry (`excel_utils.WorkbookBuildContext:60-90`) or
named ranges — and **never by literal row number**. A design that hardcodes
`'Inputs'!C12` into a schedule formula will silently point at the wrong driver
for a business with a different line count. This is the single most likely way
to produce a wrong number in a delivered workbook, and it is entirely avoidable
at design time.

---

## Q2 — Dependency inversion

Today, **VERIFIED**: schedules hold hardcodes → Model Inputs reads schedules
(817 refs) → FINMO reads both (655 Model Inputs + 163 direct schedule).

### (i) INVERT IN PLACE — new `Inputs` sheet holds the hardcodes, schedules read it

Each currently-hardcoded editable cell becomes `='Inputs'!<cell>`; the Inputs
sheet carries the literal. Model Inputs bridge untouched.

- **Formula cells that change (VERIFIED count):** ~1,267 hardcoded editable
  cells become formulas (2,967 total hardcodes − 1,167 Audit Source − 397 Checks
  − 21 FINMO − 8 Valuation − ~107 Model Inputs if left in place). Add the same
  number of new literal cells on Inputs. **R32 movement: ~2,500 cells.**
- **What breaks:** nothing structurally. Every consumer keeps reading the same
  address it reads today; only the *content* of that address changes from a
  literal to a reference.
- **Checks:** continues to validate — **UNVERIFIED but low risk**, since Checks
  reads computed values by address and those addresses do not move.
- **Auditability:** *improved*. A lender tracing a number lands on a schedule
  cell that points at a single named input, rather than a bare literal with no
  provenance.
- **Cost:** every schedule builder gains an "emit a reference instead of a
  value" branch. Contained, mechanical, and reviewable per sheet.

### (ii) INPUTS AS SOLE SOURCE — collapse Model Inputs into the new sheet

Also rewires FINMO's 163 direct schedule references (VERIFIED count for
CareCompanions; ~381 on Harrow per the directive) to route through Inputs.

- **Formula cells that change:** (i)'s ~2,500 **plus** 1,037 Model Inputs
  formulas removed or relocated **plus** 163–381 FINMO references repointed.
  **R32 movement: ~3,700–3,900 cells, and FINMO's grid — the most heavily
  pinned surface in the workbook — moves.**
- **What breaks:** Model Inputs' 817 outbound references disappear or move
  wholesale. `ctx.model_input_rows` is consumed across builders; every consumer
  needs auditing.
- **Auditability:** *degraded in one specific way* — today Model Inputs gives a
  reader a single sheet showing every driver the statements consume. Collapsing
  it into an editable sheet conflates "what the model used" with "what you may
  change", which are different questions for a lender.
- **Verdict:** **not recommended as a first move.** It is the largest possible
  blast radius, it touches FINMO, and it buys nothing a client can perceive that
  (i) does not already deliver.

### (iii) The option the code suggests — INVERT IN PLACE, keyed through `ctx`

**This is the recommendation.** It is (i) with one addition that the existing
architecture makes almost free.

`WorkbookBuildContext` (**VERIFIED**, `excel_utils.py:60-90`) already maintains
`schedule_rows`, `model_input_rows`, `finmo_rows` and `source_rows` registries,
populated by each builder as it writes and read by later builders to construct
cross-sheet references. **The mechanism for "address a cell by stable key
instead of row number" already exists and is already used for every cross-sheet
reference in the workbook.**

So the input sheet should:

1. Be built **first**, before any schedule (see Q9 — builder order matters).
2. Register every input cell in a new `ctx.input_rows` registry keyed by driver
   identity (e.g. `("revenue_drivers", lob_index, product_index, "unit_price")`).
3. Have each schedule builder emit `='Inputs'!<ctx.input_cell(key)>` instead of
   the literal it writes today.

- **What breaks:** the same ~1,267 cells as (i), no more.
- **Checks:** unaffected — addresses do not move.
- **Auditability:** improved as in (i).
- **Why it beats (i) as written:** (i) invites hardcoded `'Inputs'!C12`
  addresses. Keying through `ctx` makes the shape-dependence problem from Q1
  **unrepresentable** rather than merely avoided by discipline.

**Recommendation: (iii).** Model Inputs stays exactly as it is — a read-only
bridge — and gets renamed (Q10) so the client is not confused by two
input-sounding sheets.

---

## Q3 — The 20-column problem

Every driver is a 21-column row (stub C + 20 quarters D–W). **VERIFIED.**

| Option | Assessment |
|---|---|
| **Full 20-column editable grid** | Honest and lossless — it is exactly what the model consumes. Wide (21 columns × ~60 driver rows), but the workbook is already this wide on six sheets and clients already scroll them. Builder emits what it already computes. |
| **Seed + growth rate generates the path** | Narrow and readable, but **lossy**: it cannot represent the paths the engine actually produced. The solver's ramps are not geometric — VERIFIED: CareCompanions depreciation rate runs 0.0506, 0.0533, 0.0561…, and the utilisation cap 0.65, 0.67, 0.69… A seed+rate input sheet **cannot reproduce the workbook it shipped with**, which is disqualifying. |
| **Seed + optional per-quarter override** | Two representations of one driver, and the builder must decide which wins. Adds a mode without removing the grid, since the grid is still needed for the override. |

**Recommendation: the full 20-column grid**, one row per driver, grouped by
section, with the stub column visually separated and labelled as the opening
period rather than a quarter.

**Stub handling, explicitly (VERIFIED constraint):** column C is not a period
like the others. Model Inputs Payroll and Interest Expense exist *only* in C;
Working Capital opening balances carry meaning *only* in C; CapEx C7/C9/C13 and
Debt C7/C18 are C-only. The input sheet must therefore render three distinct row
shapes — **C-only** (opening balances), **D–W only** (per-quarter drivers whose
stub value is derived), and **C–W** (drivers meaningful in every period) — and
the builder must know which shape each driver is. **TO-BE-TESTED:** whether every
driver falls cleanly into one of these three shapes, or whether a fourth exists.
The census suggests three; it has not been exhaustively proven.

---

## Q4 — Payroll

**VERIFIED:** Payroll Schedule carries 503 hardcoded cells over 103 rows —
B7:B12 assumptions (6 cells: wage positioning tier, multiplier, burden) plus the
per-role, per-quarter Starting FTE and Hires detail block (~480 cells). Payroll
is GPT-authored; that is settled and untouched here.

| Option | Assessment |
|---|---|
| Expose B7:B12 only | Small, safe, and the wage tier/multiplier are genuinely client-meaningful levers. But headcount — the thing an operator most wants to flex — stays off the sheet. |
| Expose an FTE-by-quarter summary that redistributes across roles | Requires inventing a redistribution rule the engine does not have. That rule would be *new modelling logic living in the workbook*, which is a different and much larger project. |
| Leave payroll off the input sheet in v1 | Ships the input sheet sooner, but the Cover would then point a client at an input sheet that omits their largest cost line. |

**Recommendation: expose B7:B12 plus the per-role Starting FTE and Hires block
as a full grid — i.e. treat payroll like every other schedule.**

Rationale: the detail block is already a per-quarter grid of literals; moving it
to the Inputs sheet under Q2(iii) is the *same mechanical transform* as every
other driver, with no new logic. The redistribution option is rejected because it
would put modelling judgement in the spreadsheet. Exposing only B7:B12 is
rejected because it omits headcount, and 480 of the 503 cells are the headcount
block — excluding them means payroll is not really on the input sheet at all.

**Cost, stated honestly:** payroll is by far the largest single block on the
input sheet (~480 of ~1,267 editable cells). If sheet size becomes the binding
constraint, payroll is the first candidate for its own grouped section or a
separate input sub-sheet — **but that is a layout decision, not an architecture
one.**

---

## Q5 — Circularity

Measured dependency graph (**VERIFIED**, from parsing every formula in the built
workbook):

```
Revenue Drivers ──92──► FINMO
       ▲   ▲
       │   └──42── Payroll Schedule
       │
       └──105── Model Inputs ──655──► FINMO
                     ▲
   Debt(272) WorkingCapital(231) CapEx(105) CashEquity(84) Payroll(20)

Debt Schedule ◄──20── CapEx Depreciation
FINMO ──2029──► Calc ──18──► Dashboard
FINMO ◄──209── Valuation
```

**Existing back-edge (VERIFIED):** Payroll Schedule → Revenue Drivers (42 refs).
CapEx → Debt Schedule (20 refs). Neither is circular today because Revenue
Drivers and Debt hold **literals** at those addresses.

**The risk under each architecture:**

- **(i)/(iii) INVERT IN PLACE:** a schedule cell that today holds a literal
  becomes `='Inputs'!X`. Since Inputs holds only literals and references
  *nothing*, **no cycle can form** — Inputs is a graph source by construction.
  The Payroll→Revenue Drivers edge continues to resolve to a literal, one hop
  further away. **UNVERIFIED but structurally sound**: the argument holds as long
  as the Inputs sheet contains no formulas at all.
- **(ii) SOLE SOURCE:** if Inputs absorbs Model Inputs' 1,037 formulas, Inputs
  stops being a graph source and starts reading FINMO-adjacent values. Any
  driver derived from a computed figure (e.g. a % of revenue) would create
  `Inputs → schedule → FINMO → Inputs`. **This is a real cycle risk and is a
  further reason to reject (ii).**

**Design rule this yields, and it is the one that makes bad states
unrepresentable:** *the Inputs sheet contains literals only — never a formula.*
Enforceable by a test that walks the built Inputs sheet and asserts no cell value
starts with `=`. Such a test must import the production builder, not restate it.

**Excel iterative calculation is not proposed and no design here requires it.**

---

## Q6 — Golden master and gate impact

**VERIFIED — both goldens walk hidden sheets.** `Surface.workbook_text_surface`
and `workbook_formula_grid` iterate `wb.worksheets`
(`surface.py:284`, `surface.py:832`), which includes hidden sheets. Confirmed
empirically: R49's pinned surface contains **both `Calc` and `Audit Source`**.

**VERIFIED — neither golden reads sheet visibility.** No reference to
`sheet_state` exists anywhere in `surface.py`. **Therefore hiding a sheet moves
neither digest** (relevant to Q7).

**Expected movement from this work:**

| Golden | Today | Movement |
|---|---|---|
| R32 formula grid | `8878c405e17d` | ~2,500 cells under (iii); ~3,900 and FINMO's grid under (ii) |
| R49 text surface | `4d5d81484fd8` | New sheet's labels + section headers; every Inputs row label is new static text |

### Re-bless protocol

1. **Never bundle.** One re-bless per phase (Q12), each with its own evidence.
2. **Purity before baseline.** Dump both surfaces at the previous baseline and at
   HEAD with the corrected provenance-asserting instrument
   (`replay_gate/_grid_dump.py`), diff leaf-by-leaf, and account for **every**
   changed leaf in a declared category. Zero unexplained.
3. **Values, not just formulas.** The distinguishing evidence between an intended
   inversion and a regression is that **every recalculated value must be
   identical**. A literal replaced by a reference to that same literal is a
   formula change with *no* value change. Any moved value is a regression until
   proven otherwise. Recalculate in real Excel and compare cell-for-cell by
   (sheet, row label, column).
4. **Both shapes.** Run the comparison on a single-line *and* a multi-line
   fixture, because Q1 shows row layout is shape-dependent.
5. **Negative control.** Confirm R31 (model payloads) does **not** move. This work
   must not touch the engine; if R31 drifts, the change escaped its blast radius.

**Live-data law check:** the Inputs sheet introduces literals sourced from the
engine's own output for this draft — i.e. **per-draft data, not live external
data**. R49's staticness rule already drops per-draft values by construction (it
intersects two different businesses), so driver *values* will not enter the text
pin. The *row labels* will, and should. **No violation of the live-data law is
foreseen** — but **TO-BE-TESTED**: confirm no driver label embeds a business name
or product name, since Revenue Drivers row labels today read
`"Primary line of business / In-home care visit/shift"` and **do** carry product
identity. If those labels move to the Inputs sheet verbatim, they will correctly
fall out of the R49 pin, leaving those rows unpinned. That is acceptable but
should be a conscious choice, not a surprise.

---

## Q7 — Sheet hiding

**Default position honoured: hide nothing until proven safe.**

**VERIFIED facts bearing on this:**
- Hiding moves neither golden digest (no `sheet_state` in either surface).
- Checks makes **493 outbound references** — Payroll 395, Debt 32, FINMO 19,
  CapEx 17, Audit Source 13, Revenue Drivers 10, Model Inputs 5, Cash Equity 2.
  Excel formulas resolve against hidden sheets normally, so **Checks continues to
  function** — **UNVERIFIED in this workbook specifically; TO-BE-TESTED** by
  hiding a sheet in a built file and confirming `Checks!B2` still reads `OK`.
- The Cover contents index (`cover_sheet.py`, `_CONTENTS`) lists **11 sheets**
  and already **omits Valuation** (A-129, confirmed) and correctly omits the
  hidden Calc and Audit Source.
- Cover describes Model Inputs as *"Every driver the statements are built from"*
  — which ground truth A shows is a **misdescription of a bridge sheet**.

**Recommended visibility map:**

| Sheet | Recommendation | Justification |
|---|---|---|
| Cover, Dashboard, FINMO, **Inputs** (new) | visible | The client's four-sheet path through the product. |
| Valuation | visible | Also fix A-129 so the Cover lists it. |
| Revenue Drivers, Payroll, Debt, CapEx, Working Capital, Cash Equity | **visible — do not hide** | Under Q2(iii) these become the *derivation layer*: they show how each input becomes a statement line. That is precisely the audit trail a lender follows. Hiding them to reduce clutter would remove the traceability that justifies the workbook's price. |
| Model Inputs (renamed, Q10) | **candidate to hide — but not in v1** | Once Inputs exists, this bridge is genuinely redundant *for the client*. It remains useful for internal debugging. Hide only after the Inputs sheet has shipped and been used. |
| Calc, Audit Source | remain hidden | Already hidden; correct. |
| Checks, Diagnostics | visible | Checks is the model's honesty; Diagnostics is provenance. |

**Hidden vs very-hidden:** `sheet_state="hidden"` is unhideable by any client
through the Excel UI; `"veryHidden"` requires VBA. **Recommendation: plain
`hidden`.** Very-hidden buys nothing here and would prevent a sophisticated buyer
from auditing — a hostile posture toward the paying customer.

**If any sheet is hidden, `_CONTENTS` must be updated in the same commit**, or
the Cover will index a sheet the client cannot open.

---

## Q8 — Protection and validation

**Correction to a premise in the directive.** **VERIFIED: there is no
LibreOffice recalculation step in the build pipeline.** A grep for
`libreoffice|soffice|recalc|CalculateFull` across the builder package, `python/`
and `scripts/` returns no pipeline step — the only COM recalculation in the repo
is in **test instruments** I and mini wrote. The builder writes the `.xlsx` with
openpyxl and it is delivered unrecalculated; Excel computes on open. **The
question "does protection survive the LibreOffice recalculation step" therefore
does not arise.** If a recalculation step is ever added, this must be revisited.

**VERIFIED capability (openpyxl 3.1.5, tested directly):**
- `ws.protection.sheet = True` and `ws.protection.password = ...` — supported.
- Per-cell `Protection(locked=False)` — supported.
- `DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0")`
  attached to a range — supported.

**Interaction with the Dashboard toggle — TO-BE-TESTED and important.** The
Dashboard's macro-free selector uses data validation dropdowns writing into
cells that INDEX/MATCH formulas read. **If Dashboard is protected and those
selector cells are not explicitly unlocked, the toggle stops working.** This is
the highest-value protection experiment to run first, because it would break a
shipped feature.

**Golden capture on a protected sheet — UNVERIFIED, expected neutral.**
Protection is sheet metadata; neither surface reads it (same argument as
visibility). Expected: no digest movement. **TO-BE-TESTED** alongside the
Dashboard experiment.

**Password vs no-password recommendation:** protection **without** a password.
It prevents accidental formula overwrite — the actual risk — while letting a
buyer who knows what they are doing unprotect and inspect. A password on a sold
model creates support burden and reads as distrust.

**Validation recommendation:** apply per-driver-class validation — non-negative
for capacity/price/balances, 0–1 for rates and percentages, integer for
headcount. All achievable without macros.

---

## Q9 — Builder architecture

**VERIFIED** (`workbook_builder.py:71-102`), invocation order:

```
revenue_drivers → payroll → debt → capex → working_capital → cash_equity
  → model_inputs → finmo → [break-even, ratios] → valuation → calc
  → dashboard → source_audit → checks → diagnostics → cover
```

**Builder order matters, and the reason is the `ctx` registry** (**VERIFIED**,
`excel_utils.WorkbookBuildContext:60-90`): each builder calls
`ctx.add_schedule_row(sheet, key, row)` / `add_model_input_row` /
`add_finmo_row` / `add_source_row` as it writes, and later builders call
`ctx.schedule_row(sheet, key)` to construct references. **A builder cannot
reference a sheet whose builder has not yet run**, because the row registry is
empty until then.

**What a new Inputs builder needs:**
1. **Run first** — before `build_revenue_drivers_sheet` — so every schedule
   builder can resolve `ctx.input_cell(key)`.
2. **Populate a new registry** (`ctx.input_rows`, or reuse `schedule_rows` under
   an `"Inputs"` sheet key) as it writes each driver row.
3. **Know the driver inventory before writing**, which means the data needed to
   lay out the sheet must be available from `DraftWorkbookData` before any
   schedule builder runs. **TO-BE-TESTED:** whether every driver currently
   written by a schedule builder is derivable from `DraftWorkbookData` alone, or
   whether some are computed *during* a schedule builder's run. If the latter,
   the Inputs sheet cannot be written first in one pass and needs a two-pass
   build (reserve rows, backfill values). **This is the single biggest unknown in
   the whole design and should be resolved before any build phase is scoped.**

**Sheet placement vs build order:** creation order determines tab order; the
Cover is built last and moved to position 0 (**UNVERIFIED** — inferred from it
being built last while appearing first). The Inputs sheet must be *built* first
but *positioned* after Dashboard, so tab position must be set explicitly.

**design.py guard test interaction (VERIFIED):** `tests/test_x1_design_system.py`
walks **every populated cell and every chart of every sheet** and fails on any
font, size, colour, fill, number format or chart built outside the design system.
**A new sheet is covered the moment it exists — nobody has to add it.** The
Inputs sheet must therefore use `design.input_cell()` for every input cell and
design-system fonts/formats throughout, or the guard test goes red. This is a
feature: it makes the amber convention mandatory rather than optional.

---

## Q10 — Naming

The client will see two sheets whose names both promise inputs. **VERIFIED** that
Cover currently describes "Model Inputs" as *"Every driver the statements are
built from"*, which describes a bridge as if it were the input layer.

**Recommendation:**
- New sheet: **`Inputs`** — short, unambiguous, first word a buyer looks for.
- Rename `Model Inputs` → **`Model Feed`** or **`Driver Bridge`**, and correct
  its Cover description to something honest such as *"What the statements read,
  assembled from the schedules"*.

**R49 cost of renaming, stated precisely:** R49 is keyed by
`{sheet_name: {address: text}}`. Renaming a sheet **re-keys every pinned cell on
it — all 124 of Model Inputs' text cells** — which reads in a diff as 124
deletions plus 124 additions. That is a large, noisy, entirely-explainable
movement. **It should therefore ride in its own commit and its own re-bless**,
separate from any formula work, so the diff is trivially reviewable. Bundling the
rename with the inversion would produce a re-bless nobody can read — exactly the
failure mode R49 exists to prevent.

---

## Q11 — Market scan

**Tagged UNVERIFIED throughout** — this is recalled industry convention, not
measured, and I did not consult live sources for this section. Treat as a
starting point for a buyer-facing design review, not as citation-grade.

Common conventions in sold forecast-model templates:

- **A single "Assumptions" or "Inputs" tab** placed immediately after a
  cover/instructions sheet is close to universal in commercially sold financial
  model templates.
- **Blue font for hardcoded inputs, black for formulas** is the long-standing
  investment-banking convention, frequently with green for cross-sheet links.
  **The project's existing `INPUT_INK = "1B4F8A"` is a navy-blue and already
  conforms to this convention** — a point in favour of ground truth E's
  instruction not to invent a new one.
- **Sheet protection without a password**, with only input cells unlocked, is
  typical for templates sold to non-modellers.
- **An instructions block at the top of the input tab** — what to change, what
  not to, units expected — is standard and cheap.
- **Scenario toggles** (base/upside/downside) via a dropdown feeding INDEX/MATCH
  are common in higher-priced templates. **The Dashboard already implements
  exactly this pattern macro-free** (VERIFIED), so the capability exists in-house
  if a scenario layer is ever wanted.

**Relevance to this product:** the input sheet is what a buyer touches most, and
convention-conformance lowers their learning cost. The three cheapest
buyer-visible wins are the instructions block, consistent amber/blue input
styling actually applied to drivers, and protection with inputs unlocked.

---

## Q12 — Phasing and build-side risk register

Each phase is independently shippable and gate-clean.

| Phase | Content | Gate impact |
|---|---|---|
| **0 — Resolve the unknown** | Answer the Q9 two-pass question: is every driver derivable from `DraftWorkbookData` before schedule builders run? Research only, no code. | none |
| **1 — Truth in labelling** | Apply `design.input_cell()` to the hardcoded driver cells **where they already live**. No structural change, no new sheet, no formula change. The Cover's amber promise becomes true. | R49 neutral (styling is not text); **R32 neutral** (no formula changes) |
| **2 — Rename and re-describe** | `Model Inputs` → `Model Feed`; correct its Cover description; fix A-129 so Valuation is indexed. | R49 re-bless, large but trivially explainable; R32 neutral |
| **3 — Inputs sheet, read-only mirror** | Build the `Inputs` sheet **first**, register `ctx.input_rows`, and have it *display* every driver by reading from the schedules. Nothing inverts yet. One sheet the client can read. | R32 + R49 re-bless; **all values unchanged** — the strongest possible evidence bar |
| **4 — Invert, one schedule at a time** | Per schedule: literals move to Inputs, schedule cells become `='Inputs'!<ctx key>`. Six independently shippable increments. | R32 re-bless per schedule; **every recalculated value must be identical** |
| **5 — Protect and validate** | Sheet protection with inputs unlocked; data validation per driver class. Dashboard toggle experiment first. | expected neutral, TO-BE-TESTED |
| **6 — Hide the bridge** | Hide `Model Feed`; update `_CONTENTS`. | digests neutral; Cover text changes |

### Build-side risk register

| # | Risk | What breaks | Detection | Unwind cost |
|---|---|---|---|---|
| R1 | **Row-number addressing** — an input reference hardcoded to a literal row points at the wrong driver for a different business shape | A delivered workbook shows a wrong number with no error | Build both a single-line and a five-line fixture and compare recalculated values; the shape-dependence is invisible on one shape | Low if caught in phase 4 (revert one schedule); severe if shipped |
| R2 | **Two-pass build required** (Q9 unknown) | Inputs sheet cannot be written before schedules; phase 3 stalls | Phase 0 resolves it before any code | Zero if resolved first; a re-architecture if discovered in phase 4 |
| R3 | **A formula lands on the Inputs sheet**, creating a cycle | Excel circular-reference warning in a client's file | Test that walks the built Inputs sheet asserting no value starts with `=` (importing the production builder) | Low |
| R4 | **Protection breaks the Dashboard toggle** | A shipped feature silently stops working | Drive the selector through COM after protecting, assert KPIs reslice | Low — protection is one flag |
| R5 | **Bundled re-bless** — rename + inversion in one commit | A digest movement nobody can review; a regression hides inside an intended change | Phase discipline; one re-bless per phase | Moderate — requires re-doing the purity proof |
| R6 | **Stub asymmetry mishandled** | Opening balances land in the wrong column; balance sheet fails to tie | `Checks!B2` and the accounting identity; caught by the values-identical bar in phase 4 | Low |
| R7 | **Payroll block size** makes the sheet unusable | Buyer-facing quality problem, not a correctness one | Human review of the built sheet | Low — layout only |

---

## Summary

**Recommended architecture — Q2(iii): invert in place, keyed through `ctx`.**
A new `Inputs` sheet built first, holding literals only, with every schedule
builder emitting `='Inputs'!<ctx key>` instead of the literal it writes today.
Model Inputs stays a bridge and gets renamed. ~1,267 cells invert; ~2,500 formula
cells move in R32. Rejected: collapsing Model Inputs into the input layer, which
triples the blast radius, moves FINMO's grid, introduces genuine cycle risk, and
degrades the lender-facing audit trail.

**Biggest build-side risk — row-number addressing (R1).** Row layout is a
function of business shape: the Stage Ramp Contract sits at rows 18–28 for one
product and 26–36 for two. A design that writes `'Inputs'!C12` into a schedule
formula will silently point at the wrong driver for a differently-shaped
business, and will look perfect on whatever fixture it was developed against.
The `ctx` registry already solves this for every other cross-sheet reference in
the workbook; the input sheet must use it, and the two-shape comparison must be
part of every re-bless.

**Smallest first phase — phase 1, truth in labelling.** Apply the existing
`design.input_cell()` convention to the driver cells where they already live. No
new sheet, no formula change, no structural risk, **both goldens neutral** — and
it makes the promise the Cover already prints to every client (*"Amber cells are
inputs"*) true for the first time. It is a one-sheet-at-a-time change, it is
independently valuable if the rest is never built, and it forces the driver
census to be exactly right before anything structural depends on it.
