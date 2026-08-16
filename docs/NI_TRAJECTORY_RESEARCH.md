# Net-income trajectory research — Nine Fathom (draft 6d2823db, run 10a81085)


> **CORRECTION 2026-08-16 (see docs/FAILED_ACCEPTANCE_DELIVERY_RESEARCH.md):**
> this note's claim that Nine Fathom PASSED the acceptance gate on the
> flat-healthy branch is WRONG. It read the code default (2pp) and the
> in-loop cascade's behaviour. The PERSISTED verdict for run 10a81085 is
> `passed=false`, `failed_checks=['net_income_trajectory_viable']` — Q11
> NI margin 0.0404 against the EXECUTIVE floor 0.08
> (`flat_floor_source=executive_margin_band_judgment`, wired 2026-07-22).
> The trajectory numbers and the stub-basis finding stand; the pass/fail
> claim and the "escape hatch" framing are retracted. Nick has parked the
> stub question (the stub is the client's real state; A1 is wrong).

Status: RESEARCH for Nick's ruling (2026-08-15). Nothing built. When it
becomes a fix it is engine / acceptance-gate / golden-floor territory —
FULL APPARATUS (canary + full prove + golden re-bless where the stub
changes).

## The headline finding — the stub is a DIFFERENT ACCOUNTING BASIS

"NI below the stub in all 20 quarters" is real as a number and mostly
NOT real as a business fact. The stub row is not quarter 0 of the
forecast; it is a separate as-stated snapshot built by
`_build_operating_stub_metrics` (`finmo_bridge.py:2257-2305`) that:

- **carries ZERO depreciation by construction** — its Depreciation ratio
  slot is hard-zeroed on the seed path (`finmo_bridge.py:3735-3736`), the
  `intake_stub_value` override chain has no Depreciation branch
  (`:3684-3715`), and the capex runtime deliberately preserves the stub
  slot while writing only live quarters (`:2136-2139`);
- **charges interest at the client's stated rate**, while Q1..Q20 use the
  SBA/baseline rate (`:3699-3704` vs `:3734`, `:3769`) — Nine Fathom
  5.42%/yr at the stub vs 9.99%/yr in the forecast (1.84×).

Q1 simultaneously loads the full opening-PPE straight-line vintage
(`finmo_bridge.py:1744-1752`, `placed_quarter: 0`, no phase-in: 240,000 /
20 = 12,000/q → 12,067 with maintenance capex) and switches the interest
basis. **Restate the stub on the Q1 basis** (charge the same 12,067
depreciation, apply the forecast rate 118,000 × 0.024975 = 2,947, same
23.4% tax): 25,576 − 2,947 − 12,067 = 10,562 pre-tax → NI ≈ **8,091
(3.04%)**. **Actual Q1 NI = 8,119 (3.05%).** Same business to within 0.3%.

The like-for-like row is EBITDA: **25,576 (stub) → 25,901 (Q1) → 34,001
(Q20)** — it rises, monotonically after Q3.

**The forecast itself RISES**, it does not decline: NI margin 3.05% (Q1)
→ 4.04% (Q11) → 4.53% (Q20); NI dollars 8,119 → 15,338 (+89%). Payroll
is the only fixed block that grows (~tracks revenue); lease is flat
(12,600 every quarter), opening-PPE depreciation is flat (~12,000/q),
interest amortizes away (3,235 → 924) — pure operating leverage,
roughly +0.08pp NI margin per quarter.

The sweep confirms this is structural, not Nine Fathom-specific:
`Test Files/_research_ni_trajectory_sweep.py` over 53 completed runs
since 08-01 — **stub depreciation = 0 on EVERY run**, and **every run's
Q1→Q20 NI trend is UP**. Businesses "below stub ≥15/20 quarters with Q20
margin < stub margin": Nine Fathom and Sunny Glaze (the canary — stub
21.5% → Q1 1.5% → Q20 9.4%, and its Q1 depreciation is only 1,006 /
interest 40, so for Sunny the basis gap is OTHER cost blocks the stub
omits — open sub-question). Kestrelbrook, Thornfield, Alderfen,
Thistledown, Ravenwood, Fernhill, Wren Hollow, Sparrow: not in the
pattern; Anderson & Blake and Fetch & Fluff below stub 7/20 with rising
margins.

## What IS genuinely marginal — and it is not the executive

1. **The slope is slow because judged growth is the same for everyone.**
   The per-quarter revenue path is written by ONE function
   (`deterministic_revenue_proposer.py:97-199`, linear taper qoq_start →
   qoq_end, clamp 0.07), and the rates are the intake coherence gate's
   `judged_growth` stamp reused verbatim (`post_intake_initial_grid/
   runner.py:1624-1636`, "trust the stamp"). Nine Fathom (coffee
   roaster) and Kestrelbrook (garden centre) received the BYTE-IDENTICAL
   judgment: `qoq_start 0.019427 / qoq_end 0.007417` = 8%/yr → 3%/yr.
   Against a large day-one fixed step, ~1.28%/q buys ~0.08pp/q of
   margin. Whether that judgment is really per-business or a default in
   disguise is the real question behind "revenue too timid" — and if it
   is a constant, it is a heuristic by another name.
2. **The gate is a single NI waypoint with an escape hatch — confirmed.**
   Intake coherence: "one arithmetic core answers one question at the
   Q11 mature state" (`evaluator.py:3`, `GROWTH_FENCE_Q11 = 1.07**10`
   `:59`); five inequalities all at Q11 (`:163-247`). Post-intake
   acceptance: the ONLY NI check is `_check_net_income_trajectory_viable`
   (`post_intake_acceptance/gate.py:461-528`) — pass if Q11 margin ≥ 0
   AND Q11 − Q5 ≥ 2pp (ramping) **OR** Q11 margin ≥ floor (flat-healthy,
   `:517`; floor 2pp unless judged). Nine Fathom Q11 = 4.04% → passes on
   flat-healthy, no ramp required. Viability gates are EBITDA-only
   (`post_intake_viability/gates.py:69-131`). A terminal value AND an
   OLS slope already exist in `grade.py:151-197` but are explicitly
   NON-gating ("a GRADE, not a viability verdict"; `gate.py:1015-1033`
   "ADVISORY … does NOT gate passed"). **Nothing compares any forecast
   quarter to the stub. Nothing tests NI slope over Q1→Q20. Nothing
   requires mature margin ≥ starting margin.**
3. **The "single-waypoint viability" issue is NOT on the registry.** No
   issue signature matches waypoint / slope / terminal / Q11-only; the
   nearest written statement is `docs/architecture/
   fix_1_early_quarter_viability_scope.md:280-300` (Option B, a
   steady-state test framed as an alternative design), and
   `docs/phase_9_realism_audit.md:180-185`.

## The Kestrelbrook contrast — corrected

The executive RESTRUCTURE stage never ran on EITHER draft: it fires only
on `not acceptance_verdict["passed"]` (`intake_consult.py:14720`), both
passed, both landed cascade tier 0, `plan_confidence =
high_no_adaptation`, identical judged growth, nearly identical mature
margin (4.30% vs 4.04% at Q11; 4.57% vs 4.53% at Q20). The difference is
what the IN-LOOP cascade found binding: Kestrelbrook's as-stated G&A was
25.3% of revenue (stub EBITDA −83,876), `net_income_trajectory_viable`
failed by 15.4pp, seven rounds ran, and the deterministic floor relaxed
the G&A bound 0.23 → 0.068 (`post_intake_restructuring_log` id 12316) —
a fix to a broken STATED cost, which is what flipped Q1 EBITDA to
+81,416. Nine Fathom's structure cleared every in-loop check (worst
distance 0.000000) so nothing engaged. Same machinery, one broken input,
one healthy input — not two executive decisions.

## Findings for Nick's ruling

F-A **Not a declining plan; a mislabeled comparison.** The delivered
    plan's Q1→Q20 NI rises 89%. The client-facing defect is that the
    stub reads as a healthier quarter than any forecast quarter because
    it is on a pre-depreciation / stated-interest basis with no label —
    a reader (Nick did) concludes the plan makes the business less
    profitable. That is a false claim BY PRESENTATION in a delivered
    plan → deal-breaker class under the triage law.
    FIX OPTIONS (Nick rules): (A1) restate the stub on the forecast
    basis — charge opening-PPE straight-line depreciation and the
    forecast interest rate at the stub, so stub vs Q1 is like-for-like
    (touches the stub builder in finmo_bridge = golden floor → FULL
    apparatus + goldens re-blessed with a purity proof, the R31 drift
    protocol); or (A2) keep the stub as-stated and LABEL it in the
    workbook ("as-stated snapshot, before depreciation and financing")
    with a like-for-like EBITDA line as the honest comparator
    (presentation-only, spot-check). A1 is more honest for the reader;
    A2 is cheap. Recommendation: A1, because every downstream "vs stub"
    reading (Cowork's, the operator's, a client's) is silently wrong
    today.
F-B **Add SHAPE checks to the acceptance gate — after F-A.** Promote what
    already exists from advisory to gating and add the missing
    comparisons: (i) NI-margin slope over Q1→Q20 non-negative (the OLS
    slope in grade.py:163-197); (ii) mature margin (Q11 and Q20) ≥ the
    RESTATED stub margin — the plan must at least hold the business's
    like-for-like starting profitability; (iii) terminal steady-state
    margin ≥ the judged mature band floor (grade.py:151 terminal value).
    Sequence matters: (ii) is meaningless against today's stub — F-A
    first, then F-B judged against the restated stub. Blast radius:
    verdict path shared by every plan → the canary WILL move (Sunny
    Glaze is in the pattern) → FULL apparatus, and expect verdict flips
    on some fixtures — those flips must be adjudicated, not auto-blessed.
F-C **Judged growth identical across businesses — investigate.** If
    8%/yr → 3%/yr is what the growth judgment returns for a coffee
    roaster AND a garden centre, either the judge is defaulting or the
    inputs don't differentiate. Separate research item (intake
    coherence growth judgment; spot-check research, no code). This is
    the real "revenue too timid" root if it is a constant in disguise.
F-D **Sunny Glaze sub-question.** Its 21.5% → 1.5% Q1 drop is not
    depreciation/interest; identify which cost blocks the stub omits vs
    Q1 (payroll floor / essentials / marketing?) — extends F-A's scope
    if the stub omits more than depreciation.
F-E **Register the gap.** File the single-waypoint issue in the registry
    (verdict class) so it is tracked; it was on the board in
    conversation only.

Nothing built. Awaiting Nick's ruling on A1 vs A2, and go/no-go on F-B
(full apparatus) and F-C.
