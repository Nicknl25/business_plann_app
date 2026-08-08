# HERETIC PURPOSE MAP — CW-021b (ablation evidence, not shape inference)

**Nick's stop-order standard:** for every ledger finding, the ACTUAL purpose proven by
removing it and observing the real effect on real businesses — "this does X, without it Y
happens, therefore it's [heretic / load-bearing / physics / deliberate]." Nothing in app
code was changed; every ablation is an in-memory patch in a scratch harness
(`Test Files/_ablate_*.py`) against real captured drafts.

**Test businesses:** Peachtree Post Security (f62e8460, completed run 22e3db06, judged
stamps present), Meridian Motorcars (adf1090b, the fleet flip case), doomed Glaze
(cc8b7081, known-fail), Sunny Glaze canary (29c4a053, completed with workbook), Bluff City
janitorial (demote path), plus the full NAICS baseline table for census experiments.

Verdict vocabulary: **LOAD-BEARING** (removing it breaks a real thing; keep),
**PHYSICS/PRESENTATION** (shapes realism, doesn't set outcomes), **DELIBERATE DESIGN**
(documented two-job architecture; keep), **REDUNDANT** (owner fully covers; genuine
heretic), **LATENT** (does nothing today on live paths; killable), **MIXED** (load-bearing
in one seam, heretic in another — needs a surgical ruling, not a class ruling).

---

## EXP-1 — GROWTH_FENCE_Q11 = 1.07^10  →  **DELIBERATE DESIGN + LOAD-BEARING. Ledger G1 (H-DEMOTE) WITHDRAWN.**

**Actual purpose (traced):** the fence is not a growth cap on the plan — it is the
*optimism basis* of the gate-entry verdict. `q11_revenue = q1 × growth_to_q11`: the gate
asks "does a passing configuration EXIST at the maximum authorable ramp." The judged
multiple answers a different question — "will THIS configuration hold at the ramp the
engine will actually author" — and section.py:973-1004 documents the two-tier design with
fleet evidence (7/7; judged-entry flips Meridian; Redux false-convergence is why the WALK
uses judged). Judged-pass implies fence-pass, so convergence is monotone.

**Ablation (EXP-1b, real Peachtree shape, payroll scaled ×k):**

| payroll × | fence 1.967 | judged 1.348 | flat 1.0 |
|---|---|---|---|
| ≤1.1 | PASS | PASS | PASS |
| 1.2–1.4 | PASS | PASS | **FAIL** |
| 1.5–2.0 | PASS | **FAIL** | FAIL |
| ≥2.2 | FAIL | FAIL | FAIL |

**What breaks without it:** demoting the fence to the judged multiple flips every business
in the ×1.5–2.0 band (a six-notch-wide window of real shapes) from gate-PASS to roadmap —
false negatives at intake, exactly the failure Nick predicted. Evaluating flat (removing
growth entirely) additionally fails the ×1.2–1.4 band. The fence does a job the judgment
does not cover. Residual: the already-scheduled (b2) judged-tier confirmation pass — no
new action.

## EXP-2 — mature utilization 0.85 (five sites)  →  **PHYSICS/PRESENTATION + constraint surface. NOT an orphan to rewire. Ledger U1/U2 reduced to DUP-consolidation only.**

**Proposer copy** (`deterministic_revenue_proposer.py:48`): revenue is computed FIRST from
the growth path; util/capacity are derived to reconcile ("capacity absorbs the remainder").
Ablation on real Peachtree reference: mature_util 0.50 / 0.85 / 1.00 → revenue
**byte-identical** (Q1 1,923,000; Q11 3,169,407; Q20 4,236,370). The constant never sets
the forecast level — it decomposes it into a lender-believable utilization story (at 1.0
the plan would claim 100% utilization by Q11).

**Contract copy** (`_MATURE_UTILIZATION_CAP`): shapes the enforcement ceiling — ablations:
cap 0.85 → watermark 0.85, curve 0.65→0.85 by Q11; cap 1.0 → watermark registry-clamped to
0.98, curve reaches 1.0 (implausible-but-accepted shape); cap 0.60 (below Q1 util) → curve
pinned flat at 0.65. It bounds what adaptation may author (K13 couples util growth to
rev_max); it does not move the deterministic forecast.

**Verdict:** capacity physics + plan believability; different job from any judgment. Safe
action: consolidate the drifted literals (0.85×5, 0.84×2, 0.95×2) — behavior-neutral.
A "utilization judgment seat" remains a design question, not a correction.

## EXP-5 — seam-2 sane-floor `max(converted, 0.65)` + the band-row death question  →  **MIXED: the guard's docstring case is REAL (proven live); lethality is masked by three layers; plus a NEW latent Spec-1 finding.**

**Why low-cogs businesses don't die today (traced on the real Sunny run 9a3ecbd0):**
three stacked defenses — (1) fitted walls usually cover the contract value → CW-017
demotes band breaches to advisory (Sunny's contract cogs_max 0.29 vs converted band 0.094:
advisory, run completed); (2) many service NAICS have no cogs band coverage → no
enforcement row at all; (3) post-ac5276b the converted path bypasses the raise.

**The guard's original case is live, not hypothetical:** Sunny (retail donut shop) resolves
to level-3 *food manufacturing*: cogs 0.715/0.798 with payroll share 0.701 — overlap sum
1.416, conversion fires legitimately by its own rules, yielding a materials band max
**9.4%** for a business whose honest stated materials run **29%**. Cohort-accurate,
segment-mismatched — literally the mismatched-segment pathology the sane-floor's docstring
names (donut storefront vs manufacturer). Today the fitted walls absorb it.

**NEW LATENT FINDING (my own Spec 1, flagged for the record):**
- Seam-1 and seam-2 resolve slightly different band variants (0.0939 vs 0.0966 for Sunny).
  On a hypothetical no-walls path the contract would carry round(0.0966,2)=0.10 against an
  enforcement max 0.0939+0.005=0.0989 — **rejection by 0.0011**, a coherence gap between my
  own two seams. Not reachable while band fitting succeeds; latent, mine, needs a
  same-variant fix when touched.
- **Census of the conversion surface:** 464 of 2,435 NAICS rows are conversion-eligible
  (cogs+payroll sum > 1.0), spread across 22 sectors; **98 sit within 5% of the 1.0
  knife-edge**, where the overlap "proof" is marginal. Live firing additionally requires
  capacity_driver=labor, but the eligible surface is broad. Spec 1's `sum > 1.0` boundary,
  the `adj_max < 0.02` collapse threshold, and the walls+CW-017 backstops are what stand
  between a knife-edge cohort and a manufactured band. Any ruling on the sane-floor must
  keep a mismatched-segment defense in place for exactly the Sunny shape.

## Registry cogs floors (min 0.2 / 0.05) — **already proven by the live cycle, not re-run:**
red (Peachtree died at round 1 on the floor) → provenance-gated yield → green →
**the same draft completed to a workbook with honest 7.0–7.7% COGS in every quarter.**
Purpose: garbage-low protection, correct for labor-inclusive bands; wrong for converted
materials bands; the shipped fix (floors yield to the owner, negative control both
directions) is the settled treatment. KEPT as-is.

---

# BATCH A — coherence verdict layer (ablated on Peachtree / Meridian Family Law / doomed Glaze)

*(Correction to the skeleton above: draft adf1090b is "Meridian Family Law E2E23", not
Motorcars.)* Probe fact shaping everything: Glaze's real margin band is PARTIAL — q11
band authored, gross_margin/burden/ni floors all None — so the per-field fallbacks are
live on a real draft, not hypothetically.

| finding | purpose (traced) | ablation result (measured) | verdict |
|---|---|---|---|
| A1 evaluator fallback four (0.20/0.65/0.02/0.0) | per-FIELD fill-ins — each applies whenever ITS judged field is absent, not only when the whole band is missing | zero verdict flips on all three drafts (band vs None); but on Glaze 3 of 4 fallbacks ARE the live thresholds, and FALLBACK_NI_FLOOR=0.02 authors the client-facing gap figure ($60,757.56 = the ni shortfall) and selects which failing checks exist | **LOAD-BEARING as stand-ins on partial bands** (real occurrence); keep; the real question is upstream — why the band author may omit floors (V5 precedence flag stands) |
| A2 depreciation = capex × 5%/q | advisory NI shading, ni_floor check only | no flip at rate 0.0 / 0.05 / 0.10 on any draft; flip requires $1.5M–$37M capex vs $0–$185k stated | **NEAR-INERT**; cosmetic; safe to leave or derive later |
| A3 the 50% GM default for unauthored new lines | stand-in for an unauthored executive judgment in the corner + lever closure + client wording | Glaze: cannot flip (new lines strictly value-destroying there). Marginal-Meridian (real shape, +$560k payroll): **the default ALONE decided walk-vs-roadmap** (corner PASS at 0.5, FAIL at authored 0.25 — blended GM 0.905 vs judged 0.90 floor) | **GENUINE HERETIC with teeth**: an unauthored judgment that decides verdicts and is narrated to the client as fact ("at 50% margin"). The one Batch-A item that warrants a fix ruling |
| A4 mid-tier price ×0.5 + recommended=True | UX quantization of judged pmax; the recommended flag is the anchor brief-agreement routing ("yes, do that") resolves to | removal: options 2→1, no recommended option, router contract loses its target; zero verdict math involved | **LOAD-BEARING for conversation routing**, product-design seat, not a judgment |
| A5 custom-price lower clamp | the only guard against silent price-lowering | Glaze: wanted $1.50 → silently held at $2.00 (no message discloses the refusal); clamp removed → gap widens +$381.75/q and the walk's lever math (multipliers ≥1) is outside its model | **LOAD-BEARING** (walk math assumes ≥1 multipliers); the honest gap is DISCLOSURE, not the clamp. **NEW BUG (side-finding, pre-existing): `_apply_price_spec` matches `lob`/`product` keys but live ops uses `lob_name`/`product_name` — even legal custom prices never land on per-product `unit_price`; only the flat single-product field and the revenue anchor move. Multi-product drafts get anchor-moved with no price landing** |
| A6 $0.50 gap epsilon | ack + round-advance trigger | smallest real gap move ever observed across 55 coherence drafts: $74.68/q — no real behavior has ever depended on the constant's value; no data at its scale | **INERT at observed scales**; leave |

# BATCH C — cash/debt/payroll (ablated on the real Peachtree run: preserve_cash, debt-funding, $520k cash, judged buffer 2.0mo/ceiling 4.0mo)

| finding | purpose (traced) | ablation result (measured) | verdict |
|---|---|---|---|
| C1 cash `min(judged, policy, balanced)` | the HARD crash/paydown floor is the MINIMUM of the three — a relaxation wall: the judgment may relax the hard floor, never tighten it | the balanced-row 1.5mo is the number that governed; at 1.5 the shipped plan clears every quarter (Q1 headroom **+$5,111**); judgment-alone (2.0mo) manufactures Q1 −$251,867 and Q2 −$23,090 funding gaps → forced debt draws / crash-gate failure on a healthy debt-free plan | **LOAD-BEARING — LEDGER K1 (H-DEMOTE priority) WITHDRAWN.** The min() is deliberate: judged-rich buffers must not convert healthy plans into forced borrowing. The revolver-paydown copy was dormant here (no debt) but is the same wall |
| C2 burden ×1.22 | loads every wage row; all 80 Peachtree rows carry 0.22 | 20q payroll: $27.5M at 1.0 / $33.6M at 1.22 (matches shipped) / $37.2M at 1.35 — ±$3.6–6.1M swing. The coherence-side 1.0: flows ONLY into the favorable-corner basis (main gate checks use stated payroll, unloaded — a deliberate stated-fact basis); measured at 1.22 the gate erodes ~11 EBITDA points but does NOT flip on Peachtree; corner never executed on this run | **LOAD-BEARING in the engine; the 1.0-vs-1.22 "conflict" is a deliberate basis choice, LATENT divergence only for thin-margin corner cases** — a narrow, real review item, not the bug I ledgered |
| C3 wage positioning multipliers (1.0–2.5×) | GPT-choosable tier per business; Python seeds floor/1.0 | 40/40 recent drafts: `('floor', 1.0)` — **GPT has never once deviated**; key-person rows hardcode 1.0; supporting rows apply max(1.0, m) = identity | **LIVE-BUT-INERT** — guards a premium-wage business no run has produced; not the "biggest wage heresy" I called it |
| C4 min wage $25k / inflation 3%/yr / benchmark ratio 0.75 | wage-row physics | $25k: dormant on Peachtree (lowest wage $34,150) but the ONLY backstop when OEWS p10 is missing; inflation: fires on EVERY role (exactly ×1.03/yr; 20q payroll ±6.3%/+6.7% at 0/6%); benchmark ratio: **DEAD in application code** — consumed nowhere, its only live role is passing its own validity check (can break runs without pricing a wage) | $25k **KEEP** (last-resort backstop); 3% **ORPHAN-declared** (fires universally; a macro assumption worth documenting); ratio 0.75 **DEAD — killable** |
| C5 industry_profile shadow authority | — | **DEAD, proven at runtime**: `cash_buffer_months_for_strategy` has zero call sites; every live importer discards the profile or reads only bands/tax-rate; all four constants poisoned to 999 → nothing downstream changes; run traces show `industry_profile_present=False` | **DEAD as authority — H-KILL confirmed by evidence** (the module's one live job is effective_tax_rate) |
| C6 surplus split weights | default split policy; the binary judgment is a one-bit override wall (deleverage_first) + the judged ceiling is the distribution TRIGGER (first distribution lands the exact quarter cash reaches 4.0mo — headroom $0) | on a debt-free run every weight setting collapses to the same outcome (spillover routes surplus back to distributions); weights selected but not load-bearing here | **DELIBERATE POLICY MAPPING of the client's own strategy choice; judgment owns the trigger and the one-bit wall** — as designed |

# BATCH B — acceptance/realism/viability (ablated on real completed runs: Peachtree + both Sunny canaries)

| finding | purpose (traced) | ablation result (measured) | verdict |
|---|---|---|---|
| B1 revenue-flat 0.02 CV / 0.05 delta | acceptance canary on Q1-Q10 | Peachtree cv 0.086 / delta 0.263, Sunny 0.073 / 0.214 — clear by 3–5×; failure boundary computed: any plan under **~0.544%/q (~2.2%/yr)** hard-fails. **The real anti-flat device is elsewhere**: rev_target is a HARD MINIMUM the quarter-grid raises levers to meet ([contracts/runner.py:2190](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2190)) — growth is constructed before the gate ever looks | **DIFFERENT JOB — a ramp-bypass tripwire wearing a business threshold.** Residual conflict is real: an honest judged sub-2.2%/yr mature plan would be killed by the canary (Sunny's qoq_end is only 1.36× the boundary) |
| B2 balance-sheet ratio 5.0 | only check on BS stock LEVELS (surplus-distribution deadness detector) | real ratios 1.34 / 1.02 worst-case; no flip at 2.0 or 10.0 | **SOLE-GUARD, dormant-with-slack**; keep |
| B3 NI delta 0.02 / flat floor 0.02 | acceptance NI trajectory, ramp-OR-flat arms | both runs pass on the FLAT arm using the JUDGED floor (0.03/0.04 — `flat_floor_source=executive_margin_band_judgment`); the constant is never read when judged; no ablation flips | **already demoted-when-judged (Wave 2 landed here)** — ledger M8 overstated; note this check is the judged NI floor's ONLY enforcement point in the whole pipeline |
| B4 realism formula five | universal viability rows; ALSO called judgment-blind from restoration_loop (`model_input_json={}`) | stripping the judgment FAILS Peachtree q20_holds (−0.0152) — the judgment is load-bearing FOR the pass; GM floor + burden max fully dormant-when-judged; retention 0.5 binds both modes (collapse detector). **NEW BUG: [formulas.py:1057](../python/client_intake_and_finmo/post_intake_realism/formulas.py#L1057) reads `q11_ebitda_band` but the stamp's key is `q11` — the CW-017 E13 judged override is DEAD CODE; the 2pp constant still binds in judged mode (proven: Sunny judged flip at 0.3)** | fallbacks behave; **one key-mismatch bug to fix; restoration_loop's judgment-blindness is a real seam** |
| B5 viability PASS_REFINE 0.55 | tier-1 pass/refine split, attached ADVISORY-only at acceptance | offline rerun exact-matches stored verdicts; 0.45/0.55/0.65 all → refine. **tier1 has NEVER been a number on any real run**: drafts lack `business_naics_6` (cohort bands unresolved) AND the adapter's start-date parse fails on MySQL datetimes (stage defaults startup) | **INERT TWICE OVER + two wiring bugs** — the entire viability-package ruling question is moot until naics/date wiring is fixed; nothing to demote today |
| B6 planning-mode floors + max(judged, policy) | realism band lower-edge raiser | Peachtree: the COHORT band low (0.1004) bound — neither floor; Sunny: the JUDGED floor bound (0.08−0.07 tolerance); policy floor 0.0 in both; NO value in the table's entire −0.40…0.12 range flips either run | **policy floors subordinate-by-construction (max can only add strictness) and non-binding on real runs — ledger M6 downgraded to note.** Real gap: judged NI floor is not wired into the validator at all (only the B3 gate check enforces it) |
| B7 restructure _TARGET_LADDER | solve targets, fires only after failed acceptance (30 stored solves) | REAL TRACES: EBITDA rungs already subordinated both directions ("ebitda floor governed by executive band: q11 0.08"; rung-2 0.11 clamped DOWN to judged target 0.085). **NI rungs ignore the judgment in the target (draft a051f479 solved toward NI 0.03 against judged floor 0.04) AND in the verify (fast_evaluator.py:125 omits model_input_json → NI verified against the 2pp constant)** | **SPLIT: EBITDA half compliant (constants are judgment-absent seeds — ledger M5 half-wrong); NI half is live unsanctioned authority (ledger M5 half-right, Wave 2 gap now trace-proven)** |

---

# SCOREBOARD — ledger proposals vs measured reality

**Overturned by measurement (proposals withdrawn):** G1 fence (deliberate two-tier + load-bearing window ×1.5–2.0); U1/U2 utilization (physics/presentation; revenue byte-identical); K1 cash min() (load-bearing by +$5,111 — judgment-alone forces Q1–Q2 debt draws on a healthy plan); P2 wage positioning multipliers (live-but-inert, 40/40 runs at floor/1.0); P1 burden 1.0-vs-1.22 (deliberate stated-fact basis; latent for thin margins only); M6 policy floors (subordinate via max, non-binding); M8 NI flat floor (already dormant-when-judged); G7 flatness (a ramp-bypass canary — though the sub-2.2%/yr conflict with honest judged growth is real and stands).

**Confirmed by measurement:** M3/C5 industry_profile shadow authority (DEAD at runtime, poison-proven) — killable; A3 the 50% GM default (ALONE decides walk-vs-roadmap on a marginal real shape, and is narrated to clients as fact) — the one verdict-layer heretic with teeth; B7 NI rungs (solve + verify both judgment-blind, stored-trace proof); G5 spike ×1.3 and L2 debt-service factor and C4 benchmark ratio 0.75 (dead code, one of which can break runs via its own validity check).

**NEW bugs found BY the ablations (none shipped, all documented):** (1) `_apply_price_spec` key mismatch — custom prices never land on per-product ops fields; (2) `formulas.py:1057` `q11_ebitda_band` vs `q11` — E13 judged override dead; (3) viability tier1 never scored (missing naics + date-parse failure); (4) my Spec-1 seam-1/seam-2 band-variant mismatch (rejection-by-0.0011 on the no-walls path) + the 464-NAICS / 98-knife-edge conversion surface.

**Load-bearing constants proven (do not touch):** the fence; the cash min(); burden ×1.22; the evaluator fallback four (author the gap figure on real partial bands); the custom-price lower clamp (walk math assumes multipliers ≥1 — the honest fix is disclosure, not removal); min wage $25k (sole p10-absent backstop); retention 0.5 (collapse detector); BS ratio 5.0 (sole stock-level guard).
