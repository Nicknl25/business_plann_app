# The four derived stub cells — WHY each is the way it is (research for Nick's ruling, 2026-08-17)

NOTHING BUILT. Traced to the cent against Millgate (draft 2e198cbf, run
3d4e1de9), git history, and the workbook. Weighted to ABOVE-EBITDA per
Nick. Two corrections to docs/STUB_PURITY_AND_ANNOTATIONS_RESEARCH.md
are recorded at the end.

## 1. G&A stub — ABOVE EBITDA — REAL BUG, not a design choice, not staleness

**Does intake capture a client G&A figure? YES — a dedicated stage.**
Question verbatim (`intake_consult.py:2736-2740`): "About how much goes to
other regular business bills in a typical month, besides payroll,
marketing, and rent - things like utilities, software, insurance,
accounting, phone, and internet?" → `other_operating_expense` (monthly)
→ `other_opex_absolute = ×12` (`:9420-9426`). Millgate: 2,600/mo →
**31,200/yr**; stated `current_revenue 854,000` → the client's real G&A
ratio is **0.036534**. The intake question is scoped exactly to the G&A
row's definition (excludes payroll/marketing/rent). Not a "mixed bag".

**What the stub actually holds and why: the client's own dollars ÷ the
WRONG denominator.** The `_rescaled_target("sga_percent_of_revenue")`
branch (`finmo_bridge.py:3606-3608`) is DEAD in production — it reads
`solver_input` from a payload the only caller
(`build_python_model_input_json` → `_python_model_input_template`) never
emits — so the `else:` always wins:
`_table_seed_ratio_for_lever("expenses::General & Administrative",
annual_revenue=revenue_total_year1, …)` with the mapping row's
`seed_source_paths ["financials.other_opex_absolute", …]` and
`seed_formula annual_source_value_divided_by_annual_revenue`. And
`revenue_total_year1` is NOT the client's revenue — since `513778e`
(2026-05-07, "Phase 7.1 … Site 5: finmo_bridge revenue_total_year1 —
capacity-driven for _cogs_ratio_from_financials fallback denominator")
it is `authoritative_annual_revenue` = capacity × price × periods ×
**0.95** (`structural_feasibility_check.py:101-133`). Arithmetic:
30 × 52 × 760 × 0.95 = 1,126,320; **31,200 / 1,126,320 = 0.027701 —
exact match to the persisted stub.** Applied to Q0 revenue 213,500 →
$5,914/q = **$23,657/yr vs the client's stated $31,200 (−24%)**.

**There was never a decision.** `8ab20db` (Mar 28) seeded G&A as client
dollars ÷ client revenue (correct); `513778e` retargeted the SHARED
`revenue_total_year1` for a COGS-fallback purpose and never mentions
G&A; `57a0341` bound the stub to the same variable; `27d6163` added the
(unreachable) band branch on the same variable. **The structural tell:
every other ratio row has a stub/forecast variable split (COGS
`_baseline`/`_forecast`, Marketing `_baseline`/`_forecast`, Taxes
`taxes_percent`/`tax_rate_forecast`); G&A alone has NO `_forecast` twin
— `g_and_a_ratio_baseline` is read at :3714 (stub) AND :3785 (live).**
That is why forecast-aimed changes landed in the "today" cell. The code
even asserts the opposite belief (`:3819-3821` "Stub 0 is unchanged").
Marketing escaped only because intake pre-stores
`marketing_percent_of_revenue = 8,000/854,000` computed against STATED
revenue; G&A has no stored percent (`gna_model_json` NULL).

**Staleness is NOT the issue** — correction to the prior doc: 0.027701
appears in no envelope past or present; the live fitted band is
{0.027, 0.032465, 0.03551}; a fresh rebuild today produces the same
0.027701. It is a first-build seed with the wrong divisor. Corollary:
the `marketing_ratio_baseline` UnboundLocalError cannot fire today
(the else-branch always runs); it is a LATENT trap that arms when the
rebuild path `27d6163` intended is actually built (its own body: "the
round-1 model_input expense VALUES are seeded before band-fitting").

**The app contradicts itself on the same draft:** the coherence gate's
BASIS DOCTRINE (`intake_coherence/evaluator.py:20-29`) — "G&A percent
comes from `other_opex_absolute` … Q1 revenue: stated current_revenue
first" — runs the client at **0.036534** (`_coherence.early_eval.q11`
gna 11,961.58 / revenue 327,410); the workbook Q0 says **0.027701**.
Two statements of the client's current overhead, same run.

**Verdict: PROBLEM — fix.** Not a band-policy disagreement: client
dollars over an engine denominator, misstating the client's own today
by 24%, contradicted by the app's own gate. Fix shape (not built): give
G&A its OWN stub denominator = stated `current_revenue` (like the
gate), and a `g_and_a_ratio_forecast` twin so the forecast keeps its
capacity/band basis and this class cannot recur. Blast radius: the
shared `revenue_total_year1` + a workbook-builder cell → goldens will
move → FULL apparatus with leaf-purity proof (G&A stub + descendants
only). Also worth: an S2 label — the source column says "Direct model
driver", never "you told us 31,200".

## 2. Taxes stub — BELOW EBITDA — design choice, benign, FINE
Intake never asks a tax rate (no tax stage in `financials_consultant.py:
2060-2081`); no client fact exists. Mechanism (verbatim `finmo_bridge.py:
3725-3728`): "Stub period uses the same doctrinal effective_tax_rate as
live quarters; tax_rate_forecast already cascades intake → envelope →
industry_profile → federal corporate floor." NOT a national constant:
Millgate 0.182667 = NAICS-6 323111 IRS_SOI `naics_6_direct`, high
confidence; 0.21 federal floor only when no coverage. Applies only to
positive pre-tax: engine `max(0, pre_tax) × rate` (`:2307`), workbook
`MAX(0,C16-C17-C18)*rate`; no loss carry-forward. Millgate Q0 = 0.182667
× (58,745.77 − 2,250 − 0) = 10,320 — note it inherits the G&A understate
and the zero depreciation. **Verdict: fine as-is; labelling only (S2 —
"engine assumption" column).**

## 3. Depreciation stub — BELOW EBITDA — the PARKED A1/A2 question, not new
What is actually there: a REAL cell containing 0 at every layer — model_
input `Depreciation values[0]=0.0` (never assigned; falls through to the
template zero, `:3702-3735` has no Depreciation branch), engine
`opening_ppe × 0` (`:2292, 2305`), finmo `quarter_rows[0].depreciation
0.0` beside `ppe 260,000` / `accumulated_depreciation 0`, workbook
`CapEx Depreciation!C10 = 0` hard-typed, `C11 = MIN(260000*0,260000) = 0`,
`FINMO!C18 = 0`, cash-flow addback `'=0'`. Not blank — "this business
consumes no capital" next to $260k of PPE. Client-stated alternative:
partial (`initial_assets 260,000` is asked; no rate/accumulated). **This
IS docs/NI_TRAJECTORY_RESEARCH.md F-A ("the stub is a DIFFERENT
ACCOUNTING BASIS … carries ZERO depreciation by construction", fleet-
wide 0 on all 53 sweep runs) resurfacing from the model_input side.
Nick already ruled A1 wrong and parked it. Leave parked; do not fix
piecemeal.**

## 4. Capacity stub back-solve — design choice, Nick-ruled twice, FINE
Reason verbatim (`finmo_bridge.py:3308-3318`): "The stub (Q0 intake
snapshot) must be expressed at QUARTER scale like Q1-Q20 … the Bridgeburn
workbook shipped a stub at 4x every live quarter. The client's stated
annual revenue is the one quarterly-scale anchor that survives the year1
rebuild/revert cycle, so scale stub CAPACITY to that run-rate (price and
utilization are kept; capacity absorbs the scale, mirroring the intake-
side reconciliation)." Origin `eff7521` (07-31, Bridgeburn stub at 4.02×
= $704,340 in a 0-day column; gate `assert_post_intake_stub_scale_sane`
3× threshold). Millgate: factor 13.005589 = ×13 cadence × 1.000431, and
that residual is the client's OWN inconsistency (30×52×0.72×760 =
853,632 vs stated 854,000), already stamped in `financials_year1_json.
_rescale_provenance`. Stated REVENUE wins — Nick's ruling: `6911cb8`
added a 0.5% epsilon, `f020a34` the same day REVERTED it ("reconciling
to stated revenue is by design per the ruling"). What breaks otherwise:
Q0 revenue = 16,416 (a weekly number in a quarterly column), every
%-of-revenue Q0 row, the RE plug, the coherence anchor (Q1 = stated/4),
and the stub-scale gate fires. No quarterly capacity is ever stated, so
×13 is unavoidable. **Verdict: fine; only gap is that it is written
nowhere as stub policy (code comment + two commit bodies).**

## Stub doctrine — not written down as one thing
`docs/phase_9_p3_7_q1_stub_alignment_audit.md:8-9` ("Stub = intake
snapshot … System must NOT modify it" — framed as Nick's assertion, not
a spec); `p3_33_restructure_protocol_spec.md §10.5` (Stub 0 = STRUCTURAL
facts, not the numeric column — the gap where these cells live);
`p3_40_contract_1` (shape only: 21 periods, index 0 unwritable — never
provenance); `doctrine.md:409-412` (worries about intake leaking INTO
the forecast, the reverse rule is unwritten); NI research (empirical
"different accounting basis").

## Summary for the ruling
| cell | reason stated? | client alternative? | bug / choice | verdict |
|---|---|---|---|---|
| G&A 0.027701 | NO — collateral from 513778e via shared `revenue_total_year1` | YES: 31,200/yr from a dedicated intake question → 0.036534 | **REAL BUG** (wrong denominator; no `_forecast` twin) | **FIX** — full apparatus, purity per leaf |
| Taxes 0.182667 | yes, explicit; NAICS-6 IRS-SOI; 21% floor | none (by intent) | design | fine; S2 label |
| Depreciation 0 | never assigned; real 0 cell | partial (PPE stated) | parked A1/A2 | leave parked |
| Capacity 390.17 | yes, in full + ruled twice | none quarterly | design | fine; document as stub policy |
Corrections to the prior doc: G&A stub is NOT a stale band (branch
unreachable; value = wrong divisor); the marketing UnboundLocalError is
latent, not a live crash risk. Add: a `g_and_a_ratio_forecast` twin is
the structural prevention.
