# R-MKTG-01 — Marketing Schedule Tab (Module 6, Task 6.7)

**Tier:** research only. No builder, schedule, formula, table or Python module
changed. No gate re-bless. Deliverable is this document.

**Date:** 2026-08-20 · **Author:** VS · **Branch:** intake-stable

**Scope carried in:** R-INPUT-01's inversion is set aside. The schedule tabs are
the client's driver layer and stay as they are. COGS is settled and out of
scope. This directive covers **marketing only**.

## Claim tagging (per 04800b2)

| Tag | Means |
|---|---|
| **VERIFIED** | Measured on a workbook built in memory, or on a real draft's persisted data. Method stated. |
| **VERIFIED (source read)** | Read in code; not measured on an artifact. |
| **UNVERIFIED** | Reasoned, not measured. A hypothesis. |
| **TO-BE-TESTED** | Needs an experiment nobody has run. |

**Measurement basis:** the completed CW-038 Harrow Lane run,
draft `85f5825d50e24ccf8327441a52fbfee5` (coherence converged, 0 errors), read
directly from `intake_consult_drafts`; plus workbooks built in memory through
the production builder on the frozen single-line and two-product fixtures.
Instruments: `scratchpad/mktg_trace.py`, `scratchpad/r2_orphan_census.py`.

---

## The headline finding, before anything else

**The declining marketing curve is produced by the target solver, optimising an
EBITDA-margin target. It is not GPT-authored, not the stage ramp, and not the
audience math.**

**VERIFIED** — the engine stamps its own provenance in `model_input_json`, on
the `expenses::Marketing` section row:

```
lever_id                            expenses::Marketing
input_semantics                     percent_of_revenue
controller_write                    True
writable_full_quarters_only         True
values          [0.018, 0.018, 0.017793…, 0.017583…, …, 0.0132]
applied_by_target_solver_quarters   {'2': {'target_metric': 'ebitda_margin',
                                           'applied_value': 0.017793157894736844}, … }
```

| Period | Value | Origin (VERIFIED) |
|---|---|---|
| Stub (col C) | 0.018 | **Client's own intake figure** — `marketing_total_year1` 9,000 ÷ `current_revenue` 500,000 = exactly 0.018 |
| Q1 (col D) | 0.018 | Seed held. **Not** in `applied_by_target_solver_quarters`. |
| **Q2–Q20** | 0.017793 → 0.0132 | **All 19 written by the target solver**, every one against `target_metric: ebitda_margin` |

**And the audience math does not produce the shipped number.**
`marketing_model_json` is persisted (11,793 chars) and carries
`baseline_marketing_percent = 0.08` and `baseline_marketing = 40,000`. The
workbook ships **0.018 / 9,000**. The audience derivation's own answer is
**4.4× larger than what the client sees** and plays no part in the delivered
figure for this business.

Two consequences that govern everything below:

1. **A tab cannot recompute the shipped curve from audience inputs in Excel.**
   The curve is the output of a constrained optimisation over 28 levers. No
   formula chain reproduces it.
2. **Marketing is one of 28 `controller_write` levers** (VERIFIED) — the solver
   also writes capacity, unit price, utilisation, COGS %, R&D and lease. This is
   not a marketing-specific problem; it is the standalone-product problem, and
   it is developed in Q6.

---

## Q1 — What is actually available per quarter today

**(a) Is per-quarter marketing data persisted anywhere?**
**VERIFIED: only as the final driver row.** The single per-quarter artifact is
`model_input_json → sections → expenses → expenses::Marketing → values` (21
entries). There is no per-quarter audience, CAC, acquisition or churn series
anywhere. `marketing_model_json` is **annual only**.

**(b) Where does the declining shape come from?**
**VERIFIED — the target solver, optimising `ebitda_margin`.** See the headline
above. This is the fact the directive called most important, and it is
answerable with the engine's own stamp rather than by inference. The seed is the
client's stated ratio; Q1 holds it; Q2 onward are solved.

Note the mechanism is *not* "flat dollars over growing revenue" — I tested that
hypothesis and it fails. **VERIFIED**: marketing dollars rise 2,250 → 2,267.68
through Q6 and then *fall* to 2,262.97 by Q8, while the percent declines
monotonically. Dollars follow a solved curve, not a constant.

**(c) `marketing_model_json` contents for a real business** — **VERIFIED**,
Harrow Lane:

| Field | Value | Note |
|---|---|---|
| `estimation_method` | `gpt_estimate` | not a lookup |
| `baseline_marketing_percent` | **0.08** | 4.4× the shipped 0.018 |
| `baseline_marketing` | 40,000 | vs client's stated 9,000 |
| `reachable_market` | 8,500 | b2c 8,500 / b2b 0 |
| `capture_rate_year1` | 0.83 | |
| `expected_customers_or_clients_year1` | 650 | |
| `expected_units_year1` | 7,053 | |
| `required_units_year1` | 7,053.29 | |
| `demand_supports_required_units` | **False** | the audience math says demand does *not* support the plan |
| `market_basis_type` | `consumer` | |
| `marketing_intensity` | `medium` | |
| `ready` | True | |

That `demand_supports_required_units: False` is worth a separate look — the
audience model disagrees with the shipped plan and nothing surfaces it.
**Recommend separate triage; out of scope here.**

**(d) Does the `marketing_schedule` column exist?**
**VERIFIED: NO.** The only marketing-ish column on `intake_consult_drafts` is
`marketing_model_json`. M6 Task 6.4 would have to add it.

**Builder attribution (VERIFIED, source read):** the marketing driver row is
written to the sheet by `model_inputs_sheet.build_model_inputs_sheet` via
`excel_utils.write_values_row`; the values originate in the engine, not the
builder.

---

## Q2 — Can the tab ship before the backend schedule?

| Path | What the client sees | Honest? | Cost | Forecloses |
|---|---|---|---|---|
| **(i) Tab first, derivation-only** | Audience block (real, annual), NAICS band, stage-ramp cap, and the 21 shipped percents — with the per-quarter block labelled solver-produced | **Yes, if labelled truthfully.** The audience figures are real; they are just not what produced the curve | Small — one builder, one re-bless | Nothing |
| **(ii) Schedule first, then tab** | A fully derived per-quarter schedule | Yes | **Large.** M6 is ten tasks, depends on M1 (in_progress, E2E deferred) and M3 (completed). M6's own risk notes say marketing numbers **will change** | Ships nothing for months |
| **(iii) Tab shell now, populate later** | Section structure with empty blocks | Partly — empty blocks in a client-facing sheet read as a defect | Small, but ships a visibly incomplete sheet | Nothing |

### Recommendation: **(i), with one hard condition**

Ship the tab now as a **derivation and provenance sheet**, on the condition that
**it does not claim to be a live driver tab**, because — per Q3 — it cannot be
one for the shipped curve without re-running the solver.

Why not (ii): M6 depends on M1, whose **E2E verification is deferred**
(VERIFIED, module INDEX). Starting a ten-task subsystem on an unverified
foundation, whose own risk notes flag churn as "the biggest unknown" and predict
changed numbers, is a large bet for a tab Nick wants now.

Why not (iii): empty blocks in a sold artifact are worse than an honest smaller
sheet.

**What (i) would leave blank or labelled engine-produced:** the per-quarter
acquisition math — required entities, retained, new entities required, required
acquisitions, CAC per quarter. None of it exists (Q1a). The tab would show the
annual audience math it *does* have, and label the per-quarter percent row as
solver-produced against an EBITDA-margin target.

---

## Q3 — What would make the tab live rather than a report

**This is the make-or-break question, and the honest answer is that for the
shipped curve, it cannot be made live.**

**(a) Cells a client could edit.** Of the audience inputs that exist:
`reachable_market`, `capture_rate_year1`, `repeat_units_per_entity` (by
cadence), `expected_customers_or_clients_year1`. All are **annual**, all are
**GPT-estimated** (`estimation_method: gpt_estimate`), and **none of them feeds
the shipped percent** (VERIFIED — the shipped percent comes from the client's
stated ratio, then the solver).

**(b) The formula chain.** A chain from audience inputs to a per-quarter percent
*is* expressible in Excel:

```
required_acquisitions_q  = new_entities_required_q                 (= entities_q − retained_q)
marketing_dollars_q      = required_acquisitions_q × CAC_q × stage_modifier
marketing_percent_q      = marketing_dollars_q / revenue_q
```

Every step is arithmetic; **no macro is needed**. But this chain produces a
*different* number from the one the workbook ships, because the shipped number
is a solver output against an EBITDA target. **You cannot have both.** Either
the tab drives the model (and the delivered plan's marketing changes, breaking
convergence with the other 27 levers) or it explains the model (and it is a
report).

**The step that cannot be expressed in Excel is the solver itself** — a
constrained optimisation over 28 levers hitting `ebitda_margin`. Naming it as
required: yes, and it is fatal to a live-tab-for-the-shipped-curve.

**(c) Model Inputs r19 picking it up, and the cycle question.**
If r19 became `='Marketing Schedule'!<output cell>`, the edge is clean **only if
the tab never reads FINMO**. **VERIFIED**: revenue per quarter is available from
Revenue Drivers / Model Inputs without touching FINMO, and FINMO r11 reads
Model Inputs — so `Marketing Schedule → Model Inputs → FINMO` is acyclic. **A
tab that read FINMO revenue would close the loop and is ruled out.**

**Recommendation for the output block:** in path (i), r19 should **stay a
literal** and the tab should display the same values with provenance. Repointing
r19 to a tab whose math produces a different number would silently change the
delivered plan. If a live block is ever wanted, it belongs behind M6, not ahead
of it.

---

## Q4 — Spec-vs-current reconciliation

| Spec says (Task 6.7 / Part 13.10) | Today (VERIFIED) |
|---|---|
| `python/client_statements_output_excel/export_client_workbook.py` | Package is at repo root: `client_statements_output_excel/`, not under `python/` |
| `_compute_marketing_model_json` at line 3365, `_fallback_marketing_estimate` at 3205 | Now **5077** and **4917** — the file has drifted ~1,700 lines |
| "workbook nav bar" | **No nav bar exists.** The equivalent is the Cover `_CONTENTS` index (`cover_sheet.py`), which lists 11 sheets and **omits Valuation** (A-129) |
| "match the payroll/debt/depreciation tab conventions" | Still valid, but those conventions now run through `design.py` and its guard test |
| Tab sections (header / inputs / computation / output / provenance) | Structure is sound; the **inputs and computation blocks have no per-quarter data to fill** (Q1a) |

**Restated Task 6.7 against today's architecture:**

- **Builder slot:** a `build_marketing_schedule_sheet` must run **after**
  `revenue_drivers` (it needs revenue driver rows) and **before**
  `model_inputs` (if r19 is ever to reference it). That places it in the
  existing chain between `cash_equity` and `model_inputs`. **VERIFIED** that a
  builder cannot reference a sheet whose builder has not run.
- **ctx registry:** register every row via `ctx.add_schedule_row("Marketing
  Schedule", key, row)`. Row numbers are shape-dependent and must never be
  literals.
- **design.py:** reuse `write_values_row(..., input_style=True)` for any
  editable cell — the tab **inherits** the amber convention. The guard test
  covers the sheet the moment it exists and will fail on any off-system font,
  fill, number format or chart.
- **Nav:** add the tab to Cover `_CONTENTS`, and fix A-129 in the same commit.

---

## Q5 — Which drivers are genuinely the client's

| Input | Class | Where it comes from today (VERIFIED) | Did the client supply it? |
|---|---|---|---|
| `marketing_total_year1` → the 1.8% seed | **CLIENT LEVER** — the only real one | Intake `financials_json` | **Yes.** Stated directly. |
| `reachable_market` (8,500) | Nominally client, in practice not | `marketing_model_json`, `gpt_estimate` | **No.** Never asked. |
| `capture_rate_year1` (0.83) | Nominally client, in practice not | same | **No.** |
| `expected_customers_or_clients_year1` (650) | Derived | same | No |
| `repeat_units_per_entity` by cadence | ENGINE CONSTANT | hardcoded 6 / 2.5 / 1.2 / 2.0 (M6 6.1 would table it) | No |
| NAICS marketing % band | ENGINE CONSTANT | industry baseline resolver (M1) | No |
| Stage-ramp Marketing % Max (2.0%) | ENGINE CONSTANT, shown | Revenue Drivers stage-ramp row | No |
| Stage CAC modifier | ENGINE CONSTANT | M6 policy table — **does not exist yet** | No |
| Churn | **Does not exist today** | M6 6.1 would introduce it | No |
| The 19 solved quarters | **DERIVED — solver output** | target solver, `ebitda_margin` | No |

**Levers the client never gave and cannot judge — call-outs per the directive:**
`reachable_market`, `capture_rate_year1` and `repeat_units_per_entity` are all
GPT-estimated or hardcoded. Presenting them as client levers would invite a
client to "correct" a number they have no basis for, and — because the shipped
percent does not depend on them — **nothing would happen when they did.** That
is the worst possible outcome for a sold tool: an input that looks live and is
inert.

**There is exactly one genuine marketing lever today: the client's own stated
annual marketing spend.**

---

## Q6 — The standalone test, and it is bigger than marketing

For each editable cell, does editing it recalculate through the workbook?

| Cell | Propagates? | Detail |
|---|---|---|
| Model Inputs r19 (marketing %) | **Yes, fully** | VERIFIED chain: FINMO r11 `=D8*'Model Inputs'!D19` → Marketing → EBITDA → Net Income → Cash Flow → Balance Sheet → Calc → Dashboard, Valuation (reads FINMO), Checks, break-even, ratios. Editing r19 today already works. |
| A proposed audience block (reachable market, capture rate, CAC) | **No** | Nothing downstream reads it. Inert by construction unless the Q3(b) chain is wired *and* r19 repointed — which changes the delivered plan. |
| Stage-ramp cap display | No, by design | Reference only. |

### The list Nick asked for: what will not respond when a client changes a driver

**VERIFIED unless noted.**

1. **The solver's convergence — the big one.** 28 levers were jointly solved to
   hit `ebitda_margin`. Change any one in Excel and the other 27 keep their
   solved values. The workbook recalculates *arithmetically* and stays
   internally consistent, but it is no longer the optimised plan the engine
   produced, and **nothing in the workbook says so.** This applies to unit
   price, capacity, utilisation, COGS %, marketing, R&D and lease alike.
2. **The audience math** (`marketing_model_json`) — annual, engine-side, not in
   the workbook at all. A client changing revenue drivers gets no update to
   reachable market or capture rate.
3. **`demand_supports_required_units: False`** — the audience model's
   disagreement with the plan is computed once at intake and never surfaced.
4. **Valuation reference constants** — risk-free rate, ERP, exit multiples carry
   an "As of" date (VERIFIED, `Valuation!L5`) and are literals. They go stale
   and **the sheet does say when they were sourced**, which is the right
   behaviour. Worth confirming a client understands they will not refresh.
5. **The stage-ramp contract rows** — the constraint envelope the engine
   converged against. Displayed, never re-derived.
6. **NAICS benchmark bands** — engine-side, resolved at build time.
7. **Payroll wage benchmarks** — GPT-authored per role; a client adding
   headcount gets no new benchmarked wage.

**This list, not the tab, is the real boundary of the sellable product.** The
workbook is a fully live *arithmetic* model — every formula recalculates — but
it is a **frozen optimisation**. That distinction is honest, defensible, and
worth stating to a buyer in the workbook itself. **Recommend a short "How this
model behaves when you change it" block on the Cover** — cheap, and it converts
the biggest weakness into a statement of what the product is.

---

## Q7 — Gate impact

| Golden | Expected movement under path (i) |
|---|---|
| **R49** (text, `4d5d81484fd8`) | **Moves.** All new tab labels, section headers, provenance footer. Values drop out of the pin by construction (per-draft), labels stay. |
| **R32** (formulas, `8878c405e17d`) | **Moves** by the tab's own formulas. If r19 stays a literal (recommended), Model Inputs does **not** move. |
| **R31** (model payloads) | **Must NOT move.** Path (i) touches no engine code. R31 drift means the change escaped its blast radius. |

**Evidence bar — the strongest available here.** Under (i) the tab is additive
and reads existing values, so **every recalculated value in the pre-existing
sheets must be byte-identical**. Any moved value is a regression until proven
otherwise. Compare in real Excel by (sheet, row label, column) on **both** a
single-line and a multi-line fixture.

**Protocol:** one re-bless, its own commit, purity proven leaf-by-leaf with the
provenance-asserting dump before re-baselining; every changed leaf in a declared
category, zero unexplained; Cover `_CONTENTS` gains the tab and A-129 is fixed
in the same commit.

**If M6 ever lands, that is a separate and much larger re-bless** — M6's own
risk notes say the marketing numbers **will change**, which moves R31 as well.
**It must not be bundled with the tab.**

---

## Q8 — Sizing M6

Not applicable: Q2 recommends path (i), not schedule-first. If Nick overrides
that, M6 should be re-scoped against today's codebase in its own directive —
starting with M1's deferred E2E verification, which is a precondition M6 names
for itself and which no longer holds as written.

---

## Summary

**What produces the marketing percent today.** The client's own stated annual
spend (9,000 ÷ 500,000 = 1.8%) seeds the stub and Q1. **Quarters 2 through 20 —
all 19 of them — are written by the target solver optimising an EBITDA-margin
target**, ending at 1.32%. The engine stamps this itself in
`applied_by_target_solver_quarters`. The decline is not a ramp, not GPT, and not
flat dollars over growing revenue — I tested that last hypothesis and it fails,
because marketing dollars rise then fall while the percent falls throughout.

**Can the tab ship before the backend schedule?** Yes — as a derivation and
provenance sheet, not as a live driver tab. The audience math it would show is
real but **annual, GPT-estimated, and disconnected from the shipped number**:
`marketing_model_json` says 8% and 40,000 where the workbook ships 1.8% and
9,000.

**Which drivers a client can genuinely edit and have recalculate.** Exactly one:
the marketing percent itself, at Model Inputs r19 — and that already works
today. Every audience input would be inert unless the tab is wired to drive
r19, which would change the delivered plan and break the solver's convergence.

**What the tab would honestly have to leave blank.** The entire per-quarter
acquisition block — required entities, retained, new entities required, required
acquisitions, CAC per quarter. None of it is persisted anywhere. That is Q1(a),
measured, not inferred.

**The finding that outranks the tab.** Marketing is one of **28
`controller_write` levers** the solver jointly optimised. The workbook is a live
*arithmetic* model and a *frozen optimisation* — change any driver and the other
27 hold their solved values, and nothing in the workbook says so. Before
building a tab that invites editing, the product should say plainly what happens
when you edit. That is a paragraph on the Cover, and it is worth more to a buyer
than either tab.
