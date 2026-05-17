# Phase 9 P3.16 — ExpressLogix E2E Pass (Clean)

**Iter:** Phase 9 P3.16 — Capital Lease Integration
**Implementation commit:** `7b8928b` (`phase_9_p3_16_capital_lease_integration`)
**E2E run commit:** see `phase_9_p3_16_express_e2e_pass_clean`
**Date:** 2026-05-17
**Target business:** ExpressLogix Shipping Services
**Source draft UUID:** `a5e0363963d546e0a597ce6dbdeb787d`
**Cloned draft UUID (run):** `8c7b7480fb254f1da4fdf4b525495d23`
**Run duration:** 285,453 ms (~4 min 45 sec)
**HTTP exit:** 0 (clean pass)
**Runner:** `Test Files/run_persisted_system_run.py --base-url http://127.0.0.1:5051 --draft-id a5e0363963d546e0a597ce6dbdeb787d --seed p3_16_e2e_express`
**API server:** `context/run_api_5051_p3_10.py` with `CONVERGENCE_TEST_MODE=true`

---

## Outcome

**A — Clean pass.** All four intake gates confirmed
(`ops_confirmed`, `market_confirmed`, `people_confirmed`,
`financials_confirmed`). `remaining_issue_count = 0`. No
machinery fail-fast fired. No validator violation reported by
the new capital lease block.

Workbook saved at
`C:/dev/Cilient Plans/ExpressLogix Shipping Services -- 05-17-2026 12-37-22.xlsx`.

## Capital lease state for ExpressLogix

ExpressLogix has **no capital lease** in its intake
(`lease_opening_balance_seed = 0`). All new balance-sheet
lines, the new cash-flow line, and the new Debt Schedule sheet
rows correctly evaluate to zero. Per the iter spec, this is the
"correctly inert" case for a business without a lease.

Spot-check of the workbook (formulas, since openpyxl can't
evaluate cached values):

- **FINMO Balance Sheet:**
  - PPE row 28 → `Model Inputs!D53` (PPE Closing Balance link)
  - Right-of-Use Asset row 29 → `Model Inputs!D50` (new
    `cash::Right-of-Use Asset` link)
  - Total Assets row 31 → `=D27+D28+D29` (Current Assets + PPE
    + ROU)
  - Capital Lease Obligation row 37 → `Model Inputs!D49` (new
    `cash::Lease Closing Balance` link in its own row)
  - Total Liabilities row 38 → `=D35+D36+D37` (Current Liab +
    LTD + Capital Lease Obligation)

- **FINMO Cash Flow:**
  - Capital Lease Principal Payments row 58 → `Model Inputs!D46`
    (`cash::Lease Principal Repayments`)
  - Financing Cash Flow references the new row instead of
    folding the model input directly.

- **Debt Schedule sheet Capital Lease section** (rows 17-26):
  - Lease Opening Balance Q0 = 0 (no lease in intake)
  - ROU Asset Opening Q0 = 0
  - Lease Asset Depreciation Q1 formula = `MIN((0/20), D24)` →
    correctly clipped to zero (no lease to depreciate)
  - ROU Asset Closing per-quarter rolls correctly via
    `MAX(0, opening - depreciation)`
  - "Requested Lease Principal Repayments" rows 19 show the
    pre-iter intake leak ($38,750/quarter from
    `annual_principal_payment`) but the actual "Lease Principal
    Repayments" row 20 = `MIN(38750, 0+0) = 0` — the clipping
    correctly absorbs the leak so no false cash effect lands.

## Handler engagement

No handler was invoked. Funding handler / stage ramp handler
did not engage because no validators fired requiring their
authority. This is consistent with the spec's NO HANDLER policy
for capital lease: downstream effects (cash pressure, interest
drag) flow through existing handlers only when their own
validators fire — which they didn't for this run.

## Machinery fail-fasts

All 6 capital lease machinery fail-fasts (Type 2) passed:

1. `capital_lease_builder_balance_drift` — snapshot matches
   FINMO state quarter-by-quarter.
2. `capital_lease_routing_double_count` — financing CF =
   `debt_issuance - debt_repayment + equity - distributions -
   lease_principal` exactly.
3. `capital_lease_interest_components_misaligned` — combined
   `interest` = `debt_interest_expense + lease_interest_expense`
   per quarter (both = 0 for ExpressLogix).
4. `capital_lease_asset_not_depreciating` — combined
   `depreciation` = `ppe_depreciation_expense +
   lease_asset_depreciation_expense` per quarter.
5. `capital_lease_orphaned_schedule_in_workbook` — not invoked
   (orphan detector available but no orphan present).
6. `capital_lease_principal_exceeds_obligation` — builder
   invariant respected by construction.

## Validators

All 9 Type 1 validators returned empty violation list for
ExpressLogix (no lease in intake → nothing to validate beyond
the zero invariants).

## Logs

- E2E stdout: `tmp/e2e_p3_16_express_7b8928b.out.log`
- E2E stderr: `tmp/e2e_p3_16_express_7b8928b.err.log`
- API stdout: `tmp/api_p3_16_5051.out.log`
- API stderr: `tmp/api_p3_16_5051.err.log`

## Next steps

P3.16 iter complete. The capital lease subsystem is in place
and correctly inert for businesses without a lease. A future
E2E run on a business with an actual capital lease intake value
will exercise the non-zero code path; if/when such a test
business is set up, the same E2E harness can verify the live
ROU / lease interest / lease depreciation flow.
