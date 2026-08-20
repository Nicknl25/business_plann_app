# R-MKTG-02 — Backing into the marketing drivers from the settled percentage

**Tier:** research only. No code changed. **Date:** 2026-08-20 · **Author:** VS

Claim tags per 04800b2: **VERIFIED** (measured) / **VERIFIED (source read)** /
**UNVERIFIED** / **TO-BE-TESTED**.

**Rulings carried in (A1), treated as settled and not re-argued:** CAC is the
plug; the settled percentage is never recomputed, only decomposed. Retention is
an anchored, disclosed, editable assumption in the Valuation-sheet pattern. Q1's
prior-quarter customers seed from the stub. Units come from Revenue Drivers.
Post-delivery divergence is intended, not guarded against.

---

## 1. The core identity

```
marketing_$_q      = settled_percent_q x revenue_q          (exact, already true)
customers_q        = units_q / repeat_units_per_customer
retained_q         = customers_(q-1) x retention            <- the assumption
new_customers_q    = customers_q - retained_q
CAC_q              = marketing_$_q / new_customers_q        <- the plug
```

**VERIFIED on Harrow Lane:** `marketing_$ / revenue` equals the settled percent
to the last decimal in all 20 quarters. Because CAC absorbs the residual, **the
tie-back is exact by construction** — there is no rounding path back into the
percentage. Resulting CAC ≈ **$41–44** against a customer worth ~$430/year,
which is a sane ratio rather than arithmetic for its own sake.

**The stub ruling checks out — VERIFIED:** column C carries revenue 125,000 and
every per-line `units_per_period_capacity` / `utilization_rate`, so stub units
and therefore stub customers are computable. Q1 seeds from real data, and the
$13.91-vs-$44 Q1 artefact I flagged earlier disappears.

## 2. What is exact and what inherits the assumption

The tab must say this on its face.

| Line | Status |
|---|---|
| Revenue | **Exact** — linked |
| Marketing $ | **Exact** — settled percent × revenue |
| Marketing % (output) | **Exact** — the settled driver, unchanged |
| Units | **Exact** — Revenue Drivers capacity × utilisation × periods |
| Customers | **Assumed** — inherits `repeat_units_per_customer` |
| Retained | **Assumed** — inherits retention *and* repeat rate |
| New customers | **Assumed** — inherits both |
| **CAC** | **Assumed** — inherits both, and absorbs every residual |

**Three of eight lines are exact; four inherit the repeat rate; CAC inherits
everything.** CAC is the most quotable number on the tab and the softest — it
should carry the assumption label most visibly, not least.

Precedent to copy (**VERIFIED**, `valuation_sheet.py:194,217`): the Valuation
sheet already stamps each input `GROUNDED` or `ASSUMPTION` with a citation, and
styles only the ASSUMPTION rows as editable via `design.input_cell()`. Reuse it
verbatim — same column layout, same basis/source/as-of columns.

## 3. Class coverage — measured, not hypothesised

**VERIFIED across 400 real drafts.** All three shapes exist in production:

| Class | Count | Example |
|---|---:|---|
| Zero-marketing | **1** | Cedarhill Animal Hospital, revenue 717,288, marketing 0 |
| Non-consumer basis | **19** | `b2b` Millgate Press (b2b reach 230, b2c 0); `mixed` Kestrelbrook (b2b 250, b2c 11,500) |
| Pre-revenue | **2** | Anderson & Blake Legal, revenue 0, marketing 733,824 |

**Finding that simplifies the design: the decomposition is basis-agnostic.**
`market_basis_type` (consumer / b2b / mixed) only affects the *reachable market*
**context** line. The arithmetic runs off units, repeat rate and retention, none
of which care whether the entity is a person or a firm. **B2B and mixed need no
separate branch — only a correctly labelled context row** ("reachable firms"
vs "reachable households", and for `mixed`, both).

### The four rules that make every class work

| # | Rule | Covers |
|---|---|---|
| **R1** | `new_customers_q` floors at a small positive epsilon, and CAC renders through `IFERROR(...,"—")` | The genuine break: **`new_customers` can be 0 or negative** whenever retention × prior customers ≥ current customers. This is not exotic — **a client typing retention = 100% on a flat-revenue business produces exactly this**, and it is a display defect (`#DIV/0!` in a sold file), not a correctness one. |
| **R2** | Zero-marketing → every derived line renders **0**, CAC renders "—", and the tab states "this plan carries no marketing spend" | Cedarhill. `0 / new` is 0 when new > 0 and 0/0 when it is not; R1 handles the second. |
| **R3** | Pre-revenue → stub customers are legitimately **0**, so Q1 `new == customers` and CAC is simply first-quarter CAC | Anderson & Blake. **No special case needed** — the stub seeding rule already produces the right answer; it must just not be mistaken for a bug. |
| **R4** | Businesses with no meaningful entity count (`units` or `repeat_units_per_customer` absent or zero) render the exact lines only, and the assumed block reads "not modelled for this business" | The B2B referral-dominant case. **The tab degrades to its exact half rather than inventing an audience.** |

**R4 is the important one.** M6's `business_model_pattern_overrides_json` is the
engine-side escape hatch for referral-dominant businesses; the workbook needs
its own, and "show the exact lines, omit the assumed ones" is a cleaner answer
than a modelled fiction. **TO-BE-TESTED:** whether any real draft has units but
no derivable repeat rate — I did not find one in 400, but I did not prove the
absence.

## 4. Recommendation

**Build it, as a post-process plus a schedule tab, in that order.**

**Where it sits.** A pure post-process after the restoration-loop solver settles
the driver row, before workbook build. **The precedent is exact and in-house:**
`finmo_break_even.py` (W1) reads the settled model and writes
`finmo_json["break_even"]` without touching the engine. Same seam, same shape,
same blast radius.

**What it persists.** A new `marketing_schedule_json` column on
`intake_consult_drafts`, alongside `marketing_model_json`, `payroll_headcount`
and `debt_schedule` — all of which `DraftWorkbookData` already reads by the same
pattern (**VERIFIED source read**). Contents: the eight per-quarter lines, plus
the retention and repeat-rate assumptions with `source`, `basis` and `as_of`,
plus the class flag from §3 so the builder knows which of R2–R4 applies.

**What the tab renders.** Header (business, basis type, reachable market with
the right noun, NAICS band, stage-ramp Marketing % Max read from
`stage_ramp_contract.quarter_ramp_grid[q].marketing_max` — **VERIFIED** it does
not depend on the Revenue Drivers block R-RAMP-01 recommends omitting); the
eight lines Q1–Q20 with the stub column; an assumptions block in the Valuation
pattern; a provenance footer.

**Editable cells:** retention and repeat rate. Both amber via
`write_values_row(input_style=True)` — the tab **inherits** the convention.
Everything else is a formula.

**Why this is worth building where the R-MKTG-01 audience tab was not.** The
audience tab would have shown inputs that do not reach the shipped number — live
looking, inert. This tab's every line is **arithmetically downstream of the
number the client agreed**, so editing retention or repeat rate moves customers,
new customers and CAC immediately and visibly. It is a real schedule, not a
report, and it ties out exactly on delivery.

**Sequencing.** Post-process and payload first, verified against a real draft
with **zero workbook change** (both goldens untouched, R31 untouched — it is
additive JSON). Tab second, as its own commit and its own re-bless: R49 moves by
the new sheet's labels, R32 by its formulas, **every pre-existing recalculated
value must be identical**, on both a single-line and a multi-line fixture.

**One thing to settle before building:** the retention default. M6 proposes
per-business-model defaults (5% B2C subscription, 3% B2B recurring, 30% B2C
transactional, 50% B2B project, 10% default) and **flags them as educated
guesses at `confidence_tier: low`**. That table does not exist yet. Either seed
it as part of this work with the numbers disclosed on the page, or take a single
disclosed default and refine later — **but the tab must name the source either
way**, because per §2 four of its eight lines and its headline CAC all inherit
that one number.
