# P3.19 Phase 2d — Track 3: Cash Pass Machinery Audit

**Iter:** Phase 9 P3.19 Phase 2d (read-only investigation; no fixes)
**Scope:** Every interest-rate-related read in the cash pass, plus the cash buffer formula itself. The hypothesis was that the cash pass might silently still be reading the rate at an unexpected scale; verify or refute.

---

## A. Files audited

- `python/client_intake_and_finmo/post_intake_cash/`
  - `__init__.py`
  - `runner.py` (main cash strategy runner + funding handler invocation)
  - `common.py` (shared buffer / debt-support helpers)
  - `planning_envelope.py` (per-quarter planning context)
  - `validation_envelope.py` (cash-pass validators)
  - `cash_strategy_proposer.py` (Python-deterministic proposer)
- `python/client_intake_and_finmo/post_intake_funding_handler/mini_finmo.py` — `mini_finmo` for the funding handler
- `python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py` — `mini_finmo` for the restoration handler
- Callees in `post_intake_debt_schedule/schedule.py` for the per-quarter rate reads that cash pass invokes via wrappers

---

## B. Every interest-rate-related read in cash pass

### B1. Cash pass runner

| File | Line | Reads from | Scale expected | Arithmetic | Intent | Status |
|---|---|---|---|---|---|---|
| post_intake_cash/runner.py | 822 (`_cash_strategy_sba_forecast_interest_rate_policy`) | Wraps `_debt_schedule_sba_interest_policy` (the policy reader at debt_schedule/schedule.py:150) | ANNUAL→QUARTERLY (returns both) | none — pass-through wrapper | Provide policy structure to cash pass | ✓ |
| post_intake_cash/runner.py | 884-904 (`_cash_strategy_debt_cash_support_multiplier`) | `lever_map["expenses::Interest Rate"]` series (per-quarter row) | QUARTERLY | `1.0 - normalized_rate/2.0` | **Partial-quarter drag** — new borrowing raised at mid-quarter accrues ~0.5 quarter of interest before quarter-end, so cash-support multiplier discounts each $1 of debt by half-a-quarter's rate. NOT unit conversion. | ✓ |
| post_intake_cash/runner.py | 1186-1203 (`_cash_strategy_funding_source_policy`) | Reads `interest_rate` from debt_schedule_snapshot rows | QUARTERLY (snapshot mirrors per-quarter row) | none; compares against threshold `0.03` (= 12% annual) for `debt_drag_material` flag | Assess whether debt drag is material enough to warrant guidance | ✓ |
| post_intake_cash/runner.py | 4076-4138 (`cash_debt_interest_rate_forecast_mismatch` validator) | `debt_rate_policy.quarterly_rate_decimal` (with fallback `annual_rate_decimal / 4.0`) AND `_solved_lever_value_map(...).get("expenses::Interest Rate")` series | QUARTERLY on both sides | `/4.0` only in fallback | Enforce: every Q1-Q20 row in Interest Rate equals the SBA-backed per-quarter rate | ✓ |

### B2. Cash pass common helpers

| File | Line | Reads from | Scale expected | Arithmetic | Intent | Status |
|---|---|---|---|---|---|---|
| post_intake_cash/common.py | 152-166 (`operating_expense_from_row`) | FINMO row fields: cost_of_goods_sold, payroll, marketing, r_and_d, lease_rent, g_and_a | n/a (these are dollar amounts, not rates) | sum | Compute quarterly OPEX (excludes interest, depreciation, taxes) | **n/a — interest is NOT in the OPEX sum** |
| post_intake_cash/common.py | 216-252 (`buffer_components`) | OPEX (via above) | n/a | `monthly_opex = opex_quarter / months_per_quarter (=3)`; `cash_buffer_required = monthly_opex * floor_months` | Compute floor/ceiling cash buffer thresholds | **No interest term in the buffer formula** |
| post_intake_cash/common.py | 255-273 (`debt_cash_support_multiplier`) | `lever_map["expenses::Interest Rate"]` series | QUARTERLY | `1.0 - normalized_rate/2.0` | Same as runner.py:884-904 (this is the canonical source; runner.py delegates here) | ✓ |
| post_intake_cash/common.py | 263 (lever_map read inside the multiplier) | Same as above | QUARTERLY | n/a | n/a | ✓ |

### B3. Planning / validation envelopes

| File | Line | Reads from | Scale | Arithmetic | Status |
|---|---|---|---|---|---|
| post_intake_cash/planning_envelope.py | (calls common.debt_cash_support_multiplier) | delegated | QUARTERLY | delegated | ✓ |
| post_intake_cash/validation_envelope.py | (calls common.debt_cash_support_multiplier) | delegated | QUARTERLY | delegated | ✓ |
| post_intake_cash/validation_envelope.py | various | Reads cash buffer thresholds (no interest reads beyond the support multiplier) | n/a for rate | n/a | ✓ |

### B4. Cash strategy proposer

`post_intake_cash/cash_strategy_proposer.py` does NOT read the interest rate directly. It consumes pre-computed `lever_bounds[*].supporting_metrics.cash_support_multiplier` values that the runner computed via `debt_cash_support_multiplier`. No independent rate arithmetic in the proposer. ✓

### B5. Debt schedule plan / snapshot (consumed by cash pass)

| File | Line | Reads from | Scale | Arithmetic | Status |
|---|---|---|---|---|---|
| post_intake_debt_schedule/schedule.py | 150-182 (`sba_forecast_interest_rate_policy`) | `derived_driver_policies.debt_interest_rate_policy.annual_rate_decimal` | ANNUAL | `/4.0` to expose `quarterly_rate_decimal` | ✓ |
| post_intake_debt_schedule/schedule.py | 240 (`forecast_interest_rate = ...quarterly_rate_decimal`) | policy.quarterly_rate_decimal | QUARTERLY | none | ✓ |
| post_intake_debt_schedule/schedule.py | 282 (`interest_expense = ((opening+closing)/2) * interest_rate`) | local `interest_rate = forecast_interest_rate` (quarterly) | QUARTERLY | none — applies per quarter | ✓ |
| post_intake_debt_schedule/schedule.py | 367-368 (interest_rate_series from lever_map) | `lever_map["expenses::Interest Rate"]` | QUARTERLY | none | ✓ |
| post_intake_debt_schedule/schedule.py | 380-382 (snapshot's per-row rate) | `row.get("debt_interest_rate")` with fallback to interest_rate_series | QUARTERLY | none | ✓ |

### B6. mini_finmo (funding handler + restoration handler)

I inspected both `mini_finmo.py` files:

- `python/client_intake_and_finmo/post_intake_funding_handler/mini_finmo.py`
- `python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py`

Neither file performs its own interest-rate computation. Both are CASH TRAJECTORY MIRRORS that read PRE-COMPUTED interest from FINMO rows or schedule snapshots and project cash forward by applying the deltas from handler-authored lever changes. They do not re-derive interest from a rate.

✓ No rate reads in either mini_finmo.

---

## C. The cash buffer formula — does interest enter it?

**No.** The cash buffer requirement is computed at `post_intake_cash/common.py:216-252` as:

```python
opex_quarter = sum of (cost_of_goods_sold, payroll, marketing, r_and_d, lease_rent, g_and_a)
monthly_opex = opex_quarter / months_per_quarter   # months_per_quarter = 3
cash_buffer_required = monthly_opex * floor_months  # floor_months from SQL cash policy
cash_ceiling = monthly_opex * ceiling_months
```

`operating_expense_from_row` ([common.py:152-166](python/client_intake_and_finmo/post_intake_cash/common.py#L152)) explicitly EXCLUDES interest, depreciation, and taxes. The buffer thresholds are derived purely from operating-expense run-rate.

**Implication:** the rate fix in Phase 2 does NOT change the cash buffer threshold itself. The threshold depends only on OPEX, not on debt service. Lower interest expense (post-fix) means more cash retained, which should make passing the buffer EASIER, not harder.

If a run fails the buffer post-fix that previously passed, the cause is NOT the buffer formula consuming the wrong rate scale. It must be either:
- The cash trajectory (which depends on net cash flow per quarter, which includes interest as one of many terms)
- Or the convergence engine picking a different OPEX trajectory because the rate signal influenced its choices (debt drag materiality, cash support multiplier, etc.)

---

## D. Per the directive's specific questions

### D.A — Every interest-related read in cash pass

Listed in tables B1-B6 above. Total reads:
- 4 in runner.py (wrapper, support multiplier, funding source policy, forecast mismatch validator)
- 2 in common.py (support multiplier with read inside it; OPEX function which has no rate)
- 2 in envelopes (delegated to common.debt_cash_support_multiplier)
- 0 in proposer
- 0 in mini_finmo (either copy)
- 5 in debt_schedule/schedule.py (policy reader, plan builder, snapshot builder, lever map reader)

### D.B — mini_finmo interest projection

mini_finmo files do NOT compute their own interest projections. They are cash-delta mirrors. They project cash forward using:
- Pre-computed interest from FINMO (or snapshot)
- Lever changes the handler proposes
- Working capital deltas

So scale is whatever the pre-computed FINMO interest already is (QUARTERLY post-Phase 2). ✓

### D.C — Cash strategy proposer's interest assumption

`cash_strategy_proposer.py` does not read the rate. It reads `lever_bounds[*].supporting_metrics.cash_support_multiplier` and `required_funding_gap` from the planning_envelope, which were computed using `debt_cash_support_multiplier` (which correctly consumes per-quarter rate).

So the proposer's "interest assumption" is implicit in the cash_support_multiplier value (e.g. `1 - 0.025625/2 = 0.987` post-fix), which is the fraction of $1 of new borrowing that lands as Q-end cash after partial-quarter interest drag. The proposer uses this multiplier when sizing borrow amounts.

### D.D — Cash buffer formula

Already covered in section C. No interest term in the buffer formula.

### D.E — Funding handler internal interest computation

The funding handler's `mini_finmo` is a cash-delta mirror (no interest re-derivation). The funding handler's tool-calling session proposes lever changes (debt issuance, debt repayment, equity, distributions) and uses `mini_finmo` to preview the cash effect. The cash effect of new debt issuance is computed via the `debt_cash_support_multiplier` discussed above — quarterly rate, partial-quarter drag.

### D.F — Cash flow projection for solvency

This is `mini_finmo` again. Reads pre-computed FINMO interest. ✓

---

## E. Classification summary

| Site | Status |
|---|---|
| sba_forecast_interest_rate_policy (debt_schedule) | ✓ Consistent with quarterly contract |
| build_debt_schedule_plan exact_updates | ✓ Consistent with quarterly contract |
| build_debt_schedule_snapshot | ✓ Consistent with quarterly contract |
| _cash_strategy_debt_cash_support_multiplier | ✓ Quarterly input; /2 is intentional partial-quarter drag |
| common.debt_cash_support_multiplier | ✓ Same as above (canonical) |
| _cash_strategy_funding_source_policy | ✓ Threshold of 0.03 (3% quarterly = 12% annual) is consistent with quarterly input |
| cash_debt_interest_rate_forecast_mismatch validator | ✓ Reads quarterly_rate_decimal; fallback /4.0 from annual |
| Planning envelope / validation envelope | ✓ Delegated to common |
| cash_strategy_proposer | ✓ N/A (no direct rate read) |
| mini_finmo (funding) | ✓ N/A (no rate read) |
| mini_finmo (exhaustion) | ✓ N/A (no rate read) |
| buffer_components (cash buffer formula) | ✓ N/A (no rate term in buffer formula) |

**Zero scale mismatches found in cash pass machinery.**

---

## F. Implication for the cash_buffer_violation in the P3.19 Phase 3a rerun

The Phase 3a rerun of lease-bearing ExpressLogix failed finalize with `cash_buffer_violation` after the rate fix landed. This Track 3 audit confirms:

- The cash buffer formula has NO interest term — the threshold depends only on OPEX.
- All cash pass interest reads correctly consume the new per-quarter rate.
- Lower interest (Phase 2 fix) should make the buffer EASIER to maintain, not harder.

**Therefore the cash_buffer_violation root cause is NOT a rate-scale issue in cash pass.** Track 4's job is to look at the actual run data — the OPEX trajectory and cash trajectory — to identify why the convergence picked an unfundable plan even with correct (lower) interest. The hypothesis the iter raised in Phase 3a (a plan that was passing because the inflated interest was needed) remains the most likely explanation, and Track 4 will confirm or refute by comparing trajectory data across runs.

**Note on Track 3 ambiguity worth flagging:** the `debt_cash_support_multiplier` formula `1.0 - normalized_rate/2.0` is intended as partial-quarter drag. With rate = 0.025625, multiplier = `0.987`. Pre-fix with rate = 0.1025, multiplier was `0.949`. So pre-fix the cash strategy treated each $1 of new debt as $0.95 of usable cash; post-fix it treats it as $0.99 of usable cash. This means the cash strategy is now MORE OPTIMISTIC about how much cash a given debt issuance produces. If the convergence then chose a borrowing schedule that requires the cash to land at the higher multiplier and the actual FINMO cash flow doesn't quite produce that much, the buffer could miss. This is a SUBTLE consequence of the rate fix, but it's not a scale mismatch — the formula is correctly consuming per-quarter rate. It's a calibration question whether `/2` is still the right partial-quarter drag at the new (smaller) rate. Out of scope for this iter.

No fixes proposed per iter directive.
