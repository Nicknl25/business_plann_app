# R-DEBT-01 — Making the Debt Schedule client-operable

**Tier:** research only. No builder, formula or re-bless touched.

**Date:** 2026-08-21 · **Author:** VS · **Branch:** intake-stable

Claim tags per 04800b2: **VERIFIED (measured)** on a built workbook or a real
draft / **VERIFIED (source read)** / **UNVERIFIED** / **TO-BE-TESTED**.

**Measurement basis.** Workbooks built in memory through the production builder;
perturbation tests driven through Excel COM on **Falls City Mechanical**
(draft `76c6e0b9`) rather than Harrow, *because Harrow has no capital lease and
its zeroes hide the entire lease block*. Class coverage from 400 real drafts.
Instruments: `scratchpad/{anchor_sweep,debt_classes,debt_reach}.py`.

---

## Q1 — What a client can change, and whether it reaches FINMO

**VERIFIED (measured).** Each candidate was perturbed at Q4 in a real workbook
and FINMO recalculated. **All five reach FINMO. Two of them do not reach it in
the quarter you edit.**

| Edit (applied at Q4) | Q4 | Q8 | Q20 | Verdict |
|---|:--:|:--:|:--:|---|
| Debt Issuance +50,000 | ✓ | ✓ | ✓ | reaches, same quarter |
| Requested Debt Repayment +10,000 | ✓ | ✓ | ✓ | reaches, same quarter |
| Interest Rate 2.375% → 5% | ✓ | — | — | reaches, same quarter only |
| **Lease Net Additions +40,000** | — | ✓ | ✓ | **reaches, one quarter LATE** |
| **Requested Lease Principal +5,000** | — | ✓ | ✓ | **reaches, one quarter LATE** |
| Lease Opening Balance (stub col C) | ✓ | ✓ | ✓ | reaches immediately |

**A correction I have to record, because it nearly became a finding.** My first
pass measured only the quarter it perturbed and reported the two lease levers as
**inert**. That was wrong. A lease repayment changes the *closing* balance, which
becomes the *next* quarter's opening — so the effect lands one quarter later by
construction. Measuring the same quarter you perturb cannot see a balance-driven
chain at all. The corrected instrument reads Q4, Q8 and Q20.

**The interest-rate row reaches only its own quarter** (Q4 moves, Q8 and Q20 do
not), which is correct: the rate multiplies that quarter's average balance and
carries nothing forward.

---

## Q2 — The layout

Today the editable rows are **8, 9, 12, 19, 21** — scattered among calculated
rows down a 26-row sheet. Proposed:

**Block 1 — What you can change (debt)**
`Debt Issuance` · `Requested Debt Repayment` · `Interest Rate per quarter`

**Block 2 — What that produces (debt)**
`Opening Debt` · `Actual Repayment` · `Interest Expense` · `Closing Debt` ·
`Total Debt Service`

**Block 3 — What you can change (lease)**
`Lease Net Additions` · `Requested Lease Principal Repayments` ·
`Lease Opening Balance` (stub only — see Q5) · `Lease Life in quarters` (new,
see Q5)

**Block 4 — What that produces (lease)**
`Lease Principal Repayments` · `Lease Interest Expense` · `Lease Closing
Balance` · `Right-of-Use Asset Opening` · `Lease Asset Depreciation` ·
`Right-of-Use Asset Closing`

Editable rows amber via `write_values_row(input_style=True)`; computed rows grey
via `set_formula_style`. Stub column hidden with the `hide_stub_column` helper
added in `b7586ca`.

---

## Q3 — Rows that go inert after payoff

**VERIFIED:** on Harrow, debt closes to zero in Q7; from Q8 to Q20 Requested
Repayment still displays 1,313 and Interest Rate still displays 2.375%, while
Actual Repayment and Interest Expense are both 0. Thirteen quarters of amber
that reach nothing.

**Recommendation: leave the numbers, mark the quarters.** Add a `Why a quarter
shows nothing` note row under the debt block reading *"Debt repaid in full —
this quarter's repayment and rate no longer apply"*, populated per quarter from
whether closing debt is zero.

Rejected: **stopping the row** (a blank grid reads as a build failure, and it
would remove the cells a client needs if they *add* debt later — which is the
whole point of the issuance row); **hiding those quarters** (that is the pattern
we just spent a directive removing from the marketing sheet).

This applies the principle directly: **show the number and mark it, never hide
it.** The marketing threshold work established that suppressing a real figure —
Fernhill's $24,590 CAC — teaches the client nothing, and this is the same trade.

---

## Q4 — The MIN() guards

**VERIFIED (source read):**
`Actual Repayment = MIN(Requested, Opening + Issuance)` and
`Lease Principal = MIN(Requested, Opening + Additions)`.

**The guard is right and should stay.** It makes overpayment unrepresentable
rather than detected after the fact, which is the standing preference.

**But the silence is wrong.** A client who types a larger repayment sees the
number they typed sitting in an amber cell and *nothing else move* — and there
is no way to tell that from a broken sheet. **Recommendation: the note row from
Q3 does double duty**, reading *"Repayment capped at the balance available"* in
any quarter where `Requested > Actual`. One row, both conditions, no new
machinery.

**UNVERIFIED:** whether a client would rather see the excess rejected loudly. I
would not build a warning beyond the note — post-delivery edits are not a
correctness concern per the standing ruling.

---

## Q5 — The lease block, and the workbook-wide sweep

### The anchor

**VERIFIED (measured), and it is worse than a magic number.**

```
D25 = MIN((C18/20), D24)
G25 = MIN((C18/20), G24)      <- C18 in EVERY quarter
```

`C18` is the **stub** Lease Opening Balance. `20` is a hardcoded life.

Measured on Falls City (opening balance 81,600):

| | |
|---|---|
| depreciation, every quarter | **4,080.00** = 81,600 / 20 |
| after adding 40,000 of new lease at Q4 | **4,080.00** — unchanged at Q4, Q5, Q6 **and Q20** |

**A lease addition changes how LONG depreciation runs, never the RATE**, because
the rate is anchored to a column that never moves. A client who adds a lease
sees their asset and their interest respond and their depreciation stay
frozen — the exact shape of the `$C$7/$C$8` defect from the marketing sheet.

**This is not theoretical: 17 of 400 drafts carry a capital lease** (VERIFIED).
Harrow is simply not one of them.

**Recommendation:** depreciation base becomes the **current** quarter's opening
ROU asset, and `20` becomes an editable `Lease Life in quarters` row so the
label and the number agree. **TO-BE-TESTED:** whether changing the base from
stub to current alters any delivered number for the 17 lease businesses — it
will for any of them with a mid-plan addition, and Q8 shows **zero** drafts take
on debt or lease mid-plan today, so the delivered set may be unaffected. That
must be measured per draft before building, not assumed.

**Also found (VERIFIED, source read):** lease interest is `D18*D12` — it uses
the **debt** interest rate. A capital lease normally carries its own implicit
rate. Flagged, not recommended either way; it is a modelling decision.

### The workbook-wide sweep

**VERIFIED (measured), both fixtures.** I parsed every formula on every sheet
and flagged any reference whose column **never advances** across the period
grid — the class R32 cannot see, because it compares formula strings and
`=MIN((C18/20),D24)` vs `=MIN((C18/20),E24)` are legitimately different strings.

Six rows flagged; **five are false positives and one is the real defect:**

| Sheet | Row | Verdict |
|---|---|---|
| Debt Schedule | r25 Lease Asset Depreciation → `C18` | **THE DEFECT** |
| Payroll Schedule | r15/16/17 → `$G$27`,`$H$27`,`$M$27` | Legitimate — `SUMIFS` over a fixed detail block whose **criteria advances** 0,1,2,3,4. Verified by reading the formulas across columns. |
| Calc | r59/r103 → `FINMO!D23` | Legitimate — `MIN('FINMO'!D23:W23)`, a whole-horizon scalar repeated by design. |

**One anchor-to-stub defect exists in the entire workbook.** That is a better
result than I expected and worth stating plainly, but the sweep should become a
permanent leg — see Q7.

---

## Q6 — Interest rate labelling

**VERIFIED:** the value is **quarterly** (2.375% ≈ 9.5% annual) and the row is
labelled only `Interest Rate`.

**Recommendation: keep it quarterly and rename the row `Interest Rate per
quarter`.** Quarterly, because every other number on the sheet is quarterly and
the formula multiplies it by a quarterly balance with no conversion; converting
to annual would introduce a `/4` inside a formula, which is precisely the hidden
conversion that caused the four-fold customer error on the marketing sheet.

**Verify forward:** Valuation reads this row for cost of debt (**VERIFIED
source read**) and would need to annualise explicitly if it does not already.
**TO-BE-TESTED** before renaming — a rename that leaves Valuation reading a
quarterly rate as if annual would understate WACC by ~4x.

---

## Q7 — What breaks under a reorder

**VERIFIED (source read):** every Debt Schedule row is registered via
`ctx.add_schedule_row(DEBT_SHEET, label, row)` and every consumer resolves
through `ctx.schedule_row(...)` — Model Inputs' thirteen bridged rows, FINMO,
CapEx, Valuation and Checks alike. **A reorder is therefore safe by
construction**, provided rows keep their **label**, which is the registry key.

**The one thing that would break it:** renaming `Interest Rate` (Q6) changes the
ctx key. Every consumer lookup must move in the same commit, or
`ctx.schedule_row` returns 0 and the reference silently points at row 0.

**Recommendation, and it is the durable half of this directive:** promote the
anchor sweep to a gate leg (**R50 `no-stub-anchored-references`**). It is cheap,
it runs on the built workbook, and it catches a class both goldens are blind to
by construction. A test that imports the production builder, not a restatement
of it.

---

## Q8 — Class coverage

**VERIFIED (measured)** across 74 distinct businesses in the last 400 drafts:

| Shape | Count | Does the proposed layout hold? |
|---|---:|---|
| No debt at all | **15** | Yes — all rows zero, the Q3 note row reads "no debt in this plan" |
| Never repays | **13** | Yes — repayment row stays editable and reaches FINMO |
| Has a capital lease | **17** | Yes, **and this is the group the Q5 fix is for** |
| Takes on debt mid-plan | **0** | Layout holds, but **untested against real data** |

**The zero matters.** No draft in 400 issues debt or adds a lease after the
stub, which is why the stub-anchored depreciation has never produced a visibly
wrong number. **It also means the issuance and additions rows have never been
exercised in production** — they are editable rows whose behaviour is
theoretical. That is an argument *for* the Q5 fix, not against it: the moment a
client uses the row the sheet was built to offer, it misbehaves.

---

## Gate impact

| Surface | Expected movement |
|---|---|
| **R32** | **Moves substantially.** Reordering rewrites every Debt Schedule formula's row references, and Model Inputs' thirteen bridge rows, FINMO r10, CapEx, Valuation and a dozen Checks rows follow. |
| **R49** | **Moves.** New section headers, the Q3/Q4 note row, `Interest Rate per quarter`, `Lease Life in quarters`, and every label below a reorder re-keys by address. |
| **R31** | **Must not move.** No engine code is involved. |
| **Recalculated values** | **Must be identical**, with one declared exception: the Q5 depreciation-base fix legitimately changes depreciation for any business with a mid-plan lease addition. Q8 says that is **zero** drafts today, so the delivered set should be unchanged — measure per draft rather than assume. |

**Protocol:** one re-bless per phase, leaf-by-leaf purity before re-baselining,
compared on a single-line and a multi-line fixture **plus a lease-carrying one**,
because Harrow cannot exercise this sheet's most defective block.

---

## Recommended phasing

1. **Rename + hide + note row.** `Interest Rate per quarter`, stub hidden, the
   Q3/Q4 note row. Values unchanged. Check Valuation's cost-of-debt read first.
2. **Reorder into the four blocks.** Values unchanged; R32/R49 move on row
   shifts alone.
3. **The lease fix.** Depreciation base to the current quarter, `20` becomes an
   editable life row. The only phase that can change a delivered number.
4. **R50, the anchor sweep as a leg.** Independently valuable, and it would have
   caught this defect the day it shipped.
