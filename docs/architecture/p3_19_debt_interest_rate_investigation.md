# P3.19 Phase 1 — Debt Interest Rate Investigation

**Iter:** Phase 9 P3.19 — Debt interest rate is being applied per-quarter without scaling, producing ~4× inflated interest expense.

**Confirmed:** Real bug. Every plan with non-zero debt has had inflated interest. The bug predates P3.16 / P3.17.

---

## A. Where the SBA rate is stored

**Source:** SBA 7(a) loan database lookup, [finmo_bridge.py:1116](python/client_intake_and_finmo/finmo_bridge.py#L1116):

```python
annual_rate = round(float(median_rate_pct) / 100.0, 6)
source = {
  "source": "sba_loan_7a_raw",
  ...
  "median_rate_pct": round(float(median_rate_pct), 4),
  "annual_rate_decimal": annual_rate,
}
```

`median_rate_pct` is the median of `InitialInterestRate` values from `sba_loan_7a_raw` table (e.g. 10.25). Divided by 100 → `annual_rate = 0.1025` (decimal). Explicitly named `annual_rate_decimal` — unambiguously annual.

**Policy storage:** `derived_driver_policies.debt_interest_rate_policy.annual_rate_decimal = 0.1025`. ([finmo_bridge.py:3635](python/client_intake_and_finmo/finmo_bridge.py#L3635))

This policy storage is correct as-is. The number 0.1025 is the SBA-derived annual rate; it should not be changed.

## B. Where the rate is consumed

**Bridge writes the annual rate directly into the per-quarter `Interest Rate` row** — [finmo_bridge.py:3301](python/client_intake_and_finmo/finmo_bridge.py#L3301) and [:3334](python/client_intake_and_finmo/finmo_bridge.py#L3334):

```python
elif label == "Interest Rate":
    values.append(round(interest_rate_baseline, 6))   # 0.1025 (annual) — no /4
```

No conversion. The same value flows into both the Q0 seed and the Q1..Q20 live rows.

**Three downstream formulas consume it as if it were a per-quarter rate:**

1. **FINMO Python** ([finmo_model.py:461](python/financial_model_engine/finmo_model.py#L461)) — debt interest:
   ```python
   interest = ((debt_opening + debt_closing) / 2.0) * interest_rate
   ```

2. **FINMO Python** ([finmo_model.py:477](python/financial_model_engine/finmo_model.py#L477)) — lease interest (added in P3.16):
   ```python
   lease_interest_expense = max(0.0, lease_opening) * interest_rate
   ```

3. **Debt schedule plan** ([post_intake_debt_schedule/schedule.py:282](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L282)):
   ```python
   interest_expense = int(round(((opening_debt + closing_debt) / 2.0) * interest_rate))
   ```

4. **Workbook Debt Schedule Excel** — [schedule_sheets.py:454](client_statements_output_excel/schedule_sheets.py#L454):
   ```python
   ws.cell(interest_exp, col, value=f"=(({local_ref(debt_opening, col)}+{local_ref(closing_debt, col)})/2)*{local_ref(interest_rate, col)}")
   ```

5. **Workbook Lease Interest Excel** (added in P3.16) — [schedule_sheets.py:505](client_statements_output_excel/schedule_sheets.py#L505):
   ```python
   ws.cell(lease_interest, col, value=f"...={local_ref(lease_open, col)}*{rate_cell_value}")
   ```

Every site applies `rate × balance` once per quarter without dividing by 4. None of them know the rate they're consuming is annual.

## C. Walk-through — ExpressLogix Q1 on $500K LTD

Run draft: `3f7fd829237c40c0883fd19e41e51846` (P3.17 Phase 4 final, lease-bearing ExpressLogix).

Persisted FINMO Q1:
```
debt_opening_balance:  500,000
debt_closing_balance:  475,000
avg debt:              487,500
debt_interest_rate:    0.1025          (stored field — same value as Interest Rate row, slot 1)
debt_interest_expense: 49,968.75       (= 487,500 × 0.1025)
```

- Inferred per-quarter rate: 0.1025 = **10.25% per quarter**
- Inferred annualized: 0.1025 × 4 = **41.00%**

For a $500K SBA loan at 10.25% annual, the **correct** Q1 interest is approximately $12,500 (= 500K × 0.1025 / 4). The system is charging **$49,969**, which is roughly the **full year's interest in one quarter**.

Intake-implied rate cross-check (separate signal): `annual_interest_payment / total_debt_outstanding = 25,000 / 500,000 = 5.0%`. The system overrides this with the SBA-policy 10.25% per the policy contract, then mis-applies it as quarterly.

## D. Workbook is consistent with app

Workbook `Debt Schedule!D13` (Interest Expense Q1) formula: `=((D7+D11)/2)*D12` where `D12 = 0.1025`. Excel computes the same $49,968.75 as the app. Both the app and the workbook apply the annual rate per-quarter without scaling — same bug in both paths. The workbook is a faithful reflection of the (buggy) app math.

## E. Cross-business check

| Business | Source draft | Q1 debt | Q1 interest stored | Per-quarter rate | Annualized |
|---|---|---:|---:|---:|---:|
| ExpressLogix (lease bearing, P3.17 Phase 4) | `3f7fd829...` | $500,000 | $49,968.75 | 10.25% | **41.00%** |
| NexGen (intake) | `51ab9a6d...` | $300,000 LTD, $0 annual interest | not yet run with finmo | n/a | n/a |
| Sunny (intake) | `6c7544ec...` | $0 LTD | n/a | n/a | n/a |
| ExpressLogix leaseless (P3.14 prior) | `a5e03639...` | $500,000 | $49,968.75 (per iter directive) | 10.25% | **41.00%** |

NexGen has $300K LTD but `annual_interest_payment = 0` in intake. Sunny has no debt. Both ExpressLogix scenarios (lease + leaseless) have $500K LTD and exhibit the same per-quarter rate = annual rate = 4× over-charge.

**Conclusion:** Every business with non-zero debt exhibits the bug. Sunny is the only one of the three canonical test businesses unaffected (because it has no debt to charge interest on). NexGen's debt would exhibit it if `Interest Rate` were non-zero — but intake says zero interest, so the rate likely flows from SBA policy and triggers the bug there too on its $300K LTD.

## F. Why the realism gate didn't catch this

[post_intake_realism/schedule_sanity.py:351](python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py#L351) **`_check_debt_rate_realism`** explicitly assumes the rate is per-quarter ([line 376-377](python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py#L376)):

```python
# quarterly -> annualized
produced_rate = float(rate) * 4.0
```

For ExpressLogix the checker reads `debt_interest_rate = 0.1025` and computes `produced_rate = 0.41 = 41%`. The SBA band is typically ~5-10% annual. **41% should fail the realism band.**

Why doesn't it fire? The realism check returns `status="skipped"` when:
- No NAICS coverage for `sba_initial_interest_rate` ([line 394](python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py#L394))
- Or band/tolerance unavailable ([line 415](python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py#L415))

For the businesses we've run, the recent acceptance gate trace shows `sba_initial_interest_rate` is NOT in the `realism_checks` summary list — meaning the check was either not invoked or always skipped for these NAICS codes. So the realism gate that should have caught the bug has been silently no-op'ing.

## G. The contract gap

The system has an implicit contract:
- `derived_driver_policies.debt_interest_rate_policy.annual_rate_decimal` = annual rate (correctly named)
- `expenses::Interest Rate` row = **per-period (quarterly) rate** (implied by every consumer's formula, including the realism check that multiplies by 4 to annualize)

The bridge code at [finmo_bridge.py:3301](python/client_intake_and_finmo/finmo_bridge.py#L3301) violates this contract: it writes the annual policy value into the per-quarter row without conversion. Every downstream computation (FINMO, debt schedule, workbook) faithfully consumes the bad value.

## H. Fix scope — two clean options

### Option A (recommended) — Mirror Flavor 1 collapse at the bridge

Convert annual to quarterly at the single point where the rate is written into the `Interest Rate` row.

Change [finmo_bridge.py:3301](python/client_intake_and_finmo/finmo_bridge.py#L3301) and [:3334](python/client_intake_and_finmo/finmo_bridge.py#L3334):

```python
# Before
values.append(round(interest_rate_baseline, 6))
# After (rate stored as annual in policy; row consumes per-quarter)
values.append(round(interest_rate_baseline / 4.0, 6))
```

That single point conversion makes every downstream consumer immediately correct without changing any formula or any other site. The realism check's `× 4.0` annualization stays correct. The policy `annual_rate_decimal` stays unchanged (clearly annual).

Pros:
- Single change site
- Honors the per-quarter contract of `Interest Rate` row that every consumer already assumes
- Policy storage remains self-documenting (annual)
- Workbook display will show 2.56% (per-quarter), which mirrors how every formula in the workbook consumes it

Cons:
- Workbook `Interest Rate` cell displays per-quarter rate; a user reading "Interest Rate: 2.56%" in Excel may be momentarily confused. Mitigation: rename the row label in Excel to "Quarterly Interest Rate" if useful (cosmetic).

### Option B — Treat the row as annual everywhere; divide-by-4 in every formula

Keep the row as annual; make every formula explicit about scaling.

Sites that would need updating:
- [finmo_model.py:461](python/financial_model_engine/finmo_model.py#L461) — debt interest: `* interest_rate / 4`
- [finmo_model.py:477](python/financial_model_engine/finmo_model.py#L477) — lease interest: `* interest_rate / 4`
- [post_intake_debt_schedule/schedule.py:282](python/client_intake_and_finmo/post_intake_debt_schedule/schedule.py#L282) — schedule plan interest: `* interest_rate / 4`
- [schedule_sheets.py:454](client_statements_output_excel/schedule_sheets.py#L454) — workbook debt interest: `=...*D12/4`
- [schedule_sheets.py:505](client_statements_output_excel/schedule_sheets.py#L505) — workbook lease interest: `=...*rate/4`
- [schedule_sanity.py:377](python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py#L377) — remove the `* 4.0` annualization
- FORMULA_REGISTRY descriptions to clarify annual semantic

Pros:
- Row displays annual (5%, 10.25%), matching user intuition
- Semantics explicit at each formula site

Cons:
- Six+ sites to update consistently
- Higher risk of missing one
- The "Interest Rate" row's semantic intent has always been per-period in this codebase (the realism check at line 376-377 documents this), so flipping the contract is a larger change

## I. Recommendation

**Option A.** Single-line fix at the bridge. Honors the existing per-period contract of the `Interest Rate` row. Every downstream consumer is automatically correct.

Test scope:
- Q1 ExpressLogix debt interest at SBA rate 10.25% annual on $500K avg LTD → expect ~$12,500 (was $49,969)
- Q1 ExpressLogix lease interest on $54K lease at SBA rate 10.25% annual → expect ~$1,385 (was $5,535)
- Sunny: no behavior change (no debt)
- NexGen: $300K LTD now charged ~$7,688/quarter instead of ~$30,750/quarter
- Acceptance gate: lease-bearing ExpressLogix should now pass 16/16 (the q11_ni_margin marginal failure was driven by ~$8K/quarter of inflated lease+debt interest; correct rates restore margin)

Regression risk:
- Any business that was passing the acceptance gate ON the inflated interest needs to be verified post-fix (lower interest = higher NI = should make most gates easier, not harder)

## J. Out-of-scope notes

The realism check `_check_debt_rate_realism` ([schedule_sanity.py:351](python/client_intake_and_finmo/post_intake_realism/schedule_sanity.py#L351)) is the gate that should have caught this. It is silently no-op'ing for the test businesses (NAICS coverage missing per its `status="skipped"` path). Wiring more NAICS coverage or making the silent skip louder is a separate iter — but worth noting that the realism layer was structurally correct (multiplies by 4 to annualize, asserts against SBA band), it just never got the chance to fire.
