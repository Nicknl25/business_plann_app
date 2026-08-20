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

**Is it meaningful as disclosure?** Yes, and that is its whole remaining value.
It answers a question a lender actually asks — *what did you constrain this plan
to?* — with a per-quarter, per-stage answer: revenue growth targets and ceilings,
a utilisation cap, expense ceilings and a net-income margin floor. Its
`rationale` and `decision_source` fields say it was a deterministic
stage-appropriate floor, not a guess. **That is disclosure value independent of
anything reading it.**

---

## Q3 — The amber problem

231 cells styled as client inputs that do nothing when edited. **This is the
same class as** Model Inputs r18 (the dead COGS rollup) **and** Audit Source's
1,167 over-styled provenance cells (R-INPUT-01 C2-a).

**Recommendation: one styling pass, not three commits.** All three are the same
defect — *a cell wearing the input convention that no consumer reads* — and they
are all fixed the same way, by not passing `input_style=True`. Doing them
together means one R49-neutral, R32-neutral change and one review of the whole
question "which cells does the amber convention actually promise something
about". Splitting it means three re-blesses arguing the same point.

**Cost:** low. `write_values_row(..., input_style=False)` at the call sites, per
R-INPUT-01's verified chain. It is styling only, so **neither golden moves**
(R49 hashes text, R32 hashes formulas; fills are neither).

**Pair it with the guard-test pairing assertion** proposed in R-INPUT-01 C2, so
the incoherent state cannot come back.

---

## Q4 — Disposition

**Recommendation: (b) RELABEL IN PLACE.**

Keep the block on Revenue Drivers, strip the input styling, and put a header
over it saying plainly what it is — the constraints the engine honoured, not
levers. Add the `business_stage`, `planning_mode` and `decision_source` values
as a short provenance line, since they are already in the contract and are the
part a lender would ask about.

| Option | Why not chosen |
|---|---|
| (a) Leave as-is | 231 cells keep implying they are editable. The workbook is being sold to people who will try. |
| **(b) Relabel in place** | **Chosen.** Cheapest honest option; keeps disclosure where a reader of Revenue Drivers already is; both goldens move only by the new header text (R49). |
| (c) Move to a reference area | Buries genuine disclosure. The constraints are *about* the revenue drivers; separating them costs the reader the adjacency that makes them legible. |
| (d) Hide | Hiding moves neither digest (**VERIFIED**: neither surface reads `sheet_state`), but Audit Source is the standing proof that hidden sheets accumulate problems nobody sees — its 1,167 mis-styled cells survived precisely because nobody looks. Hiding this block would repeat that. |
| (e) Omit | Loses the disclosure and saves nothing a client perceives. |

Against the standing goal — a client scanning for what they can change should
not find eleven rows of engine constants dressed as inputs — (b) fixes exactly
that while keeping what a lender wants.

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

**Verify forward:** moving it changes its row number, and its annual columns are
`AVERAGE` over its own row. Both are self-contained (**VERIFIED** — nothing else
references it), so the move is safe, but the ctx registry key must move with it.

---

## Q6 — Gate and downstream impact

Under the recommended **(b) + Q5 promotion**:

| Surface | Movement |
|---|---|
| **R32** (formulas) | Moves only if row 25 is relocated — its `AVERAGE` formulas change row. The 11 constant rows carry no formulas, so relabelling them moves nothing. |
| **R49** (text) | Moves: the new section header and provenance line are new static text; relocating row 25 re-keys its label by address. |
| **R31** | Must not move. No engine code is touched. |
| **Recalculated values** | **Zero change expected.** Nothing reads the block (Q1), and row 25's formula follows the revenue row wherever it sits. **Any moved value is a regression** — that is the evidence bar. |
| **Cover `_CONTENTS`** | The Revenue Drivers description ("Capacity, price and utilisation per line of business") stays accurate. No change required, though A-129 (Valuation omitted) remains open separately. |

**R-MKTG-01 dependency, addressed.** That directive assumes a client can see
`Stage Ramp Marketing % Revenue Max` (2.0%) as context on a marketing tab.
**Option (b) preserves it** — the row stays visible and readable on Revenue
Drivers, and a marketing tab can reference it by ctx key. This is a further
argument against (c), (d) and (e), all three of which would either bury that
context or delete it.

---

## Answer in three sentences

**Nothing consumes the block** — zero references across formulas, defined names,
data validation, conditional formatting, chart series and hyperlinks, on both a
single-line and a multi-line fixture, so Nick's read is confirmed (my first scan
said otherwise and was wrong: it had swallowed the live row and counted its own
self-references). **Relabel it in place** — strip the amber input styling from
all 231 cells, head the block as the constraints the engine honoured with its
`business_stage` / `planning_mode` provenance, and fold that styling fix into
one pass with Model Inputs r18 and Audit Source's 1,167 cells, since all three
are the same defect. **Row 25 moves the other way** — "Actual Revenue QoQ
Growth" is genuinely live and should be promoted up into the live driver section
under revenue rather than left inside a block relabelled as inert.
