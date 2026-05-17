# Phase 9 P3.16b — ExpressLogix with Capital Lease E2E (Pass Clean)

**Iter:** Phase 9 P3.16b — E2E exercise of capital lease integration on a lease-bearing intake
**Parent commit:** `7b8928b` (`phase_9_p3_16_capital_lease_integration`)
**Date:** 2026-05-17
**Target business:** ExpressLogix Shipping Services (modified)
**Source draft UUID (modified):** `e112df06c6914889b1f104f05e97bcc0`
**Cloned draft UUID (run):** `5107f559865f45c9adec9f650a6741fb`
**Run duration:** 265,917 ms (~4 min 26 sec)
**HTTP exit:** 0 (clean pass on first attempt — no fix loop needed)
**Workbook:** `C:/dev/Cilient Plans/ExpressLogix Shipping Services -- 05-17-2026 12-55-06.xlsx`

---

## Source modification

A new draft `e112df06c6914889b1f104f05e97bcc0` was created as a copy
of canonical ExpressLogix source draft
`a5e0363963d546e0a597ce6dbdeb787d` with one field changed:
`financials_json.initial_lease` was set from `0.0` to `4500.0`
(monthly). After `_annualized_lease_commitment()` multiplies by
12, this seeds `lease_opening_balance_seed = $54,000` — the same
value used in the iter P3.16 spec's North Ridge worked example.
All other intake data is identical to the canonical draft.

## Outcome

**A — Clean pass on first attempt.** No fix loop required.
All four intake gates confirmed, `remaining_issue_count = 0`,
zero machinery fail-fast firings, zero validator violations.

## Capital lease trajectory (FINMO Q0..Q20)

```
Q  open_lease close_lease ROU asset_dep lease_int total_int total_dep | assets liab+eq diff
 0       54000       54000  54000        0        0     25000        0 | 1150000 1150000 0.00
 1       54000       15250  51300     2700     5535     55504     2934 | 3849645 3849645 0.00
 2       15250           0  48600     2700     1563     48969     3170 | 3890121 3890121 0.00
 3           0           0  45900     2700        0     44844     3407 | 3962479 3962479 0.00
 4           0           0  43200     2700        0     42281     3647 | 3994647 3994647 0.00
 8           0           0  32400     2700        0     32031     4617 | 4165978 4165978 0.00
20           0           0      0     2700        0      1281     7617 | 5298792 5298792 0.00
```

Verified behaviors:

- **Lease obligation pays off by Q2:** $54K → $15.25K → $0.
  The intake-leak $38,750/quarter requested principal correctly
  clips against the remaining balance in Q2 ($15,250 actual vs
  $38,750 requested).
- **ROU asset depreciates straight-line over 20 quarters
  independent of the principal schedule** (per iter spec
  §"DESIGN — DEPRECIATION"): $54K → $51.3K → $48.6K → ... → $0
  at Q20, decreasing by $2,700/quarter throughout, even after
  the lease obligation is paid off at Q2.
- **Lease interest declines with balance, zero after payoff:**
  $5,535 → $1,563 → $0. Computed at SBA rate (0.1025) ×
  opening balance per quarter, same rate as debt (spec §"DESIGN
  — INTEREST EXPENSE").
- **Combined P&L interest line** = debt interest + lease
  interest each quarter (e.g. Q1: $49,969 + $5,535 = $55,504).
- **Combined P&L depreciation line** = PPE depreciation + lease
  asset depreciation each quarter (e.g. Q1: $234 + $2,700 =
  $2,934). The lease asset depreciation persists for all 20
  quarters at $2,700/quarter.
- **Balance sheet reconciles every quarter** (`diff = 0.00`),
  including Q0 where ROU asset offsets the lease obligation on
  the liability side, so retained earnings is no longer
  artificially depressed by the pre-iter orphan treatment.

## Workbook spot-check

Debt Schedule sheet's Capital Lease section now shows nine
populated rows for the lease-bearing run:

- Lease Opening Balance: 54000 → 15250 → 0 → 0 → ...
- Requested Lease Principal Repayments: 38750/quarter (intake
  leak preserved as input; clipping happens in the next row)
- Lease Principal Repayments: 38750 → 15250 → 0 → ... (clipped)
- Lease Net Additions: 0 throughout (no new leases in scope)
- Lease Interest Expense: D18*0.1025 → declining-balance
  formula, populates correctly
- Lease Closing Balance: 15250 → 0 → 0 ...
- Right-of-Use Asset Opening: 54000 → carries from prior closing
- Lease Asset Depreciation: `MIN((54000/20), opening)` = 2700
  per quarter throughout
- Right-of-Use Asset Closing: 51300 → 48600 → ... → 0 (Q20)

FINMO sheet new rows:

- BS row 29 "Right-of-Use Asset (Capital Lease)" → 51300 at Q1
- BS row 31 "Total Assets" = Current Assets + PPE + ROU ✓
- BS row 37 "Capital Lease Obligation" → 15250 at Q1
- BS row 38 "Total Liabilities" = Current Liab + LTD + Capital
  Lease Obligation ✓
- CF row 58 "Capital Lease Principal Payments" → 38750 at Q1
- P&L "Interest" and "Depreciation" rows continue to show
  COMBINED values; internal splits are emitted to FINMO JSON
  but not displayed.

## Validators (Type 1)

All 9 validators returned empty violation list for the
lease-bearing snapshot:

1. capital_lease_obligation_at_q0 — payload seed matches intake.
2. capital_lease_asset_at_q0 — ROU opening matches intake.
3. capital_lease_obligation_amortizes_correctly — closing =
   opening - principal at every quarter.
4. capital_lease_asset_depreciates_linearly — ROU declines by
   $2,700/quarter, reaches 0 at Q20.
5. capital_lease_interest_at_sba_rate — interest = opening ×
   rate at every quarter.
6. total_interest_in_pnl_equals_components_sum — debt + lease
   = combined.
7. total_depreciation_in_pnl_equals_components_sum — PPE + lease
   = combined.
8. capital_lease_principal_in_cf_financing — financing CF
   includes lease principal exactly once.
9. lease_obligation_zero_at_term_end — closing = 0 once
   principal payments exhaust the obligation (Q2 onward).

## Machinery fail-fasts (Type 2)

All 6 passed:

- capital_lease_builder_balance_drift — snapshot agrees with
  FINMO at every quarter, every field (opening, principal,
  closing, interest, ROU, depreciation).
- capital_lease_routing_double_count — financing CF =
  `debt_issuance - debt_repayment + equity - distributions -
  lease_principal` to the dollar.
- capital_lease_interest_components_misaligned — combined =
  components sum.
- capital_lease_asset_not_depreciating — combined depreciation
  = PPE + lease asset depreciation sum.
- capital_lease_orphaned_schedule_in_workbook — not invoked
  (lease present, so no orphan condition).
- capital_lease_principal_exceeds_obligation — builder
  invariant respected by construction.

## Handler engagement

No handler invoked. Even though lease principal payment of
$38,750/quarter combined with debt principal payment of
$38,750/quarter is a meaningful cash outflow, the existing
cash buffer is large enough (cash_on_hand=$300K, plus operating
cash flow) that the funding handler's cash buffer validator
did not fire. Restoration loop did not fire because
profitability remained intact.

## Significance

This run is the first end-to-end validation of the P3.16
capital lease integration on a **lease-bearing** business. It
confirms the design:

- ROU asset and lease obligation are independent, on opposite
  sides of the BS, balanced by construction.
- Lease obligation can pay off faster than the asset
  depreciates; the asset continues straight-line through Q20.
- Combined P&L lines include lease components; internal splits
  are validated against the P&L total.
- Existing handlers continue to operate normally — capital
  lease is invisible to them except through the cash/income
  effects.
- No regression on businesses without a lease (verified in
  P3.16 first ExpressLogix pass at commit 1fde956).

## Logs

- E2E stdout: `tmp/e2e_p3_16b_express_attempt1.out.log`
- E2E stderr: `tmp/e2e_p3_16b_express_attempt1.err.log`

## Stop conditions

- Fix attempts used: 0 of 5 budget. No fix needed.
