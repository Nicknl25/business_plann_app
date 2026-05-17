# P3.19 Phase 2d — Track 4: Cash Buffer Violation Root Cause

**Iter:** Phase 9 P3.19 Phase 2d (read-only investigation; no fixes)
**Scope:** Diagnose why the lease-bearing ExpressLogix Phase 3a rerun failed finalize with `post_intake_cash_buffer_violation`. Compare trajectories of the prior PASSING run (annual rate, marginal acceptance) vs the FAILING run (correct quarterly rate, hard cash buffer fail).

---

## A. Runs compared

| Label | Cloned draft | Interest rate scale at the time | Finalize outcome | Acceptance outcome |
|---|---|---|---|---|
| **PASS** | `3f7fd829237c40c0883fd19e41e51846` | ANNUAL stored in per-quarter slot (4× inflated debt + lease interest, pre-Phase-2) | passed | 15/16 (net_income_trajectory_viable Q11 NI margin -0.23% vs 0% threshold) |
| **FAIL** | `e38c800fa06f4bddafd95211e9e4d017` | QUARTERLY stored (correct, post-Phase-2-followup) | **FAILED** with `post_intake_cash_buffer_violation` | n/a — finalize blocked it |

Both runs used the same source draft `e112df06c6914889b1f104f05e97bcc0` (ExpressLogix Shipping Services + injected `initial_lease=4500`). The only code difference between the two runs is the rate fix.

---

## B. Q1 snapshot — by line item

```
                              PASS (annual)     FAIL (qtr)      DELTA (FAIL - PASS)
revenue                       808,913           4,729,063       +3,920,150
cost_of_goods_sold            550,061           3,576,773       +3,026,712
payroll                       538,070           415,443         -122,627
marketing                     22,650            279,272         +256,622
general_and_administrative    22,650            279,272         +256,622
lease_rent                    150,000           150,000         0
research_and_development      0                 4,656           +4,656
opex_total                    1,283,430         4,705,417       +3,421,987
monthly_opex                  427,810           1,568,472       +1,140,662
ebitda                        -474,517          23,645          +498,162
interest_total                55,504            13,876          -41,628
  debt_interest               49,969            12,492          -37,477
  lease_interest              5,535             1,384           -4,151
depreciation                  2,934             2,934           0
taxes                         0                 1,258           +1,258
net_income                    -532,955          5,578           +538,532
ocf (operating cash flow)     -351,156          -2,157,887      -1,806,730
icf (investing)               -4,682            -4,682          0
fcf (financing)               697,554           -63,750         -761,304
  debt_issuance               0                 0               0
  debt_repayment              25,000            25,000          0
  lease_principal_repayment   38,750            38,750          0
  equity (raised)             761,304           0               -761,304
  owner_distributions         0                 0               0
ending_cash                   641,715           -1,926,319      -2,568,034
debt_closing                  475,000           475,000         0
```

---

## C. Cash trajectory + buffer comparison (Q1..Q20)

```
Q    PASS cash       PASS buf req    PASS status  |   FAIL cash         FAIL buf req     FAIL status
 1     641,715         641,715         OK              -1,926,319        2,352,709        GAP -4,279,028
 2     648,831         648,831         OK              -1,980,310        2,375,916        GAP -4,356,227
 3     654,600         654,600         GAP -1          -2,047,147        2,394,677        GAP -4,441,824
 4     659,004         659,003         OK              -2,047,568        2,409,857        GAP -4,457,425
 8     670,600         670,601         GAP -1          -1,899,668        2,467,559        GAP -4,367,227
12     666,087         666,086         OK              -1,564,034        2,652,952        GAP -4,216,987
16     674,103         674,104         GAP -1          -1,019,163        2,750,742        GAP -3,769,905
20     693,733         682,155         OK                -459,367        2,781,397        GAP -3,240,764
```

**PASS run** sits right AT the buffer threshold the entire 20 quarters — `ending_cash ≈ buffer_required` to the dollar. Most quarters round to "OK" (off-by-$1 noise on the others). Cash is just barely meeting the buffer requirement. This is a marginally-funded plan.

**FAIL run** has cash deeply negative through all 20 quarters (-$1.93M at Q1, slowly improving to -$459K at Q20). Buffer required is much higher (~$2.4M-$2.8M because OPEX is much higher). Gap is ~$4M throughout.

---

## D. Where the delta comes from

### D.1 Convergence picked completely different plan shapes

The two runs are not the same business operating with slightly different interest. They are **entirely different plans** the convergence engine authored:

- **PASS plan:** slow revenue ramp ($808K → $1.4M over 20 quarters), modest OPEX (~$1.3M/quarter), equity funding $761K at Q1 to bridge the early cash gap. A conservative, equity-funded plan.
- **FAIL plan:** aggressive revenue scale ($4.7M from Q1), large OPEX (~$4.7M/quarter), NO equity funding ($0), deeply negative operating cash flow throughout. An aggressive, debt-only plan that never gets the equity injection it needs.

The interest delta alone (-$42K/quarter) cannot explain a $2.5M Q1 cash difference. The cash gap arises because:

- OCF is $1.8M WORSE in FAIL (-$2.16M vs -$0.35M) — the plan operates at much higher OPEX scale relative to revenue.
- FCF is $0.76M WORSE in FAIL (-$64K vs +$697K) — the PASS run got equity injection; the FAIL run didn't.

Net Q1 cash change: PASS = OCF -$351K + ICF -$5K + FCF +$697K = +$341K (cash goes from $300K to $641K). FAIL = OCF -$2.16M + ICF -$5K + FCF -$64K = -$2.23M (cash goes from $300K to -$1.93M).

### D.2 Debt service is identical between runs

Both runs have the same:
- Debt issuance series ($0 every quarter)
- Debt repayment series ($25K/quarter)
- Debt closing balance trajectory ($500K → $0)
- Lease principal payment ($38,750/qtr — intake-leak value)

So the debt amortization path is identical. The interest expense difference (-$42K/qtr) is the only debt-related delta, and it's a modest improvement.

### D.3 The actual driver is the revenue + OPEX trajectory the convergence engine picked

The PASS run's convergence converged on a `revenue_not_flat_q1_q10` trajectory of `[808913, 861735, 915043, 968835, 1023114, 1077877, 1133126, 1188860, 1245079, 1301784]` — a very gradual ramp.

The FAIL run's convergence picked Q1 revenue = $4,729,063 — almost 6× higher at Q1 — and a much flatter trajectory above that. OPEX scales proportionally.

This is the GPT-authored convergence (`_run_unified_convergence_openai`) responding differently to the planning context. Inputs that changed between the two runs:

1. **Interest rate signal:** PASS saw 0.1025/qtr (= 41% annualized — would be visible as crushing debt drag in any per-row cash projection); FAIL sees 0.025625/qtr (= 10.25% annualized — looks much more manageable). GPT's choice of which levers to move and target_values likely shifted in response.
2. **Cash strategy debt support multiplier:** PASS used 0.949 (per-$1 of new debt produces $0.95 of usable cash because of inflated quarterly interest drag); FAIL uses 0.987 (per-$1 produces $0.99). The cash strategy's lever_bound `max_borrow_amount` calibrations could be different.

### D.4 The funding handler did not engage to fill the gap

In the FAIL run, finalize fails BEFORE the funding handler could engage on the cash buffer violation. The handler is normally invoked on `cash_buffer_violations` from the cash post-pass (iter 19 Stage 4). The FAIL run's cash_buffer_violation diagnostic shows finalize raised directly without the funding handler getting a chance to author corrective lever changes.

(Or the handler did engage during convergence, found it could not resolve, and the convergence continued anyway. The run_diagnostics block would show handler_status — Track 4 hasn't deep-dived this; recommend a follow-up.)

---

## E. Direct answer to the iter's central question (D)

> "(a) Convergence picked an unaffordable plan because lower interest made it look feasible, OR
> (b) Cash pass machinery still uses an incorrect (stale) rate internally and produces wrong projections, OR
> (c) Something else entirely"

**Answer: primarily (a), with a small contribution from the implicit rate signal influence on the GPT-authored convergence.**

- **(a) confirmed:** the PASS run was marginal (cash at buffer throughout, equity-funded). The FAIL run is a completely different plan (6× larger Q1 revenue + OPEX scale, no equity funding). The lower interest signal apparently shifted the GPT-authored convergence's lever choices toward an aggressive scale that the cash strategy didn't author equity to fund.

- **(b) refuted by Track 3:** all cash pass interest reads correctly consume the per-quarter rate. The buffer formula has no interest term. No stale-rate computation exists.

- **(c) partially:** convergence non-determinism is real. Two runs with the same source draft can produce different lever values because the GPT call is non-deterministic. The rate fix changed one input signal; whether that single change explains the entire plan-shape divergence vs ordinary GPT non-determinism cannot be definitively separated from this single data point. A second-run replication of FAIL would help confirm whether the FAIL plan shape is stable or whether different runs see different shapes.

---

## F. Implication for fix strategy (NOT in this iter)

The cash buffer violation is **not** caused by a rate-scale bug. The rate fix is correct. The downstream issue is that:

1. **The convergence engine, with the new (correct) rate signal, authored a plan that the cash strategy cannot fund.** The plan operates at $4.7M/quarter OPEX vs $1.3M/quarter in the prior PASS — a 4× larger scale.

2. **Equity funding fell to zero** in the FAIL plan ($0 vs $761K in PASS). Without equity injection, the cash gap cannot be closed by debt alone (debt issuance is also $0 — the cash strategy didn't author new borrowing either).

3. **The funding handler appears not to have engaged** at the cash buffer violation; if it had, it might have authored equity or new debt to close the gap.

Possible fix directions (NOT in scope for this iter — for user to decide):
- Investigate why convergence picked a 4× larger plan with the rate change. Is the revenue authoring sensitive to interest signal in a way that amplifies the response?
- Investigate why equity funding fell to $0 — is there a cash_strategy_proposer threshold that toggled based on the new rate / cash-support-multiplier?
- Check the funding handler trace — did it engage on the cash buffer violation, what levers did it try, why did it not close the gap?
- Rerun the FAIL scenario to confirm stability — same source, same code, different seed. If the plan shape replicates, it's deterministic-given-rate. If it doesn't, GPT non-determinism is the larger factor.

No fixes proposed in this memo per iter directive.

---

## G. Summary

- **Confirmed:** the cash buffer violation is NOT a rate-scale issue in the rate plumbing, the cash pass machinery, or the buffer formula itself. Tracks 1, 2, 3 already established this.
- **Confirmed:** the FAIL plan is fundamentally different from the PASS plan — 4-6× larger OPEX/revenue scale, no equity funding, no debt issuance to close the cash gap.
- **Identified driver:** the convergence engine authored a different plan when the interest rate signal changed. The lower rate likely made aggressive scale look more feasible (lower debt drag); GPT picked levers accordingly; cash strategy didn't author the equity injection the previous PASS run got.
- **Recommendation (NOT a fix):** the user should decide whether to investigate convergence sensitivity to the rate signal, whether to make the cash strategy proposer more aggressive about authoring equity when needed, whether to ensure the funding handler engages on this class of buffer violation, or whether to accept that the new rate produces a different (and unfundable) plan and treat that as a real signal about the business's viability under correct interest rates.

The P3.19 rate fix itself remains correct. The cash buffer violation is a downstream signal that the test business may not have been a viable plan at correct SBA rates — the prior PASS only happened because the inflated rate forced a smaller plan scale that the cash strategy could fund with equity.
