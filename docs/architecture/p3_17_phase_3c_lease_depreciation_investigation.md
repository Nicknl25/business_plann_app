# P3.17 Phase 3c Phase 1 — Lease Depreciation P&L Flow Investigation

**Iter:** Phase 9 P3.17 Phase 3c — Lease depreciation P&L flow fix.
**Symptom:** Workbook from P3.17 Phase 4 initial (lease-bearing ExpressLogix, file dated 2026-05-17 13:47:28, runner draft `9446dc72f280459a8fdcf04937c213f4`) shows the FINMO sheet balance sheet drifting by ~lease-asset-depreciation amount each quarter on the Excel computation path. Persisted FINMO `finmo_json` in MySQL is internally consistent (Phase 4 initial verification confirmed A = L+E = $4,500,777 at Q1 and at every other quarter using both component sum and stored totals). The drift is purely in the workbook formulas.

---

## A. ROU asset writeback path (Debt Schedule sheet)

[client_statements_output_excel/schedule_sheets.py:488-505](client_statements_output_excel/schedule_sheets.py#L488):

```python
rou_close = ctx.schedule_row(DEBT_SHEET, "Right-of-Use Asset Closing")
# ...
ws.cell(rou_close, col, value=f"=MAX(0,{local_ref(rou_open, col)}-{local_ref(lease_dep, col)})")
```

Where `lease_dep` = `Lease Asset Depreciation` row, computed at the same site:

```python
ws.cell(lease_dep, col, value=0 if idx == 0 else f"=MIN({per_quarter_dep_formula},{local_ref(rou_open, col)})")
```

So Path A (Debt Schedule sheet's "Right-of-Use Asset Closing") reduces ROU by `Lease Asset Depreciation` directly via in-sheet Excel formula at every Q1-Q20.

This row is then exposed via `Model Inputs!Right-of-Use Asset` and read by FINMO Balance Sheet row `Right-of-Use Asset (Capital Lease)` at [client_statements_output_excel/finmo_sheet.py:194](client_statements_output_excel/finmo_sheet.py#L194):

```python
_set_formula(ws, ctx.finmo_row("Balance Sheet", "Right-of-Use Asset (Capital Lease)"), col, f"={_mi(ctx, 'cash::Right-of-Use Asset', col)}")
```

So the asset side of the workbook BS declines by $2,700/quarter (= $54,000 / 20).

## B. Lease asset depreciation expense computation

Computed in two places (the divergence point):

**Path B1 — FINMO Python** ([python/financial_model_engine/finmo_model.py:480-485](python/financial_model_engine/finmo_model.py#L480)):

```python
ppe_depreciation_uncapped = quarter.expenses.depreciation_percent * max(0.0, previous_ppe)
ppe_depreciation_expense = min(ppe_depreciation_uncapped, max(0.0, previous_ppe))
rou_opening = previous_right_of_use_asset
lease_asset_depreciation_expense = min(per_quarter_lease_depreciation, max(0.0, rou_opening))
right_of_use_asset = max(0.0, rou_opening - lease_asset_depreciation_expense)
depreciation = ppe_depreciation_expense + lease_asset_depreciation_expense
```

This is the persisted-finmo-json computation. `depreciation` is COMBINED (PPE + lease) and emits to the `depreciation` field in `finmo_json` quarter rows. Verified in the live run: Q1 `depreciation=2934.0` = `ppe_depreciation_expense=234.0` + `lease_asset_depreciation_expense=2700.0`.

**Path B2 — Workbook Excel** ([client_statements_output_excel/schedule_sheets.py:556](client_statements_output_excel/schedule_sheets.py#L556) for CapEx, [schedule_sheets.py:493](client_statements_output_excel/schedule_sheets.py#L493) for lease):

The CapEx sheet's "Depreciation Expense" cell = `MIN(opening*rate, opening)` (PPE only).
The Debt Schedule sheet's "Lease Asset Depreciation" cell = `MIN(seed/20, rou_opening)` (lease only).

These exist as TWO SEPARATE rows on TWO SEPARATE sheets. There is no combined-depreciation cell anywhere in the workbook.

## C. Workbook P&L Depreciation chain

FINMO P&L "Depreciation" formula at [client_statements_output_excel/finmo_sheet.py:177](client_statements_output_excel/finmo_sheet.py#L177):

```python
_set_formula(ws, ctx.finmo_row("Income Statement", "Depreciation"), col, f"={_mi(ctx, 'is::Depreciation Expense', col)}")
```

Inspecting the rendered workbook (file 13:47:28):

```
FINMO Depreciation row 18: Q1 formula = "='Model Inputs'!D21"
Model Inputs row 21 'Depreciation Expense': Q1 formula = "='CapEx Depreciation'!D11"
Model Inputs row 51 'Lease Asset Depreciation': Q1 formula = "='Debt Schedule'!D25"
```

**The FINMO P&L "Depreciation" cell reads ONLY `is::Depreciation Expense`, which only contains PPE depreciation.** The lease asset depreciation row (`cash::Lease Asset Depreciation`, Model Inputs row 51) is exposed but never read into the P&L. So:

- Workbook P&L Q1 Depreciation = `'CapEx Depreciation'!D11` = $234 (PPE only)
- Persisted FINMO Q1 depreciation = $2,934 (PPE + lease)
- Display gap: $2,700/quarter, exactly equal to the straight-line lease asset depreciation $54,000/20.

## D. Workbook P&L Interest — same bug pattern

Same divergence in the interest chain:

```
FINMO Interest row 17: Q1 formula = "='Model Inputs'!D19"
Model Inputs row 19 'Interest Expense': Q1 formula = "='Debt Schedule'!D13"  (debt-only interest)
Model Inputs row 48 'Lease Interest Expense': Q1 formula = "='Debt Schedule'!D22"  (separate, never read)
```

- Workbook P&L Q1 Interest = `'Debt Schedule'!D13` = ((Opening Debt + Closing Debt)/2) * Interest Rate = $49,969 (debt only)
- Persisted FINMO Q1 interest = $55,504 (debt + lease = $49,969 + $5,535)
- Display gap: $5,535 at Q1, declining as the lease pays down.

## E. Net effect on workbook BS

Asset side ROU declines by $2,700/quarter as designed (Path A).
P&L expense flows are understated by $5,535 (interest) + $2,700 (depreciation) = $8,235/quarter — but Net Income then has a tax effect on the overstated pre-tax income. The Q1 effective tax rate around 18% means tax cost is overstated by $1,483, leaving NI overstated by $6,752. Retained Earnings inherits that overstatement.

Meanwhile, Operating Cash Flow adds back the understated Depreciation, so Cash is also understated by $2,700 (the depreciation that didn't add back). And NI flowing into OCF compensates partially.

The net Q1 BS drift is the difference between asset-side ROU drop ($2,700) and equity-side NI/RE growth (depends on tax effect). Magnitude in the user-reported pattern (`Q1: -$2,700, Q2: -$5,400, ... Q20: -$54,000`) is consistent with the lease asset depreciation accumulating on the asset side without a matching expense on the income side. The interest portion may be offsetting the tax effect differently, or the user looked at a specific subset that isolates depreciation.

The exact magnitude is not critical to the fix — the root cause is the same regardless: P&L Depreciation and Interest in the workbook do not include lease components.

## F. Existing validator coverage gap

[python/client_intake_and_finmo/post_intake_capital_lease/schedule.py](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py) has two relevant Type 2 fail-fasts:

- `fail_fast_lease_interest_components_misaligned` — checks that `finmo_row["interest"] == finmo_row["debt_interest_expense"] + finmo_row["lease_interest_expense"]` at every live quarter.
- `fail_fast_lease_depreciation_components_misaligned` — checks that `finmo_row["depreciation"] == finmo_row["ppe_depreciation_expense"] + finmo_row["lease_asset_depreciation_expense"]` at every live quarter.

Both check the PERSISTED FINMO state. The persisted `interest=55504` and `depreciation=2934` for Q1 are correctly the combined sums, so both validators pass. **The gap: neither validator inspects what the workbook formula will ultimately compute.** The workbook P&L formula references a different source than the persisted FINMO `interest`/`depreciation` fields and silently produces a smaller number.

This is the validator gap to repair: there needs to be a check that the workbook P&L formulas reference all components (debt + lease for Interest, PPE + lease for Depreciation), not just the legacy `is::Interest Expense` / `is::Depreciation Expense` cells that point to debt-/PPE-only sources.

## Doctrine pattern classification

**Doctrine §3 Pattern 1 (two paths compute the same value, drift at the boundary).** The two paths are:

- Path A (assets): `Debt Schedule!Right-of-Use Asset Closing` reduces ROU by `Lease Asset Depreciation` (in-sheet Excel formula). This path mathematically subtracts $2,700/quarter from the asset side.
- Path B (income): `FINMO!Depreciation` reads `is::Depreciation Expense` = `CapEx Depreciation!Depreciation Expense` (PPE only). This path does NOT add the $2,700/quarter lease asset depreciation as an income-statement expense.

The two paths must produce the same conceptual quantity (lease asset depreciation reduces ROU on the asset side AND reduces NI on the income side). Today they don't.

**Mirror Flavor 1 (direct reference):** the right fix is to have the workbook P&L formula reference both `is::Depreciation Expense` (PPE) AND `cash::Lease Asset Depreciation` (lease) so the rendered P&L line equals their sum. Same for Interest: reference both `is::Interest Expense` (debt) AND `cash::Lease Interest Expense` (lease). The Model Inputs cells for the lease components already exist — they just are not read by the P&L formula.

## Scope of the fix

Two file changes:

1. [client_statements_output_excel/finmo_sheet.py:176-177](client_statements_output_excel/finmo_sheet.py#L176) — append the lease component to the P&L Interest and Depreciation formulas.
2. (Validator repair, Phase 3) — add a workbook-structure assertion that the rendered FINMO P&L formulas reference both legacy and lease component cells, so future regression is caught.

The fix does not touch the persisted FINMO computation (already correct), does not touch the Debt Schedule sheet's lease section (already correct), does not touch any handler, and does not require softening any check.
