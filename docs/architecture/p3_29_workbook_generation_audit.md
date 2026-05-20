# P3.29 — Workbook generation timing + input audit

**Status:** Read-only investigation. No code changes. No fixes proposed.
**Goal:** Determine whether workbook generation is structurally sound
(single render at end, reading finalized state) or has divergence
vulnerabilities (piecemeal writes / formula chains rebuilt from sources
that can differ from validator-blessed state).

**Headline finding:** Workbook generation timing is sound (single
render at end). But the workbook's FINMO sheet is **formula-rebuilt
from Model Inputs → schedule sheets → JSON sources that can differ
from the validator-blessed `finmo_json`**. The Audit Source sheet
preserves the validator-blessed values. The two-sheet duality is
*designed* (users can edit Model Inputs and FINMO recomputes), but it
*also* means a fresh-from-pipeline workbook can ship with FINMO
displaying numbers the validator never saw. The CareFirst P3.25
divergence ($35K/quarter Payroll → $677K Cash Q20) is the canonical
example, and the Checks-sheet baseline-reconciliation rows label this
divergence as "CHANGED (informational, does not fail Model Status)".

---

## Q1 — Workbook generation timing

**Single render at end. Single call site.**

The only workbook export invocation in the production pipeline is at
[api_handlers/intake_consult.py:7615-7623](../../python/api_handlers/intake_consult.py#L7615-L7623):

```python
from client_statements_output_excel.export_client_workbook import export_workbook_for_draft_id
client_workbook_path = str(
  export_workbook_for_draft_id(
    draft_id=result_draft_id,
    conn=conn,
    run_diagnostics=(diagnostic_payload or None),
  )
)
```

Ordering in the post-acceptance block:

1. **Acceptance verdict produced** (the post-intake validator chain
   completes, runs `_assert_global_invariants_via_sequence`, produces
   `acceptance_verdict`).
2. **Diagnostic payload built and persisted**
   ([intake_consult.py:7551-7592](../../python/api_handlers/intake_consult.py#L7551-L7592)).
3. **Workbook generated**
   ([intake_consult.py:7612-7623](../../python/api_handlers/intake_consult.py#L7612-L7623))
   — `export_workbook_for_draft_id` re-queries the persisted draft
   row, parses its JSON columns, and renders the workbook to disk.
4. **Workbook Model Status fail-fast** ([intake_consult.py:7649-7669](../../python/api_handlers/intake_consult.py#L7649-L7669))
   tries to open the workbook in Excel-COM to read `Checks!B2`.
   Logs and skips if Excel is unavailable; raises if status is read
   and ≠ "OK".
5. **Auto-email** ([intake_consult.py:7673-7704](../../python/api_handlers/intake_consult.py#L7673-L7704)).
6. **HTTP response** with `client_workbook_path`.

Comment at [intake_consult.py:7612-7613](../../python/api_handlers/intake_consult.py#L7612-L7613):
> "Generate the workbook regardless of acceptance verdict. The
> Diagnostics sheet renders from the just-persisted diagnostic row."

No piecemeal sheet writes during the run. The only Python writes that
touch the workbook happen inside `build_client_financial_model_workbook`
at [workbook_builder.py:30-59](../../client_statements_output_excel/workbook_builder.py#L30-L59),
which is one synchronous function building all sheets in-process and
returning the in-memory openpyxl workbook to be saved by
`export_workbook_for_row` at [export_client_workbook.py:99-104](../../client_statements_output_excel/export_client_workbook.py#L99-L104).

**Verdict:** Timing is sound. The workbook is the last artifact
produced. The 28-draft sweep's per-draft logs confirm this: the
`Saved client financial model workbook:` line follows
`System run duration: X ms` for every run that reaches finalize.

---

## Q2 — Per-sheet input sources

The workbook reads from the persisted `intake_consult_drafts` row via
[data.py:168-181](../../client_statements_output_excel/data.py#L168-L181):

```python
def draft_data_from_row(row, *, run_diagnostics=None) -> DraftWorkbookData:
  return DraftWorkbookData(
    draft_row=dict(row),
    model_input_json=parse_json_object(row.get("model_input_json")),
    finmo_json=parse_json_object(row.get("finmo_json")),
    payroll_headcount=parse_json_object(row.get("payroll_headcount")),
    debt_schedule=parse_json_object(row.get("debt_schedule")),
    planning_run_json=parse_json_object(row.get("planning_run_json")),
    run_diagnostics=run_diagnostics if isinstance(run_diagnostics, dict) else None,
  )
```

Five JSON sources + run_diagnostics. Each sheet's input lineage:

| Sheet                  | Direct reads from               | Reads as           |
| ---------------------- | ------------------------------- | ------------------ |
| Revenue Drivers        | `model_input_json.sections.revenue` (driver rows: Capacity, Unit Price, Utilization) | Hardcoded values per quarter; Revenue cell = `=Capacity * Unit Price * Utilization` per slot ([schedule_sheets.py:160-162](../../client_statements_output_excel/schedule_sheets.py#L160-L162)) |
| Payroll Schedule       | `payroll_headcount.rows` (detail rows) and assumptions | Hardcoded FTE/wages; Wage Cost = `(Avg FTE × Wage)/4`; Total Payroll = `SUMIFS(detail)` ([schedule_sheets.py:310-345](../../client_statements_output_excel/schedule_sheets.py#L310-L345)) |
| Debt Schedule          | `debt_schedule` JSON             | Hardcoded values + linking formulas |
| CapEx Depreciation     | `model_input_json.sections.schedules` (capex rows) | Hardcoded values |
| Working Capital        | `model_input_json.sections.balance_sheet` rows | Hardcoded values |
| Cash Equity Schedule   | `model_input_json.sections.balance_sheet` rows + financials_year1_json | Hardcoded values |
| Model Inputs           | **All schedule sheets above** (formulaic bridge) | Per-row formula `=Schedule!ref` ([model_inputs_sheet.py:67-72](../../client_statements_output_excel/model_inputs_sheet.py#L67-L72)) |
| FINMO                  | **Model Inputs only** + own subtotals | Per-cell Excel formula chain ([finmo_sheet.py:154-336](../../client_statements_output_excel/finmo_sheet.py#L154-L336)) |
| Audit Source           | **`finmo_json` directly** (pl, balance_sheet, cash_flow sections) | Hardcoded values, "Persisted FINMO" detail label ([source_audit_sheet.py:17-44](../../client_statements_output_excel/source_audit_sheet.py#L17-L44)). Sheet is hidden. |
| Checks                 | Cross-sheet formula comparisons | Formulas referencing FINMO + Audit Source + schedule sheets |
| Diagnostics            | `run_diagnostics` dict (persisted by `persist_run_diagnostics`) | Hardcoded values (planning_mode, score, verdict, handler info, realism check rows) |

### The critical formula chain for Payroll (Pattern P1 vector)

| Layer | What it reads | What it computes |
| ----- | ------------- | ---------------- |
| Payroll Schedule!Total Payroll (col D=Q1) | `payroll_headcount.rows` (headcount detail) | `=SUMIFS($M$start:$M$end, $A$start:$A$end, 0)` — sum of wage cost over all headcount rows whose quarter_index=0 |
| Model Inputs!Payroll (row R, col D) | Payroll Schedule!Total Payroll | `='Payroll Schedule'!D<row>` ([model_inputs_sheet.py:142-157](../../client_statements_output_excel/model_inputs_sheet.py#L142-L157)) |
| FINMO!Payroll (row 14, col D) | Model Inputs!Payroll | `='Model Inputs'!D<row>` ([finmo_sheet.py:186](../../client_statements_output_excel/finmo_sheet.py#L186)) |
| Audit Source!Payroll (col D) | `finmo_json.pl["Payroll"].values[1]` | Hardcoded number |

So the **same logical quantity** ("Q1 payroll dollars") flows down
two **independent** chains:

- Chain A (validator-blessed): `model_input.expenses::Payroll` →
  `build_python_finmo_json` → `finmo_json.pl["Payroll"]` →
  Audit Source!Payroll
- Chain B (workbook display): `payroll_headcount.rows` →
  Payroll Schedule SUMIFS → Model Inputs!Payroll → FINMO!Payroll

These chains share NO step. They can produce different numbers if
`payroll_headcount.rows` and `model_input.expenses::Payroll` are
inconsistent, which is exactly the Pattern P1 / Mirror Flavor 1
shape that P3.25 documented.

### Pattern-spot: which FINMO rows are similarly vulnerable?

Same shape (FINMO formula reads Model Inputs row that references a
schedule sheet built from a JSON source independent of `finmo_json`):

- **Revenue** ([finmo_sheet.py:180](../../client_statements_output_excel/finmo_sheet.py#L180)) — `is::Revenue` → Revenue Drivers!Total Revenue → built from `model_input_json.sections.revenue` Capacity × Unit Price × Utilization. Audit Source!Revenue reads `finmo_json.pl["Revenue"]`. Divergence vector: if `model_input.sections.revenue` is out-of-sync with what produced `finmo_json.pl["Revenue"]`. P3.22 Part 2 fail-fast (`revenue_driver_formula_contract_failed`) is supposed to catch this — Pinnacle Logistics tripped it at 3 ppb in P3.28.
- **COGS / Marketing / R&D / G&A** ([finmo_sheet.py:181-187](../../client_statements_output_excel/finmo_sheet.py#L181-L187)) — formulas like `=Revenue * Model_Inputs!Cost_of_Goods_Sold_pct`. The pct values come from `model_input.sections.expenses` (direct values, no schedule sheet). Less vulnerable; but the Revenue input to the multiplication is the formula-rebuilt Revenue, not the Audit Source Revenue.
- **Lease/Rent** ([finmo_sheet.py:185](../../client_statements_output_excel/finmo_sheet.py#L185)) — `is::Lease` → Cash Equity Schedule!Lease → reads from `model_input.sections.balance_sheet` Lease row. Independent from `finmo_json.pl["Lease/Rent"]`.
- **Interest / Depreciation** ([finmo_sheet.py:201-202](../../client_statements_output_excel/finmo_sheet.py#L201-L202)) — sums of `is::Interest Expense + cash::Lease Interest Expense` (and similar for Depreciation). P3.17 Phase 3c noted this divergence is exactly why these formulas now reference both components: the persisted FINMO already includes both, but the workbook was historically dropping the lease components. The fix aligned the chain; the duality persists.
- **Balance sheet items** ([finmo_sheet.py:206-264](../../client_statements_output_excel/finmo_sheet.py#L206-L264)) — Cash references Cash Flow!Ending Cash (own chain); AR/Inventory/Prepaid computed from `bs::AR Days × Revenue / days_in_quarter`; Debt rows read from Debt Schedule sheet; Owner's Capital/Other Equity/Distributions read from Cash Equity sheet. Every line is formula-rebuilt; every Audit Source line is the persisted balance_sheet value.
- **Cash Flow items** ([finmo_sheet.py:267-305](../../client_statements_output_excel/finmo_sheet.py#L267-L305)) — All reference FINMO's own income-statement / balance-sheet cells. Same chain-B vulnerability as Payroll/Revenue: if upstream diverges, this propagates.

**Conclusion:** Every FINMO sheet row that holds a financial quantity
is a formula chain anchored in `model_input_json` / schedule JSONs,
**not** in `finmo_json`. The validator consumed `finmo_json`. The
workbook user sees the formula-rebuild. Anywhere `finmo_json` and
`model_input_json` are inconsistent, FINMO and Audit Source diverge.

---

## Q3 — Audit Source vs FINMO duality

### Audit Source intent (per code)

[source_audit_sheet.py:20](../../client_statements_output_excel/source_audit_sheet.py#L20):
> `set_title(ws, "Audit Source", "Persisted system outputs used only for checks and audit tie-outs.")`

[source_audit_sheet.py:44](../../client_statements_output_excel/source_audit_sheet.py#L44):
> `ws.sheet_state = "hidden"`

The sheet renders `finmo_json.pl / balance_sheet / cash_flow`
section values as hardcoded numbers per quarter (no formulas). It is
hidden by default. Its `detail` column literally reads "Persisted
FINMO" ([source_audit_sheet.py:37](../../client_statements_output_excel/source_audit_sheet.py#L37)).

### FINMO intent (per code)

[finmo_sheet.py:157](../../client_statements_output_excel/finmo_sheet.py#L157):
> `set_title(ws, "FINMO", "Three-statement financial model. All formulas reference Model Inputs and in-sheet statement rows.")`

FINMO is the **visible**, user-facing three-statement model. Every
quantitative cell is an Excel formula referencing Model Inputs or its
own subtotals.

### Why two sheets?

The Checks sheet's note at [checks_sheet.py:857](../../client_statements_output_excel/checks_sheet.py#L857)
states the design intent explicitly:

> "CHANGED means assumptions were edited from the persisted run; it
> is informational and does not fail Model Status."

The duality assumes a **post-delivery editing workflow**: the
operator opens the workbook, adjusts a driver on a schedule sheet
(e.g. Capacity for Product X in Q5), and FINMO recomputes
end-to-end. Audit Source stays frozen as the "original system run."
Checks rows 166-172 compare the two and emit `CHANGED` if they
differ. Model Status only fails on `FAIL`-status checks (formula
errors, accounting equation breaks, etc.), not on `CHANGED`.

### The architectural problem

The duality is sound *if* and only if a **fresh-from-pipeline**
workbook starts with FINMO == Audit Source. If pipeline state can
produce a workbook where FINMO ≠ Audit Source from the moment of
generation, the user gets a "CHANGED" verdict on a workbook nobody
edited — and FINMO may show numbers the validator never saw.

P3.25's CareFirst case proved this:

| Quantity                | Chain B (FINMO)  | Chain A (Audit Source) | Delta     |
| ----------------------- | ---------------- | ---------------------- | --------- |
| Payroll Q1              | 142,725          | 107,440                | +35,285   |
| Q11 EBITDA              | ≈ −32,599        | ≈ +4,835               | −37,434   |
| Cash Q20                | (lower)          | (higher)               | −676,909  |

Validator passed 16/16 on `finmo_json`. User-facing FINMO shows a
catastrophically different picture. **This is the architectural bug
the duality enables.**

---

## Q4 — Structural divergence vectors

Enumerated paths by which workbook FINMO can differ from
validator-blessed `finmo_json`:

### V-1 — Mirror Flavor 1: `model_input` ↔ `payroll_headcount` drift
**File:line evidence:**
- Payroll FINMO formula: [finmo_sheet.py:186](../../client_statements_output_excel/finmo_sheet.py#L186) `={_mi(ctx, 'is::Payroll', col)}` → resolves to `=Model Inputs!<row>` → Model Inputs row reads `'Payroll Schedule'!<row>` ([model_inputs_sheet.py:142-157](../../client_statements_output_excel/model_inputs_sheet.py#L142-L157)) → Payroll Schedule Total Payroll = SUMIFS over `payroll_headcount.rows`.
- Audit Source Payroll: [source_audit_sheet.py:30-41](../../client_statements_output_excel/source_audit_sheet.py#L30-L41) reads `finmo_json.pl[*]["Payroll"]`.
- The divergence requires `payroll_headcount.rows` (Chain B) and
  `model_input.expenses::Payroll` (Chain A) to be inconsistent at
  persist time. P3.25 documented this; P3.26 Commit 2 routed
  payroll feasibility back through Handler C as the single writer.
  The doctrine pin is at [feasibility_repair.py:9-23](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L9-L23),
  but **the GPT exhaustion handler still lists `expenses::Payroll`
  in `GPT_AUTHORED_LEVER_IDS`** ([handler.py:54](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L54))
  — any non-feasibility-repair invocation that writes Payroll
  re-opens this vector.

### V-2 — Revenue driver formula vs persisted Revenue
**File:line evidence:**
- FINMO Revenue: [finmo_sheet.py:180](../../client_statements_output_excel/finmo_sheet.py#L180) `={_mi(ctx, 'is::Revenue', col)}` → Model Inputs!Revenue → `Revenue Drivers!Total Revenue`. Total Revenue is `=SUM(per-slot Revenue rows)` where per-slot Revenue is `=Capacity * Unit Price * Utilization` ([schedule_sheets.py:160-162](../../client_statements_output_excel/schedule_sheets.py#L160-L162) and [schedule_sheets.py:181-188](../../client_statements_output_excel/schedule_sheets.py#L181-L188)).
- Audit Source Revenue reads `finmo_json.pl["Revenue"]`.
- P3.22 Part 2 contract `revenue_driver_formula_contract_failed`
  is meant to catch persist-time disagreement; Pinnacle Logistics
  in P3.28 tripped it at 3 ppb (likely float-rounding tolerance
  issue, but the vector is real).

### V-3 — Excel quarter-grid math vs FINMO build math
**File:line evidence:**
- The FINMO sheet's per-line formulas (EBITDA, Net Income, balance
  sheet totals, cash flow chain) re-derive each line from the
  schedule + Model Inputs source values **without consulting**
  `finmo_json.pl/balance_sheet/cash_flow`. The Python FINMO build
  (`build_python_finmo_json` at
  [finmo_bridge.py:3816](../../python/client_intake_and_finmo/finmo_bridge.py#L3816))
  applies its own algebra, rounding, and clamping (e.g. LTD =
  MAX(0, Debt Closing − STD) at [finmo_sheet.py:245-250](../../client_statements_output_excel/finmo_sheet.py#L245-L250)
  comment notes the iter-15 fix that aligned the two paths).
- Anywhere the two formulas evaluate to different floats — e.g.
  due to rounding order, IFERROR fallbacks, or division-by-zero
  guards — FINMO ≠ Audit Source even with identical Model Inputs.

### V-4 — Multiple write paths to the same model_input row
**File:line evidence:**
- The intake_consult_draft persister
  [intake_consult_draft.py:1892-1906](../../python/client_intake_and_finmo/intake_consult_draft.py#L1892-L1906)
  accepts `model_input_json`, `finmo_json`, `payroll_headcount`,
  `debt_schedule` as independent SQL columns. Any caller can
  update one without the others. Audit:
  `_persist_unified_convergence_state` at
  [post_intake_convergence/runtime.py:1408](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L1408)
  + ~10 call sites in `runner.py` ([1267, 1391, 1565, 1939, 2458, 2664, 3322, 3378](../../python/client_intake_and_finmo/post_intake_convergence/runner.py#L1267)).
  Each invocation can pass different subsets. The initial-grid
  persister `persist_system_stage` ([post_intake_initial_grid/runner.py:354](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L354))
  + ~10 call sites is similar.

  These call sites are *supposed* to persist consistent state,
  but there is no SQL-level invariant enforcing
  `model_input.expenses::Payroll = sum(payroll_headcount.rows.payroll)`.
  Mirror Flavor 1 violations are detectable only by the assertions
  in `feasibility_repair.py`, which fire only on the
  feasibility-repair code path.

### V-5 — Schedule sheets read different JSON shapes than what FINMO build consumed
**File:line evidence:**
- The Revenue Drivers sheet reads `data.revenue_rows` =
  `model_input.sections.revenue` ([data.py:126-128](../../client_statements_output_excel/data.py#L126-L128)).
- `build_python_finmo_json` ([finmo_bridge.py:3816](../../python/client_intake_and_finmo/finmo_bridge.py#L3816))
  also reads `model_input_json` but via its own row resolution
  logic (`apply_derived_driver_policies_to_model_input` and
  similar). If the two readers handle the same fields differently
  (e.g. one applies a min-clamp the other doesn't), output diverges.

### V-6 — State mutations between validator-pass and workbook-generation
**File:line evidence:**
- Audit of the post-acceptance block
  ([intake_consult.py:7458-7623](../../python/api_handlers/intake_consult.py#L7458-L7623)):
  between `acceptance_verdict` being set and
  `export_workbook_for_draft_id` being called, the code persists
  diagnostics (does NOT mutate model_input/finmo/headcount) and
  then exports. The persistence happens to a separate
  `run_diagnostics` table.
- The draft row's `model_input_json` / `finmo_json` /
  `payroll_headcount` were last persisted by the planning runner
  *before* acceptance ran. So between persist-and-validate and
  workbook-export, the draft row should be stable.
- HOWEVER, the workbook calls `_select_draft_row` which re-queries
  the DB. If a *separate* writer (intake editing, another
  pipeline) touched the row in the interim, that change would
  ship in the workbook. In normal single-run operation this
  doesn't happen, but the code does not lock the row.

### V-7 — Excel evaluation order / formula-engine semantics
**Indirect.** Excel's recalculation may use slightly different
floating-point ordering than Python's. Most cells reconcile within
floating-point tolerance, but the P3.22 Part 2 fail-fast surfaced a
0.034 / $10M = 3 ppb mismatch that the contract rejected as
`revenue_driver_formula_contract_failed`. This vector exists for
every formula chain regardless of state alignment.

---

## Q5 — Structural fix shape

The architectural posture that would make the workbook a
deterministic clone of validator-blessed state:

### Option A — Hardcode FINMO to persisted values (eliminate the duality)

Render FINMO as **hardcoded values from `finmo_json`** (the same
shape Audit Source currently uses), and either drop the Model
Inputs sheet entirely or render it as a read-only display of the
inputs that produced the run.

**Sheets/formulas that change from "compute from inputs" to "render
finalized value":**

- FINMO sheet: every cell currently `={_mi(...)}` or computed
  algebra → hardcoded value from `finmo_json.pl /
  balance_sheet / cash_flow`. ~330 LOC in `finmo_sheet.py`.
- Audit Source sheet: redundant — could be removed, or kept
  hidden as a parallel "snapshot at run time" if users edit the
  Model Inputs.
- Checks sheet baseline rows: become trivial (FINMO == Audit
  Source by construction).
- Model Inputs sheet: stays as a formulaic bridge, but its
  values are now "the inputs that produced the run", not "what
  FINMO reads from".

**Loss:** users lose the ability to edit Model Inputs and watch
FINMO recompute. The workbook becomes a static financial-model
**report**, not an interactive **model**.

**Estimated scope:** ~500 LOC across `finmo_sheet.py` +
`source_audit_sheet.py` + `checks_sheet.py`. Plus deprecation
strategy for the Audit Source sheet.

### Option B — Enforce Chain A == Chain B at persist time

Keep both chains; add a post-persist invariant that **fails fast**
if `finmo_json` and `payroll_headcount` (and any other multi-surface
field) are inconsistent. Doctrine assertion already exists for
payroll: `assert_finmo_payroll_matches_headcount_schedule` at
[post_intake_headcount/schedule.py:3192](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3192). It is invoked
inside `apply_payroll_schedule_to_state`
([feasibility_repair.py:99-102](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L99-L102))
but **only on the feasibility-repair path**.

The fix: extend the assertion to fire on **every persist** of
`payroll_headcount` or `finmo_json`. Add analogous assertions for
other multi-surface fields (revenue, lease, debt). Use the
P3.26-style `post_intake_sequence_step_scope` to route the
invocation through canonical writers.

**Loss:** more rigid persistence contract; potentially more
fail-fast surface area to maintain.

**Estimated scope:** ~150 LOC for assertion + invocation
plumbing + tests. Per multi-surface field.

### Option C — Workbook reads ONLY from `finmo_json` for the FINMO sheet, schedule sheets read independent JSON

Hybrid: keep schedule sheets as today (so they show the source
data: headcount rows, debt schedule, etc.), but the FINMO sheet
renders `finmo_json` values directly. Model Inputs sheet becomes
the schedule-sheet → FINMO bridge but FINMO does NOT read from
it.

**Loss:** Model Inputs sheet becomes a non-load-bearing display
artifact; users editing schedule sheets no longer affect FINMO.

**Estimated scope:** ~250 LOC in `finmo_sheet.py`. Smaller than
Option A because schedule sheets keep their existing JSON inputs.

### Where workbook generation needs to move to (timing)

Already at the end. No move needed.

### What state needs to be finalized before workbook can read it

Already the case: `finmo_json`, `model_input_json`,
`payroll_headcount`, `debt_schedule`, `planning_run_json` are all
persisted by the planning runner before acceptance. The workbook
re-queries the row.

### Combined recommendation (sequencing)

1. **Cheapest immediate** — close the V-1 (Payroll) Mirror Flavor
   1 vector by tightening `GPT_AUTHORED_LEVER_IDS` to remove
   `expenses::Payroll` (enforcing P3.26 Commit 2 doctrine in
   code, ~20 LOC, Low risk — already in P3.28 audit memo §6).
2. **Cheap medium** — extend
   `assert_finmo_payroll_matches_headcount_schedule` to fire on
   every `payroll_headcount` persist, not only on the
   feasibility-repair path. Option B for the payroll surface
   only. ~50 LOC.
3. **Decision required** — Option A vs Option C for FINMO sheet
   rendering. Option A is more invasive but yields a deterministic
   FINMO==Audit Source guarantee at workbook open. Option C
   preserves user-editable Model Inputs but loses Mirror Flavor 1
   protection on every other surface. Option B can supplement
   either to cover persistence-side invariants.

---

## Headline answer

**Structurally:** workbook generation timing is sound; single
render, end of pipeline, reads finalized state.

**Vulnerable:** the FINMO sheet is a **formula-rebuilt
clone of Model Inputs**, which itself is a **formula-rebuilt
clone of schedule sheets**, which are built from `model_input_json`
+ `payroll_headcount` + `debt_schedule` — **independent of
`finmo_json`**. The validator consumed `finmo_json`. Any
inconsistency between the JSON sources produces a FINMO that
displays numbers the validator never blessed.

**The Audit Source sheet exists precisely because the architecture
*expects* this divergence as a feature** (user edits Model Inputs
post-delivery). But that same architecture means *bugs* in the
upstream pipeline (Pattern P1 / Mirror Flavor 1) ship as silent
divergences on day 1, labeled "CHANGED (informational)" by the
Checks sheet.

User direction required: pick between Option A (eliminate duality,
~500 LOC), Option B (enforce Chain A == Chain B at persist, scoped
~50-150 LOC), Option C (FINMO renders persisted, schedule sheets
keep edit-driven flow, ~250 LOC), or a combination. The doctrine
question — "is the post-delivery editing workflow load-bearing?" —
gates the choice.
