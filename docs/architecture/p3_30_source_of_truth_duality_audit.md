# P3.30 — Source-of-truth duality audit (root-cause)

**Decision context (per directive):**
- Options A / B / C from P3.29 are **rejected**.
- The structural fix must be upstream: eliminate redundant surfaces,
  or make one canonical and derive the others from it.
- Downstream-detection (assert FINMO == Audit Source after the fact)
  is not the goal.

**Headline:** there are two *kinds* of duality in the workbook.

1. **JSON-level dualities** — the same conceptual quantity is stored
   in multiple SQL columns / JSON sub-objects, and there exists a code
   path that can write one without writing the others. **Payroll is
   the only confirmed Type 1/2 instance.**
2. **Algebraic dualities** — two engines (Python `calculate_finmo_model`
   and Excel formula chain) compute the same quantity from the same
   model_input + schedule JSON inputs. They can disagree only via
   rounding, MAX/MIN clamping, or evaluation order. Most FINMO rows
   are Type 3 (same source); divergence vector is implementation
   discipline.

The structural fix sequence:
- **Payroll:** consolidate three surfaces to one canonical
  (`payroll_headcount.rows`); derive `payroll_headcount.quarter_totals`
  and `model_input.expenses["Payroll"].values` from it on read; close
  independent write paths.
- **Everything else:** align Excel formulas to Python algebra
  cell-by-cell (or eliminate the Excel re-derivation entirely; that
  is Option A and is out of scope here).

---

## Q1 — Enumerate the dualities

### Mapping convention

- **Surface A** = the JSON value the validator's `finmo_json` is built
  from (`build_python_finmo_json` reads `model_input_json` →
  `calculate_finmo_model` → `_series(metric_key)` →
  `finmo_json.pl/balance_sheet/cash_flow[*].values`).
- **Surface B** = the JSON value the workbook formula chain reads
  (schedule sheet → Model Inputs → FINMO).

### FINMO P&L lines (file:line for each)

| Line | Surface A source | Surface B source | Same JSON? |
| ---- | ---------------- | ---------------- | ---------- |
| Revenue | `model_input.sections.revenue[*].values` per driver (Capacity, Unit Price, Utilization) → `calculate_finmo_model` → `_series("revenue")` [finmo_bridge.py:737](../../python/client_intake_and_finmo/finmo_bridge.py#L737) | `model_input.sections.revenue` same → Revenue Drivers sheet `=Capacity*UnitPrice*Util` per slot [schedule_sheets.py:160-162](../../client_statements_output_excel/schedule_sheets.py#L160-L162) → Model Inputs!Revenue [model_inputs_sheet.py:114-125](../../client_statements_output_excel/model_inputs_sheet.py#L114-L125) → FINMO!Revenue [finmo_sheet.py:180](../../client_statements_output_excel/finmo_sheet.py#L180) | **YES** |
| COGS | `model_input.expenses["Cost of Goods Sold"].values` (ratio) × revenue | Same `model_input.expenses["Cost of Goods Sold"].values` direct (hardcoded into Model Inputs row at [model_inputs_sheet.py:173-184](../../client_statements_output_excel/model_inputs_sheet.py#L173-L184)) × FINMO!Revenue | **YES** |
| Marketing / R&D / G&A | `model_input.expenses["..."].values` × revenue | Same; same chain as COGS | **YES** |
| Lease/Rent | `model_input.expenses["Lease"].values` → `_series("lease_rent")` | Cash Equity!Lease reads `model_input.expenses["Lease"].values` direct [schedule_sheets.py:679-684](../../client_statements_output_excel/schedule_sheets.py#L679-L684) → Model Inputs!Lease [model_inputs_sheet.py:133](../../client_statements_output_excel/model_inputs_sheet.py#L133) → FINMO!Lease [finmo_sheet.py:185](../../client_statements_output_excel/finmo_sheet.py#L185) | **YES** |
| **Payroll** | `model_input.expenses["Payroll"].values` → `_series("payroll")` [finmo_bridge.py:743](../../python/client_intake_and_finmo/finmo_bridge.py#L743) | `payroll_headcount.rows[*]` (per-FTE detail) → Payroll Schedule SUMIFS [schedule_sheets.py:341-345](../../client_statements_output_excel/schedule_sheets.py#L341-L345) → Model Inputs!Payroll [model_inputs_sheet.py:134](../../client_statements_output_excel/model_inputs_sheet.py#L134) → FINMO!Payroll [finmo_sheet.py:186](../../client_statements_output_excel/finmo_sheet.py#L186) | **NO — separate JSON sources** |
| Interest | `debt_schedule` + `model_input.expenses["Interest Rate"]` → `calculate_finmo_model` → `_series("interest")` [finmo_bridge.py:746](../../python/client_intake_and_finmo/finmo_bridge.py#L746) | Debt Schedule sheet `Interest Expense = ((Open+Close)/2)*Rate` [schedule_sheets.py:454](../../client_statements_output_excel/schedule_sheets.py#L454) + `Lease Interest = LeaseOpen*Rate` [schedule_sheets.py:532](../../client_statements_output_excel/schedule_sheets.py#L532) → Model Inputs → FINMO!Interest = `is::Interest Expense + cash::Lease Interest Expense` [finmo_sheet.py:201](../../client_statements_output_excel/finmo_sheet.py#L201) | **YES (same JSON; different engines)** |
| Depreciation | `model_input.expenses["Depreciation"]` (rate) × `model_input.sections.schedules` opening PPE + capital lease seed/20 → `_series("depreciation")` | CapEx sheet `Depreciation Expense = MIN(Opening*Rate, Opening)` [schedule_sheets.py:596](../../client_statements_output_excel/schedule_sheets.py#L596) + Lease Asset Depreciation `MIN(LeaseSeed/20, ROU_Open)` [schedule_sheets.py:535](../../client_statements_output_excel/schedule_sheets.py#L535) → FINMO!Depreciation = `is::Depreciation Expense + cash::Lease Asset Depreciation` [finmo_sheet.py:202](../../client_statements_output_excel/finmo_sheet.py#L202) | **YES (same JSON; different engines)** |
| Taxes | `MAX(0, EBITDA - Interest - Depreciation) * rate` (Python) | `MAX(0, FINMO_EBITDA - FINMO_Interest - FINMO_Depreciation) * rate` (Excel) [finmo_sheet.py:203](../../client_statements_output_excel/finmo_sheet.py#L203) | **YES (same JSON; different engines)** |
| Net Income | Derived | Derived | **YES** |

### FINMO Balance Sheet lines

| Line | Surface A | Surface B | Same JSON? |
| ---- | --------- | --------- | ---------- |
| Cash | `_series("cash")` (Python ending cash chain) | `=FINMO!Ending Cash` self-reference [finmo_sheet.py:207](../../client_statements_output_excel/finmo_sheet.py#L207) | YES (engines) |
| AR / Inventory / Prepaid | `_series` from Python | `=(days/days_in_quarter)*Revenue` etc. [finmo_sheet.py:213-215](../../client_statements_output_excel/finmo_sheet.py#L213-L215); days from `model_input.sections.balance_sheet` (Working Capital sheet) | YES (engines) |
| PPE | `model_input.schedules.ppe_opening_balance_seed` + capex - dep chain | CapEx sheet closing PPE [schedule_sheets.py:597](../../client_statements_output_excel/schedule_sheets.py#L597) → Model Inputs!PPE Closing → FINMO!PPE [finmo_sheet.py:217](../../client_statements_output_excel/finmo_sheet.py#L217) | YES (engines) |
| ROU Asset / Capital Lease Obligation | Python lease chain | Debt Schedule lease chain | YES (engines) |
| AP | days × opex (Python) | days × opex (Excel) [finmo_sheet.py:229](../../client_statements_output_excel/finmo_sheet.py#L229) | YES (engines) |
| Short Term Debt | Python: SUM of next 4 quarters' actual_repayment | Excel: SUM of Debt Schedule!ActualRepayment Q+1..Q+4 [finmo_sheet.py:122-135](../../client_statements_output_excel/finmo_sheet.py#L122-L135) | YES (engines) |
| Deferred Revenue | Python: `model_input.bs["Deferred Revenue %"]` × revenue | Excel: same × FINMO!Revenue [finmo_sheet.py:237](../../client_statements_output_excel/finmo_sheet.py#L237) | YES (engines) |
| Long Term Debt | Python: MAX(0, debt_closing - STD) | Excel: same [finmo_sheet.py:245-250](../../client_statements_output_excel/finmo_sheet.py#L245-L250) | YES (engines) |
| Owner's Capital / Other Equity / Distributions | `model_input.sections.balance_sheet` | Cash Equity sheet reads same `model_input.sections.balance_sheet` [schedule_sheets.py:670-675](../../client_statements_output_excel/schedule_sheets.py#L670-L675) | YES |
| Retained Earnings | Python rollforward | Excel rollforward [finmo_sheet.py:258-261](../../client_statements_output_excel/finmo_sheet.py#L258-L261) | YES (engines) |
| Total Assets / Liabilities / Equity / L&E | Derived | Derived | YES |

### FINMO Cash Flow lines

| Line | Same JSON? |
| ---- | ---------- |
| Beginning / Ending Cash | YES (engines) |
| Δ Current Assets / Δ Current Liabilities | YES (engines; subset semantics — see [finmo_sheet.py:276-286](../../client_statements_output_excel/finmo_sheet.py#L276-L286)) |
| Operating Cash Flow / Investing / Financing / Net | YES (engines) |
| Capital Expenditures / Debt Issuance / Debt Repayment / Equity / Distributions / Lease Principal | YES (engines, all reading model_input/debt_schedule/capex) |

### Within-payroll_headcount sub-duality

`payroll_headcount` itself stores the same payroll dollars in **two
sub-objects**:

| Surface | Field path | Reader |
| ------- | ---------- | ------ |
| Sub-A | `payroll_headcount.quarter_totals[q].payroll` (aggregate per quarter) | Used by `apply_payroll_headcount_payload_to_model_input` to derive `model_input.expenses["Payroll"].values` ([schedule.py:2879-2895](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2879-L2895)); validated by `_validate_quarter_totals_match_title_rows` ([schedule.py:2856](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2856)) |
| Sub-B | `payroll_headcount.rows[*]` (per-FTE detail: `starting_fte`, `hires`, `annual_wage`, `payroll_taxes_benefits_percent`) | Used by Payroll Schedule sheet to render Detail rows and compute Total Payroll via SUMIFS over wage_cost+benefits [schedule_sheets.py:310-345](../../client_statements_output_excel/schedule_sheets.py#L310-L345) |

So payroll has **three** JSON surfaces for the same quarterly dollar
amount: `payroll_headcount.rows` (canonical detail), `payroll_headcount.quarter_totals` (aggregate), `model_input.expenses["Payroll"].values` (model-input copy).

---

## Q2 — Per-duality details

The only JSON-level duality (independent write paths to independent
sub-objects representing the same quantity) is **Payroll**. Every
other FINMO line is engine-duality (Excel formula vs Python algebra)
on a **shared** JSON source.

### Duality D1 — Payroll dollars per quarter

**Three surfaces:**

- S1 = `payroll_headcount.rows[*]` (detail, canonical-by-intent)
- S2 = `payroll_headcount.quarter_totals[q].payroll` (aggregate)
- S3 = `model_input.sections.expenses["Payroll"].values[q+1]` (model-input)

**a) Why do all three exist?**

- S1 is the source of truth Handler C authors directly (per-FTE wage
  detail). Doctrine pin: [feasibility_repair.py:9-23](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L9-L23).
- S2 is a pre-computed aggregate inside the same JSON column so
  downstream consumers don't have to re-sum the rows.
- S3 is the model_input shape the FINMO build chain expects (every
  expense line is a row in `expenses[*].values`).

**b) Ever supposed to legitimately differ?** No. Doctrine assertions
exist for both consistency checks:
- `_validate_quarter_totals_match_title_rows` at [schedule.py:2856](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2856) — enforces S1 ↔ S2.
- `assert_finmo_payroll_matches_headcount_schedule` at [schedule.py:~3192](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py) — enforces S2 ↔ finmo_json (and indirectly S3).
- `assert_payroll_headcount_model_input_applied` — enforces S2 ↔ S3.

**c) Canonical writer:** Handler C
(`estimate_payroll_headcount_schedule_with_gpt` at
[schedule.py:2180](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2180))
produces S1 + S2 together; `apply_payroll_headcount_payload_to_model_input`
([schedule.py:2809](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2809)) derives S3 from S2.

**d) Other writers that can hit S3 directly:**

- `GPT_AUTHORED_LEVER_IDS` includes `"expenses::Payroll"` at
  [handler.py:54](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L54).
  The GPT exhaustion handler can therefore write `model_input.expenses["Payroll"].values` directly without touching S1 or S2.
- `apply_exact_lever_updates_to_model_input` ([numeric_execution.py:870](../../python/client_intake_and_finmo/numeric_execution.py#L870)) applies lever updates to model_input, and the lever catalog can include payroll.
- Yesterday's removed `_rebuild_payroll_authority` (per P3.24/P3.26
  memos) was another writer; deleted in P3.26 Commit 2 chain, but the
  pattern recurs whenever a handler is granted authority over S3.

**e) Reconciliation today:** the three assertions named in (b) fire
ONLY on the payroll-feasibility-repair path
(`apply_payroll_schedule_to_state` at
[feasibility_repair.py:58-104](../../python/client_intake_and_finmo/post_intake_headcount/feasibility_repair.py#L58-L104)).
They do NOT fire on every persist of S3 by an arbitrary handler. So
if a GPT exhaustion run writes S3 with a value different from
sum(S1), S3 ends up at the handler's number, S1+S2 stay at Handler C's
prior number, the validator reads `finmo_json` (built from S3) and
sees the handler's number, the workbook renders the SUMIFS of S1 and
shows Handler C's prior number, divergence ships.

This is the CareFirst P3.25 mechanic.

### Engine-duality summary (all other FINMO lines)

For every non-Payroll line, both surfaces read the SAME JSON column
(model_input, debt_schedule, or sections.schedules). The divergence
risk is purely:
- Excel formula evaluates differently than Python's
  `calculate_finmo_model` (rounding, MIN/MAX clamping, division
  guards, evaluation order).
- One of the engines applies a derived-driver policy that the other
  doesn't (`apply_derived_driver_policies_to_model_input` at
  [finmo_bridge.py:1859](../../python/client_intake_and_finmo/finmo_bridge.py#L1859) — Python normalizes model_input before
  `calculate_finmo_model`, but the workbook reads model_input
  **as-persisted**, without the normalization step).

The Pinnacle Logistics P3.28 failure (delta 0.034 / $10M = 3 ppb on
revenue driver formula contract) is an instance of this:
`_enforce_revenue_driver_formula_contract` at
[finmo_bridge.py:630-633](../../python/client_intake_and_finmo/finmo_bridge.py#L630-L633)
fires because Python's `calculate_finmo_model` rounds slightly
differently than the strict `sum(Capacity × Unit Price × Utilization)`
contract.

---

## Q3 — Classification table

| Duality | Type | Reasoning |
| ------- | ---- | --------- |
| **D1 Payroll** (S1/S2/S3) | **Type 2** (derived view) | S1 is canonical; S2 and S3 are derived aggregates/copies. The fact that they are persisted independently is the root cause; the fact that any handler can write S3 directly is the propagation vector. |
| Revenue (engines) | Type 3 + formula tolerance gap | Same JSON source; Excel/Python algebra differ only via rounding. Pinnacle 3 ppb is real but not a *duality* — it's an implementation-tolerance mismatch. |
| COGS / Marketing / R&D / G&A (engines) | Type 3 | Same source; one multiplication. Algebra is identical. |
| Lease/Rent (engines) | Type 3 | Same source; direct read. |
| Interest / Depreciation (engines) | Type 3 | Same JSON; both engines walk debt/lease/capex schedules. Algebraic risk: clamping (e.g. `MIN(Opening*Rate, Opening)` for dep, `MAX(0, ...)` for LTD). |
| Taxes (engines) | Type 3 | Same algebra: `MAX(0, EBITDA - Int - Dep) × rate`. |
| Net Income / EBITDA / totals (engines) | Type 3 | Pure derived from above. |
| AR / Inventory / Prepaid / AP (engines) | Type 3 | Same days × revenue / days_in_quarter input. |
| STD / LTD / Capital Lease (engines) | Type 3 | Same schedules. |
| Owner's Capital / Other Equity / Distributions | Type 3 | Same `model_input.sections.balance_sheet` rows. |
| Retained Earnings (engines) | Type 3 | Both rollforward NI − Distributions. |
| Cash Flow lines (engines) | Type 3 | Both derive from same inputs. |

**Only D1 (Payroll) is a structural / JSON-level duality.** Every
other row is engine-duality on shared inputs.

---

## Q4 — Structural fix for Type 1/2 dualities

### D1 — Payroll structural fix

**Goal:** make S1 (`payroll_headcount.rows`) the single canonical
surface for payroll dollars. Eliminate the possibility of S2 / S3
holding different numbers from S1.

**Smallest-change shape:**

1. **Remove `expenses::Payroll` from `GPT_AUTHORED_LEVER_IDS`** at
   [handler.py:54](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L54).
   The GPT exhaustion handler no longer has authority to write S3
   directly. Payroll changes must go through Handler C (via the
   payroll feasibility repair route the P3.26 Commit 2 routed).
   - LOC: ~5 (one tuple entry + tests).
   - Risk: Low — already in the P3.28 audit's quick-wins list.
   - Code paths broken: none observed; the GPT exhaustion handler
     still has the other 12 levers.
2. **Make S3 a derive-on-read view in `apply_payroll_headcount_payload_to_model_input`'s contract.** The function already
   writes S3 from S2 ([schedule.py:2895](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2895)); the structural change is to mark the
   `model_input.expenses["Payroll"]` row with
   `controller_write = False` and `derived_driver = "payroll_headcount"`
   (already done at [schedule.py:2896-2897](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2896-L2897)) AND have downstream lever-update code
   honor that flag — refusing to write to a derived_driver row.
   - LOC: ~30 (the flag is already present and respected by Handler C's
     own catalog cleanup at [schedule.py:2857-2866](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2857-L2866); the gap is
     other writers that don't check the flag).
   - Risk: Medium — need to audit every `apply_*` model_input writer
     to honor `derived_driver`.
3. **Make S2 a derive-on-read view from S1.** Today
   `_validate_quarter_totals_match_title_rows` asserts S1==S2; the
   structural change is to **compute S2 on every read from S1** so
   they cannot disagree by construction. This is a JSON-layer
   normalization at the `payroll_headcount` deserializer.
   - LOC: ~50 — change `payroll_headcount` getter (or the
     `parse_json_object` step in [data.py:177](../../client_statements_output_excel/data.py#L177))
     to derive `quarter_totals` from `rows` post-load; remove
     `quarter_totals` persist or keep it as cache-only.
   - Risk: Medium — `quarter_totals` is consumed by several readers
     ([apply_payroll_headcount_payload_to_model_input](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2879-L2895),
     diagnostic builder, validators). Each must be updated to derive
     from S1 or to read the normalized view.
4. **Workbook Payroll Schedule sheet** continues to render Detail
   rows from `payroll_headcount.rows` (S1). Total Payroll SUMIFS
   stays. This becomes the canonical render — no change needed.

**Total estimated scope:** ~85 LOC across handler.py, schedule.py,
data.py, and a few tests. **Closes the CareFirst P3.25 vector by
construction** (no path can produce S1 ≠ S3 because S3 is no longer
independently writable).

### Engine-duality discipline (not a duality fix, but the meta-recommendation)

For Type 3 lines, the fix shape is **align the Excel formula to
Python's `calculate_finmo_model` exactly**. Concretely:
- Where Python applies `apply_derived_driver_policies_to_model_input`
  before computing, the workbook's Model Inputs sheet should
  similarly normalize OR the model_input persisted to the draft row
  should already be the normalized form. Today the persisted
  `model_input_json` is the pre-normalization form
  (`build_python_finmo_json` normalizes internally at
  [finmo_bridge.py:624-626](../../python/client_intake_and_finmo/finmo_bridge.py#L624-L626)) — the workbook reads
  pre-normalization. This is a hidden divergence vector.
- Where Python applies MIN/MAX clamping (e.g. LTD = MAX(0, ...) at
  [finmo_bridge.py](../../python/client_intake_and_finmo/finmo_bridge.py), depreciation = MIN(Opening×Rate, Opening) at
  [schedule_sheets.py:596](../../client_statements_output_excel/schedule_sheets.py#L596)), Excel formulas must apply the same clamp
  with the same operand order.
- Where Python rounds to 6 decimals via `round(..., 6)` at
  [finmo_bridge.py:733](../../python/client_intake_and_finmo/finmo_bridge.py#L733), Excel does NOT round (formulas
  retain full precision). This is the ~3 ppb gap Pinnacle hit.

**Per-line audit + alignment is needed for genuine FINMO == Audit
Source guarantee**, but each one is an implementation issue, not a
structural duality. Scope: ~30 LOC per line plus a regression check.

---

## Q5 — Resolving Type 3 candidates

The Type 3 classification holds for every non-Payroll FINMO line on
the JSON axis. The remaining divergence vectors are:

1. **Python applies `apply_derived_driver_policies_to_model_input`
   before the FINMO build; workbook does not.** This is a real
   pre-build normalization step that can modify revenue driver values
   (e.g. capacity-utilization expansion at the FINMO ceiling). If
   this normalization changes any model_input field, the workbook
   reads the un-normalized number and the validator reads the
   normalized number. Resolution: **persist the normalized model_input
   to the draft row** (i.e. apply the normalization step BEFORE the
   final persist), so both engines read the same starting point.
2. **`_enforce_revenue_driver_formula_contract`** fires at
   [finmo_bridge.py:630-633](../../python/client_intake_and_finmo/finmo_bridge.py#L630-L633) when Python's revenue computation
   disagrees with the strict `sum(Cap × Price × Util)` formula. If
   Python's clamping or aggregation differs from the strict formula,
   this fail-fast catches it. The workbook uses the strict formula.
   Resolution: align Python's revenue computation to the strict
   formula (or vice versa) so the contract holds for every row.
3. **Excel does not round; Python does (`round(..., 6)`).**
   Resolution: either remove the Python rounding OR add an Excel
   `=ROUND(..., 6)` wrapper to every FINMO formula. Recommend
   removing Python rounding; the precision is preserved in
   `finmo_json` and the validator already tolerates float precision.

None of these are duality issues. They are calibration-of-two-engines
issues that the user has already chosen to keep two of (per the
Option-A rejection).

---

## Q6 — Audit Source timing window

**Audit Source sheet population:**
[source_audit_sheet.py:17-44](../../client_statements_output_excel/source_audit_sheet.py#L17-L44) — populated synchronously
during workbook build, inside `build_client_financial_model_workbook`
at [workbook_builder.py:46](../../client_statements_output_excel/workbook_builder.py#L46). The function reads
`data.finmo_json` which is captured at `draft_data_from_row` time
([data.py:175](../../client_statements_output_excel/data.py#L175)) — i.e. the parsed JSON from the
`intake_consult_drafts.finmo_json` column **at the moment the
workbook export call selects the row** ([export_client_workbook.py:122](../../client_statements_output_excel/export_client_workbook.py#L122)).

**FINMO formula evaluation:** happens when Excel opens the workbook
(not at write time). At write time, FINMO cells are stored as
formula strings. The Audit Source cells are stored as hardcoded
numbers.

**Window between Audit Source write and FINMO evaluation:** the
entire time between workbook generation and a user opening the file
in Excel. During this window:
- `finmo_json` in the DB cannot change the workbook's Audit Source
  numbers (they were copied at write time).
- `model_input_json` in the DB cannot change the workbook's Model
  Inputs / FINMO cells (they were copied at write time).
- Excel will recompute FINMO formulas from the Model Inputs cells
  ALREADY in the workbook. The workbook is self-contained.

**Conclusion on timing:** there is **no in-pipeline window** where
finmo_json could change between Audit Source population and FINMO
formula evaluation. Both surfaces are frozen into the workbook at
write time. The FINMO formula evaluates against the snapshot Model
Inputs that were written to the workbook in the same pass that wrote
Audit Source.

**This means the CareFirst divergence is NOT a timing root cause.**
It is purely a write-state inconsistency at workbook-generation time:
the draft row's `payroll_headcount.rows` and
`model_input.expenses["Payroll"].values` were inconsistent in the
DB *before* the workbook was generated. The workbook faithfully
rendered both inconsistent values into two different sheets.

**This is the proof that the structural fix must be upstream of the
workbook**, at the JSON-write layer for Payroll specifically.

---

## Summary recommendation

| Duality | Type | Structural fix | Est. LOC | Risk |
| ------- | ---- | -------------- | -------- | ---- |
| D1 Payroll | Type 2 | (i) Remove `expenses::Payroll` from `GPT_AUTHORED_LEVER_IDS`; (ii) honor `derived_driver` flag in every model_input writer; (iii) derive `quarter_totals` from `rows` on read | ~85 | Med |
| All other FINMO lines | Type 3 | Per-line Excel-vs-Python formula alignment + persist normalized model_input | ~30 per line; ~25 lines | Low–Med |

Sequencing:
1. **Now** — D1 (i): remove Payroll from handler catalog (~5 LOC).
   Closes the active vector immediately.
2. **Next** — D1 (ii) + D1 (iii): consolidate Payroll to canonical
   `rows`. Closes the structural vector permanently. ~80 LOC.
3. **Then** — Engine-alignment audit per line. Each is independent;
   can be sequenced after Tier 2 fixes
   (stage_ramp awareness, cash buffer handler).

**Doctrine question for user:** the FINMO column on the
`intake_consult_drafts` table currently stores the *output* of
`build_python_finmo_json` (which has rounding + normalization
applied). The workbook re-renders from `model_input_json` (which
does not). If we persist the normalized `model_input_json` instead
of (or in addition to) the un-normalized form, all engine-duality
vectors collapse to "Excel formula tolerance". That is a smaller
follow-on architecture change (~40 LOC) that complements D1
without adopting Option A.

No code changes proposed in this memo. User direction required for
the D1 sequencing and the model_input-normalization question.
