# R-FINMO-01 — the engine declares what each FINMO row IS

**Status:** directive, awaiting Nick. Nothing built.
**Written:** 2026-08-21, alongside R-DEBT-02 stage 2 (`a46e5f8`, `d3e8efe`).
**Origin:** amendment A4 to R-DEBT-02, item (b). Nick took option (c) — declare
the mode in the workbook now, and write the engine-side fix up as its own
directive rather than folding it into a workbook commit.

---

## The problem, stated once

A FINMO row's annual column is a **flow** (sum four quarters), a **balance at
the year's end** (take Q4), a **balance at the year's start** (take Q1's
opening), or a **rate** (average, or annualise). Nothing the engine emits says
which. The workbook has to work it out.

Until 2026-08-21 it worked it out by reading the row's **display label** —
`_ANNUALIZED_LABELS` by exact match, then substring hints on "opening",
"beginning", "ending ", "rate", "days", "% of". That made the label two things
at once: the row's identity in code, and its presentation to a client. A pure
reword changed the maths.

That is not hypothetical. It is where `Ending Cash` for Year 1 read **391,730**
against a true **127,623** — four quarter-end balances added together.

`35df1d2` replaced the inference with a declaration table **inside the workbook
package** (`finmo_sheet._STATEMENT_ANNUAL_MODE` / `_ROW_ANNUAL_MODE`), and
`d3e8efe` finished the job for the schedule sheets. The guessing is gone.

**But the declaration lives in the wrong repository of knowledge.** The
workbook is now asserting, in a lookup table it maintains by hand, a fact that
belongs to whatever produced the number.

## What already does this correctly

`model_input_json` **already carries `value_kind` per row.** The precedent is
in the codebase, it is the shape being asked for here, and it is why this is a
small directive rather than a design exercise. The ask is to make
`finmo_json` do what `model_input_json` already does.

## The ask

1. **Emit `value_kind` on every FINMO row** the engine writes into
   `finmo_json`, using the same vocabulary `model_input_json` uses. Where that
   vocabulary lacks a case FINMO needs (a year-START balance, an annualised
   quarterly rate), extend it deliberately and in one place — do not invent a
   second spelling.

2. **Make the workbook read it.** `finmo_sheet._declared_annual_mode()` becomes
   a translation from `value_kind` to annual mode, not a hand-maintained table
   of statements and labels.

3. **Keep the raise.** `_declared_annual_mode` already raises on an undeclared
   statement rather than guessing. After this change it should raise on a row
   arriving with **no `value_kind`**. The whole point is that silence is the
   failure mode; a default would restore it.

4. **The tail is a decision, not a default.** `_TAIL_PREFIXES` currently holds
   exactly one entry (`"Break-Even Units - "`), and
   `tests/test_annual_mode_declared.py::EXPECTED_TAIL_SIZE` fails if it grows,
   so growing it is done in the open. Either give break-even rows a real
   `value_kind` too, or keep the tail and keep the counter.

## The bar

- **Numbers do not move.** The current declarations are correct — `35df1d2`
  moved 0 of 1,730 formulas, and stage 2 moved 0 of 31,192 recalculated cells
  across three drafts. This is a change of *where the fact lives*, not of what
  the fact is. Same bar: every annual cell identical, both fixtures, plus the
  three-draft recalculated comparison.
- **R31 will move and R32 will not.** `value_kind` is new content in
  `finmo_json`, so the model payload changes; the formula grid must not. If
  R32 drifts, a declaration disagreed with its inference and that is the
  finding, not a re-bless.
- **Red-proof the raise.** A row with `value_kind` stripped must fail the
  build loudly. Assert it against a real payload, not a hand-built dict — a
  guard proven only against a fixture the production path never takes is the
  class of test that has already cost this project three rounds.

## Explicitly out of scope

- Any change to what a number IS. This moves a declaration; it does not
  re-decide an aggregation.
- The label text. Labels are free to be reworded — that freedom is the point.
- Model Inputs' remaining two inference sites (the balance-sheet and cash
  blocks, `annual_mode=None` at `model_inputs_sheet.py:252` and `:291`). They
  legitimately route on `_BALANCE_HINTS` and are not FINMO rows. If they should
  also be declared, that is a separate call.

## Related, and NOT part of this

**Lease additions never reach the right-of-use asset.** Found while measuring
`d3e8efe`. `Lease Closing Balance` = opening + additions − principal;
`Right-of-Use Asset Closing` = opening − depreciation, with **no additions
term**. A lease added mid-model raises the liability against no asset.

Exposure is nil today — **150 of 150 sampled drafts carry the additions row and
every one is zero**, so the engine emits no lease additions. It is latent, it
is an accounting question rather than a formula question, and it needs a ruling.
Recorded here so it is not lost; it is not part of R-FINMO-01.
