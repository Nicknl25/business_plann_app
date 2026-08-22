# R-CAPEX-01 — costing the CapEx useful-life input

**Status:** costing only, awaiting Nick's ruling. NOTHING BUILT.
**Asked:** 2026-08-21 — *"The useful-life input is a separate decision. Tell me
what it would cost and what moves, and I'll rule on it on its own."*
**Measured:** 2026-08-22 against `6d8ee66`.

---

## The short answer

**It costs about a day and it moves nothing.** The engine already computes
depreciation exactly this way; the sheet just displays the answer as a fitted
rate instead of as the life that produced it.

---

## What the engine actually does

`finmo_bridge.py:1718-1810`, method name in its own payload:
**`rolling_capex_vintage_straight_line`**.

- one vintage for the opening book — `opening_ppe / useful_life_quarter_count`
- one vintage per quarter's capex — `final_capex / useful_life_quarter_count`
- each charges for `useful_life_quarter_count` quarters from when it is placed
- `useful_life_years` defaults to **5.0** (`_CAPEX_USEFUL_LIFE_YEARS`), = 20 quarters

That is straight line on original cost over a stated life — precisely the
mechanism the sheet would be surfacing. The rate the sheet shows is derived
FROM the dollars, not the other way round.

## What moves — measured, not argued

Recomputed vintage straight-line from each workbook's own capex series and
opening PPE, against the Depreciation Expense the sheet prints today:

| draft | printed, 20q | straight-line-on-cost | delta |
|---|---:|---:|---:|
| gate fixture | 16,435 | 16,435 | **0** |
| Harrow `85f5825d` (08-19) | 101,233 | 101,233 | **+0** (max cell ±0.04, rounding) |
| Falls City `76c6e0b9` (08-07) | 220,897 | 1,900,892 | +1,679,996 |

**Falls City is a stale draft, not a defect.** Its payload predates
`7b26ff6` (2026-08-14, *"opening-PPE straight-line depreciation"*), so it never
depreciates its opening book at all — PPE climbs 1,680,000 → 1,879,883 over
five years. Confirmed by date: **every draft that excludes the opening book is
2026-08-13 or older; every draft from 08-16 on includes it** (28 correct / 172
stale across 200 sampled, two independent detectors agreeing).

So on current engine output the change is **numerically neutral**.

⚠️ Worth knowing separately: **Falls City is one of the three drafts I verify
every workbook change against**, and its engine payload is three weeks stale.
Workbook-to-workbook comparisons on it remain valid, but it is not
representative of what the engine emits today.

## What it would cost

| piece | scope |
|---|---|
| `build_capex_depreciation_sheet` — replace `MIN(opening × rate, opening)` with the vintage window already used for the lease | ~15 lines |
| new editable "Useful life in quarters" row | ~5 lines |
| `checks_sheet.py:563` — the "Depreciation formula" tie-out asserts `dep = opening × rate`; it must move with the rule | small, and it WILL go red first (it did on the prototype) |
| `model_inputs_sheet.py:145` — Model Inputs "Depreciation" maps to the CapEx **rate** row | decide: keep the rate as a derived row, or re-point |
| R32 + R49 re-bless | row shifts only |

The lease block already carries this exact formula shape, so it is a
transplant rather than a design.

## Two defects found while costing

1. **The stated life is a hard-coded fallback.**
   `build_capex_depreciation_sheet` reads
   `data.schedules.get("useful_life_years") or 5`, and that key is **`None`** —
   measured. The subtitle's "5 years" is the `or 5`, not the model's
   assumption. The engine's real value is reachable at
   `expense_rows[…].capex_depreciation.useful_life_years`. Today both are 5.0,
   so nothing is visibly wrong; if the engine's life ever changed, the sheet
   would keep saying 5.

2. **Model Inputs row 28 "Depreciation" holds a RATE** (0.00025), sitting
   directly above row 29 "Depreciation Expense" which holds dollars (420).
   FINMO consumes row 29, so nothing is currently wrong — but the label reads
   like an amount.

## Recommendation

Take it. It is numerically neutral on current output, it deletes a derived
row masquerading as an input, and it replaces it with the assumption the
engine is actually using — which is the same move already made on the lease
block. Fix (1) in the same change so the life on the page is the life in the
model.
