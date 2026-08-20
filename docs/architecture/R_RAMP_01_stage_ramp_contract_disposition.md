# R-RAMP-01 — Stage Ramp Contract: disposition

**Tier:** research only. No builder, schedule or formula changed. No re-bless.

**Date:** 2026-08-20 · **Author:** VS · **Branch:** intake-stable

Claim tags per 04800b2: **VERIFIED** (measured on a built workbook) /
**VERIFIED (source read)** / **UNVERIFIED** / **TO-BE-TESTED**.

**Measurement basis:** workbooks built in memory through the production builder
on both the frozen single-line fixture and the two-product fixture, plus the
persisted `planning_run_json` of the completed CW-038 Harrow Lane run.
Instrument: `scratchpad/ramp_scan.py`.

---

## Q1 — The negative, properly proven

**VERIFIED: nothing in the workbook consumes the block.** Rows located **by
label**, never by number, since the block sits at 18–28 for one product and
26–36 for two.

| Consumption path | Hits (single-line) | Hits (multi-line) |
|---|---:|---:|
| Formulas, all 15 sheets | **0** | **0** |
| Defined names | **0** | **0** |
| Data-validation formulas | **0** | **0** |
| Conditional-formatting rules | **0** | **0** |
| Chart series references (`val` / `cat` / `tx`) | **0** | **0** |
| Hyperlink locations | **0** | **0** |

**A correction worth recording, because my first scan said the opposite.** The
initial run reported **120 consumers** and a verdict of "CONSUMED". That was my
instrument, not the workbook: I spanned `min..max` of every row whose label
starts with "Stage Ramp", which swallowed the section header *and* the live
"Actual Revenue QoQ Growth" row sitting inside the block's row range. All 120
"hits" were that live row's own annual `=AVERAGE(D17:G17)` cells referring to
itself. Narrowing to the eleven **constant** rows — those carrying numeric
values and no formulas — and excluding self-references gives **0 on every path,
on both shapes**.

Ground truth confirmed: **11 inert rows × 21 columns = 231 cells**, all amber.

---

## Q2 — What the block is

**VERIFIED (source read + measured):** it is the constraint contract the solver
converged against. `client_statements_output_excel/data.py:157-194` reads it
from the canonical path
`planning_run_json → unified_convergence_context → business_world_contract →
stage_ramp_contract`, and fails loud if `quarter_ramp_grid` is absent.

**It is per-business and per-stage, not a global constant — VERIFIED** on
Harrow Lane's persisted contract:

```
business_stage              operating
stage_family                operational
contract_version            stage_ramp_contract_v2
decision_source             python_deterministic_floor
planning_mode               rebalance
planning_mode_reason        app_classified_misaligned_but_salvageable_case
utilization_high_watermark  0.85
quarter_ramp_grid           20 rows
  q1: rev_target 0.01, rev_max 0.04, max_util 0.65, cogs_target 0.14,
      cogs_max 0.14, marketing_max 0.02, rd_max 0.0, ga_max 0.06, …
```

**Is it meaningful as disclosure?** In principle it answers a question a lender
asks — *what did you constrain this plan to?* — with a per-quarter, per-stage
answer, and its `rationale` and `decision_source` say it was a deterministic
stage-appropriate floor rather than a guess.

**In practice, measured, it is not worth much** — Q4a shows six of the eleven
rows never bound the plan in any quarter and a seventh was overridden
throughout. I initially argued this section supported keeping the block visible;
**the binding measurement in Q4a is what changed my recommendation**, and it is
the more reliable of the two, because it is a measurement rather than an appeal
to what a lender might want.

---

## Q3 — The amber problem

231 cells styled as client inputs that do nothing when edited. **This is the
same class as** Model Inputs r18 (the dead COGS rollup) **and** Audit Source's
1,167 over-styled provenance cells (R-INPUT-01 C2-a).

**Under the chosen option (e), this row's share of the problem resolves
itself**: the 231 cells stop existing, and Revenue Drivers is left holding only
live drivers. **Model Inputs r18 and Audit Source's 1,167 cells still need the
styling pass** — omitting the ramp block fixes 231 of the ~1,400 mis-styled
cells and none of the rest.

**Recommendation for the remainder: one styling pass, not two commits.** Both
are the same defect — *a cell wearing the input convention that no consumer
reads* — fixed the same way, by not passing `input_style=True`. One
R49-neutral, R32-neutral change, one review of "which cells does the amber
convention actually promise something about", paired with the guard-test
fill/ink pairing assertion from R-INPUT-01 C2 so it cannot come back.

**Cost:** low. `write_values_row(..., input_style=False)` at the call sites, per
R-INPUT-01's verified chain. It is styling only, so **neither golden moves**
(R49 hashes text, R32 hashes formulas; fills are neither).

---

## Q4 — Disposition (AMENDED per Nick's ruling A1)

> **A1 supersedes the first version of this section.** Option (b) *relabel in
> place* was my original recommendation and is **rejected**: the block drives
> nothing, so it does not belong on a tab whose purpose is live drivers. The
> choice is between **(c') own hidden sheet** and **(e) omit**.

### Q4a — What is actually lost by omitting

Nick's premise is that the constraints are back-derivable from the file. **I
tested it per row rather than accepting it**, and the answer splits cleanly:
**the actuals are all visible; not one ceiling is recoverable.**

**VERIFIED** on Harrow Lane. Quarter alignment checked first — `values[q]` is
quarter `q` (Q1 COGS % = 0.142665, exactly the client's blended 15%/2%), so the
comparison below is like-for-like.

| Constraint row | Actual visible in file? | Where | Ceiling recoverable? | Quarters it actually bound |
|---|---|---|---|---:|
| Revenue QoQ **Target** | Yes | row 25, live formula | No | **12 / 20** |
| Revenue QoQ Max | Yes | row 25 | No | 0 / 20 |
| Revenue QoQ Spike Max | Yes | row 25 | No | 0 / 20 |
| Utilization Cap | Yes | Revenue Drivers utilisation row | No | n/a |
| COGS % Target | Yes | FINMO COGS ÷ Revenue | No | 0 / 20 |
| COGS % Max | Yes | FINMO | No | **exceeded in all 20** (see below) |
| Marketing % Max | Yes | Model Inputs r19 | No | 3 / 20 |
| R&D % Max | Yes | FINMO | No | 20 / 20 *(trivially — both are 0)* |
| G&A % Max | Yes | FINMO | No | 4 / 20 |
| Lease % Max | Yes | FINMO | No | 0 / 20 |
| Net Income Margin Floor | Yes | FINMO NI ÷ Revenue | No | 0 / 20 |

**Nick's premise holds for the actuals and fails for the ceilings — and that
turns out not to matter much, because of what the binding column shows:**

- **Six of eleven rows never constrained the plan at all.** Revenue QoQ Max,
  Spike Max, COGS % Target, Lease % Max and the Net Income Margin Floor bound
  in **0 of 20 quarters**; Lease sat at 8.3% against a 30% ceiling. Disclosing
  a limit that never touched the plan tells a lender nothing.
- **R&D's 20/20 is an artefact** — ceiling 0.0, actual 0.0. It is not a
  constraint, it is a business with no R&D.
- **Three rows did real work**: the Revenue QoQ *target* (12/20), Marketing %
  Max (3/20), G&A % Max (4/20). But their **effect is already fully visible** in
  the actuals a reader can see; only the label "this was a limit" is lost.
- **One row would actively raise a question the workbook cannot answer.**
  **VERIFIED: the shipped COGS % exceeds the stated `cogs_max` in every one of
  the 20 quarters** — 0.1427 rising to 0.1451 against a flat 0.1400 ceiling. The
  actual comes straight from the client's own per-line rates (15% groom / 2%
  nail). That is very likely correct engine behaviour — a client-stated fact
  should beat a benchmark ceiling — but **displaying the ceiling next to a plan
  that visibly breaches it invites a lender question with no answer in the
  file.** Whether the engine should flag this is a separate matter and
  **out of scope**; I am not claiming a defect, only that the number is a
  liability on a client-facing sheet. **TO-BE-TESTED** whether this holds on
  other businesses or is specific to a client whose stated COGS exceeds its
  NAICS band.

**Conclusion on lost value:** what omission loses is the sentence "a governor
was in force." For eleven rows, six of which never governed anything, one of
which was overridden, and three whose effect is already on the page. That is
close to zero client- or lender-facing value.

### Recommendation: **(e) OMIT**

| Option | Assessment |
|---|---|
| **(e) Omit** | **Chosen.** Removes 231 inert amber cells at the source; nothing consumes the block (Q1); the disclosure it carries is near-valueless once the actuals are visible (Q4a); and it avoids displaying a COGS ceiling the plan exceeds. Smallest workbook, least to explain. |
| (c') Own hidden sheet | Preserves a disclosure nobody asked for, at the cost of a new sheet that **no one will ever audit** — which is precisely how Audit Source came to carry 1,167 engine cells styled as client inputs. Creating a second such sheet to hold data of near-zero value repeats a known failure. |

**The one thing to keep.** The engine payload itself
(`stage_ramp_contract`) is untouched and stays in `planning_run_json` — omitting
the *block* removes a rendering, not the record. Anyone investigating a plan can
still read the contract, its `rationale`, `decision_source` and
`business_stage`, from the run. **Nothing about the audit trail is lost; only a
sheet rendering is.**

---

## Q5 — Row 25 (row 17 on a single-line business)

**VERIFIED: "Actual Revenue QoQ Growth" is live on both fixtures** —
`=IFERROR(D14/C14-1,0)` single-line, `=IFERROR(D22/C22-1,0)` multi-line, reading
the revenue row, with its own annual `=AVERAGE(...)` aggregation.

**Recommendation: promote it out of the ramp block into the live driver
section, immediately under revenue.** It is a *result*, not a constraint, and it
is the one row here that responds when a client edits a driver — which makes it
genuinely useful in a sold model. It must not be swept into a disposition aimed
at the inert rows. Leaving it visually inside a block relabelled "constraints
the engine honoured" would mislabel the one live row in the group.

**Under the chosen option (e), this is no longer optional — it is the whole
reason row 25 needs an explicit decision.** Once rows 26-36 are omitted, row 25
would otherwise be a lone survivor under a section header for a block that no
longer exists. **Recommendation: it stays on Revenue Drivers, immediately under
the revenue rows, in the live driver section**, and the "Stage Ramp Contract"
section header is removed with the block.

**Verify forward:** moving it changes its row number, and its annual columns are
`AVERAGE` over its own row. Both are self-contained (**VERIFIED** — nothing else
references it), so the move is safe, but the ctx registry key must move with it.
Its formula reads the revenue row by address (`=IFERROR(D14/C14-1,0)` /
`=IFERROR(D22/C22-1,0)`) — **VERIFIED shape-dependent**, so it must be emitted
through the ctx key for the revenue row, never a literal.

---

## Q6 — Gate and downstream impact (AMENDED)

Under the recommended **(e) omit + Q5 promotion**:

| Surface | Movement |
|---|---|
| **R32** (formulas) | Moves. The 11 constant rows carry no formulas, so removing them costs nothing directly — but every Revenue Drivers row below the block shifts up, and row 25's `AVERAGE` formulas move with it. **A row-shift diff, not a re-authoring.** |
| **R49** (text) | Moves substantially: 11 row labels and the section header disappear, and every label below them re-keys by address. Large, noisy, entirely explainable. |
| **R31** | Must not move. No engine code is touched; `stage_ramp_contract` stays in `planning_run_json` untouched. |
| **Recalculated values** | **Zero change expected.** Nothing reads the block (Q1). Row 25's formula follows the revenue row through the ctx key. **Any moved value is a regression** — that is the evidence bar, on both fixtures, recalculated in real Excel. |
| **Cover `_CONTENTS`** | Revenue Drivers' description ("Capacity, price and utilisation per line of business") **becomes more accurate**, not less. No change required. A-129 remains open separately. |

**Omission-specific check, as A1 requires — VERIFIED, nothing depends on the
block existing:**

- **Checks**: 0 cells mention "Stage Ramp"; Q1 already proved 0 formula
  references.
- **Diagnostics**: 0 cells mention the ramp. (Diagnostics r63 tracks
  `marketing_percent_of_revenue`, which is the *actual*, not the cap.)
- **Charts**: 9 charts in the workbook, **0 series reference the block** (Q1,
  all six paths, both fixtures).
- No defined name, data validation or conditional-formatting rule touches it.

**The (c') risk A1 asks about, stated for completeness even though (c') is not
recommended:** a new hidden sheet holding engine constants is exactly the
Audit Source shape — 1,167 engine cells styled as client inputs, undetected
because nobody opens a hidden sheet. If (c') were chosen anyway, the input
styling must be stripped **in the same commit that creates the sheet**, never
as a follow-up, because a follow-up on a hidden sheet is what never happens.

**R-MKTG-01 dependency — where Marketing % Max comes from once the block is
gone.** **VERIFIED (source read):** the value does not originate on Revenue
Drivers. `schedule_sheets.py:222` renders it from
`data.stage_ramp_contract → quarter_ramp_grid[q].marketing_max`, via
`data.py:157`. A marketing tab reads the **same payload field directly** — it
never needed the Revenue Drivers row. **Omitting the block costs R-MKTG-01
nothing**, and a single cap value on the marketing tab is better context than
eleven rows on a driver tab.

---

## Answer in three sentences (AMENDED)

**Nothing consumes the block** — zero references across formulas, defined names,
data validation, conditional formatting, chart series and hyperlinks, on both
fixtures (my first scan said otherwise and was wrong: it had swallowed the live
row and counted its own self-references). **Omit it** — Nick's premise that the
constraints are back-derivable holds for the actuals and fails for the ceilings,
but the ceilings turn out not to be worth recovering: six of the eleven rows
never bound the plan in a single quarter, R&D's apparent 20/20 is 0-against-0,
and the COGS ceiling is *exceeded* in all 20 quarters, so displaying it would
raise a question the file cannot answer; a hidden sheet would just be a second
Audit Source. **Row 25 stays and moves up** — "Actual Revenue QoQ Growth" is
live, is the one row here that responds when a client edits a driver, and
belongs in the live driver section under revenue once the section header around
it is gone.
