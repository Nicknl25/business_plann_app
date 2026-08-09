# INTAKE LIVE-TRUTH ARCHITECTURE — research synthesis (NO BUILD)

**Nick's principle:** the intake side is one set of live numbers that coherence reasons on,
the client sees, and the backend builds — always identical, instantly, on every change.
Four rules: (1) coherence knows every wall and has every lever; (2) one source of truth per
number; (3) any change recomputes everything downstream; (4) every surface reads the live
value. Four research tracks (engine walls, number residency, recompute/display flow,
coherence levers) ran to ground; full evidence in the session transcripts. Engine frozen
throughout.

## 1. CURRENT STATE — four recompute regimes living in one intake

| Regime | Covers | Semantics |
|---|---|---|
| TRUE spreadsheet (every turn) | ops → financials_year1 → current_revenue echo → COGS/marketing percents, opex ×12 | The target semantics already exist here — `assemble_financials_year1` + the sync tail run at the top of every turn |
| Hand-listed sync tail | the financials field families | One fixed-order pass, families enumerated by hand; adding a number means remembering to add its family |
| Chokepoint-only | the PAYROLL sub-graph | Recomputed only at: stage autofill (once ever, guarded by `current_payroll is not None`), the owner-pay writer, and the gate's owner-staleness check. **Nothing else ever recomputes it** |
| Completion-attempt-only | the coherence verdict layer | `eval`/gap/options stamped at gate entries; the panel reads stored stamps between them |

**The model family (what everything should look like):** `other_operating_expense` →
`other_opex_absolute` — one declared basis, one one-way deriver run every turn, the derived
twin unreachable by any patch path. **Two dead propagation primitives already in the tree:**
`propagate_shared_facts` (a generic cross-section propagator, imported and never called)
and `_refresh_shared_forecast_context`.

## 2. NEW BLOCKER-CLASS FINDINGS (found by this research, not yet fixed)

1. **`payroll_adjustment` never reaches the engine.** The walk's payroll lever writes a
   delta; the gate adds it back; **zero post-intake readers exist**. Every walk-approved
   payroll change converges the gate on a number the engine will never build —
   "converged on one, built on another" *by construction*. (CW-023's sibling, live now.)
2. **Blocked completion turns persist only `financials_json`** — same-turn walk-applied
   ops price changes, the rebuilt year1, and the owner people-row materialization are
   DROPPED; next turn rebuilds from old ops and rescales capacity to the new anchor — a
   price increase silently becomes a volume increase.
3. **Non-owner wage corrections recompute nothing** (CW-023 fixed the owner row only).
   Three layers then hold three payrolls: gate on stale baseline, FINMO on stale
   `payroll_total_year1`, headcount build on the corrected wage directly.
4. **The band/bounds/corner identity digest excludes `financials_json` entirely** — the
   walk invites corrections (4 of 6 disputable fields are financials numbers) that can
   never invalidate the artifacts judged from them. Plus: roadmap status is a permanent
   latch despite its own wording promising re-runs; `corner` is write-once.
5. Stated COGS dollars are not durable (ratio-primary + every-turn re-derive restates the
   client's number invisibly); five ops-implied-revenue formulas drift (can manufacture
   the ×4.33 fingerprint the clarifier then asks the client about); marketing baselines
   copy-once-then-stale; `financials_year1_json` stale on several persist paths; walk
   option patches replay stale precomputed dollars.

## 3. THE WALL TABLE (rule 1) — summary

Full table in the research. The gate today is a pure Q11 P&L checker: five inequalities
(GM floor, burden max, EBITDA≥0, band low, NI floor) + fence/judged growth + cost floors +
price ceilings + the new anchor/capacity holds. **Blind walls ranked by client-hit
likelihood:**

1. **Payroll % of revenue policy tier (0.16–0.70 for "high")** — proven live twice
   (Sparrow ×3 runs at 0.72; Peachtree). Labor-heavy services legitimately run 70–85%;
   the wall fires in the payload BUILDER whose exceptions bypass the GPT retry loop —
   deterministic refusal. The gate already computes the exact ratio as a fact; the wall
   is one comparison away.
2. **Q1 roster ±30% of stated payroll** — one GPT roster-duplication away for any
   owner-operator.
3. **Cash/debt acceptance walls** (interest ≤5% of revenue or coverage ≥1.5; cash never
   negative; loss window funded through Q5) — funding/debt excluded from the gate BY
   DESIGN; a debt-financed or thin-cash client converges at intake and dies at acceptance.
   Needs a doctrine ruling, not just plumbing.
4. Stub-scale 3× and basis walls (partially mitigated by anchor-vs-ops).
5. Stage-ramp cost maxes/posture (shielded by the Python-first builder; exposed on GPT
   cascade tiers). Asymmetry to fix: the registry CLAMPS on the Python path but REJECTS
   the same value on the GPT path.
6. NAICS no-coverage family — the only walls fully predictable in the room from NAICS
   alone; rare codes.
7. Machinery walls (A=L+E, contracts, horizons) — engine-bug class, not client-steerable.

**Lever gaps (rule 1's other half):** the corner check SPENDS walls the walk cannot offer —
volume headroom (`volume_multiplier_max`, authored+railed) and COGS floors route clients
into walks that have no volume or COGS round. Both are pure arithmetic to lift (the
projection math exists in the corner's own basis). Authored-but-consumed-by-nothing:
`team.max_annual_payroll` + `structure_at_min`, per-line `can_drop` + `gross_margin_pct`
(mix), the bounds' own growth block, rent `max`/rationale. Doctrine-fenced: debt/capex.
The wall-awareness seam is clean: `Thresholds`/checks dict is a single choke point, and
payroll-share is ALREADY measured on the gate's own basis.

## 4. OPTIONS

**A. Keep extending the sync tail** (add payroll family, more hand-wired heals).
Rejected: the hand-listed family pattern IS the disease — every bug in this campaign was a
family someone forgot.

**B. THE RECALC — one canonical derive-everything pass (recommended).**
A single dependency-ordered function: people (+rest-of-team) → payroll rollup (all fields,
basis rows, mirror); ops → year1 → revenue anchor → COGS/marketing/opex families; every
derived value written ONLY here; run at the end of EVERY turn regardless of focus, at gate
entry, and before EVERY persist; one persist helper that always writes all touched
sections (kills the blocked-response hole). Derived fields become unpatchable everywhere
else (the opex model generalized). This is not a new engine — it is promoting the
already-existing every-turn revenue sub-graph + `_compute_payroll_baseline` + the family
syncs into one ordered pass with a single entry point. The dependency set is small and
static; a fixed topological order suffices — no graph framework needed.
- Blast radius: intake_consult turn tails + persist sites (5 gate sites, ~6 append sites),
  section.py patch appliers; behavior-neutral for already-coherent drafts.
- Kills findings 1 (adjustment folded into the rollup the engine reads — or retired),
  2 (single persist), 3 (recompute regardless of which role changed), 5's staleness
  (single formula for ops-implied revenue, one basis rule per family — the COGS
  dollars-vs-ratio and marketing asymmetry decisions surface explicitly for ruling).

**C. Full declarative dependency-graph engine.** Cleanest theory; biggest rebuild;
overkill — B achieves spreadsheet semantics with a fixed order because the graph is
static and shallow.

**D. Live-SQL/computed views.** Wrong fit — state lives in JSON documents and the
derivations are Python (rollup proration, rescale, judgment interplay).

**Walls-as-data (with B, any option):** a declarative intake-visible wall table
(name, formula over the gate's basis, bound, source policy) consumed by
`evaluate_structural` as additional checks + by the rounds as steering bounds. Payroll-
share first (the ratio is already measured; the wall is one row). Cash/debt walls enter
only after Nick rules on the funding-out-of-gate doctrine. Engine stays frozen — the
table MIRRORS engine policy; a consistency tripwire (compare table vs policy values at
startup) keeps them honest without coupling.

**Display (rule 4):** with B running every turn, the coherence deterministic eval is
cheap to refresh every turn (judgments cached; arithmetic only) — the panel stamps stop
being gate-only snapshots. Chat stays transcript-semantics (numbers true at utterance);
receipts already live-computed.

## 5. RECOMMENDED SEQUENCE

1. **The Recalc core + single-persist** — the class-killer. Includes retiring
   `payroll_adjustment` into the rollup (or wiring it — ruling: fold, since the walk's
   delta should just BE the new people/rest-of-team truth per one-door doctrine).
2. **Invalidation honesty**: identity digest gains the financials-derived basis;
   roadmap latch replaced with re-evaluation (its own wording already promises this);
   `corner` re-runs when bounds inputs change.
3. **Walls table v1**: payroll-share tier wall into Thresholds + binding_constraint
   narration + a costs/pricing round that can steer it (raise revenue / restructure team
   pairing needs the bounds author's `structure_at_min` made machine-usable — small
   authored extension, intake-side).
4. **Lever lifts**: `_volume_round` + COGS move (walls already authored; arithmetic
   exists in the corner). This also finally gives the F&F "another dog or two" client
   their lever.
5. **Display refresh** (every-turn eval restamp + panel flat/stale markers) + the
   stage-ramp clamp/reject asymmetry flag to the engine-freeze queue.
6. Cash/debt wall disclosure — held for Nick's doctrine ruling.

Verification discipline per phase: engine-read field assertions + rebuilt-plan (workbook)
checks, per the CW-023 lesson — never transcript-level only.
