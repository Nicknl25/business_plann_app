# CW-022 — THE FETCH & FLUFF FALSE PASS: unified research (NO BUILD)

**Nick's root framing, confirmed at every layer by six research tracks:** the app does
ARITHMETIC, not REASONING — levers move numbers with no model of what the numbers mean.
The client told the system everything it needed, three times, in plain language — msg 25
(demand truth: "my people are on fixed incomes… I'd rather fit in another dog than raise
prices"), msg 65 (cost composition: "insurance $350, fuel $500, van maintenance $250,
licensing $40…"), msg 111 (a clear three-part instruction) — and the machinery could not
consume any of it. Draft 50658fff; all numbers below reproduced offline to the displayed
cent; scratch evidence in `Test Files/_research_*.py`; app code untouched.

## THE CAUSAL CHAIN (every link now traced)

1. **Turn 96 — fence-tier PASS on honest facts.** First-capture facts were correct
   (reconstruction matches stored eval to the cent). Fence ×1.967 diluted her fixed costs
   from 84.5% of revenue to 60.4% → PASS with 1.6pp headroom. **The judged-tier FAIL
   ($1,650/q short) was computed on the same stack and discarded** (`use_judged` requires
   WALKING or fence-fail; section.py:1008-1012). Flat basis: NI −10.1% — the arithmetic
   she did herself at turn 97. Verdict wording: chat suffix says "stress test, not a
   forecast" but gives no today's-scale number; **the panel says "a typical mature
   quarter keeps…" — the CW-003 framing fix never reached CoherencePanel.tsx:78-99.**
2. **Turn 97-110 — the ungrounded disclaimer.** Post-completion chat is served by the
   intent router's `answer_readonly` with the raw `_coherence` blob and ZERO doctrine
   (the coherence prompt block injects only while a walk round is live). GPT saw an
   unexplained $6,354 and invented a provenance ("separate, internal stress test…
   idealized") — disavowing the very verdict that unlocked Submit.
3. **Turn 111-112 — the capture corruption.** "Price $80, keep 21/week, pay $3,300/mo"
   hit `_reconcile_driver_correction`'s empty-changed-products landing: the dollar-target
   filter is SHAPE-ONLY, so her PRICE ($80) qualified as a count and her PAY ($3,300) as
   an annual revenue target; the coincidence fingerprint 80 × $60 × 0.70 = $3,360 vs
   $3,300 = **1.82%, inside the 2% tolerance** ("unrelated financial answers never
   match" — counterexampled). Wrote capacity=1.54/period, propagated
   `current_revenue = $3,350`. The prose-claim guard is **bypassed whenever a driver note
   landed** — the spurious landing vouched for the turn.
4. **The walk opened on a fictional gap** ($12,656/q — arithmetic on garbage), and the
   bounds were **authored on the corrupted state** (rationale: "current quarterly revenue
   ~$838"). **Counterfactual, computed: with a clean capture of her real corrections
   ($80, 21/wk, $3,300 pay), ALL THREE TIERS PASS with no gap at all ($87,360 clears
   every check, EBITDA 33-40%). The entire walk, the 40% price hike she accepted, and the
   $122,304 plan were artifacts of the corruption.**
5. **Cost round — insurance proposed for cutting.** The lever sees four aggregate
   scalars; insurance/fuel/maintenance are invisible inside `gna_pct`. Percent floor ×
   corrupt revenue = "gna from $17,400 to $603" ("gna" leaked verbatim to client text),
   and the maximal-cut bundle is **hardcoded `recommended=True`**
   (controller.py:418). The bounds author actually KNEW insurance was inside — its
   attestation names it — flattened into `0.18` with the rationale truncated by a
   500-char cap. Her "I'd be driving uninsured" never landed as a floor assertion
   (multi-intent turn; `client_floors: None` in final state).
6. **Pricing round — the multiplier ratchet + closes-$0.** The author judged "$108 max
   ($75-110 band)" at price $60, stored as ratio 1.8 with NO reference price; re-based on
   the client's later $80 → offered **$112 recommended, $144 max — both above the
   author's own dollar judgment** (a third round would offer $201.60). Meanwhile every
   option displayed **"closes ≈ $0"**: the projection basis holds G&A/marketing as
   PERCENTS while the panel gap derives them from FIXED DOLLARS — on the corrupt anchor
   gna_pct = 389% of revenue, so the projection said the price rise makes the gap WORSE
   (closes = −$1,862) and `max(0, closes)` silently masked the negative. Accepting the
   lever then actually closed $1,038. Same signature at normal magnitudes explains batch
   A's "fixed-cost-dominated" $0s. Side effect: her stated $5,900 supplies were silently
   inflated 2.5× to $14,676 (accept patch never rescales cogs_pct).
7. **Convergence and build.** $122,304 is units-consistent only at $112; at her real
   accepted $80 it needs 98% utilization (her stated max: 70%); at her original $45,
   174%. **No capacity term exists anywhere in the walk's convergence** (the anchor is
   never checked against ops physics in either direction; at msg 112 they diverged 26×
   and nothing noticed). The build then derives capacity FROM revenue ("capacity absorbs
   the remainder") and grows it to 31.2 grooms/wk by Q7 for a solo groomer whose stated
   ceiling is 30. Every downstream check passed; the plan shipped.
8. **Owner comp.** Three captures: role $24k (client override), field echo $2,000/mo,
   correction $3,300/mo at turn 111 — the correction landed ONLY in `owner_compensation`
   (the walk's disputable path; the CW-001 whitelist drops `people.*` writes), the gate's
   regex de-dup zeroed its effect, and the engine has no P&L seat for the field at all.
   **Her corrected pay need never reached the plan's cost structure.**
9. **Fleet-wide finding:** the marketing/demand model has been EMPTY on every draft since
   2026-07-22 and has never reached a submission (0 of 69). The only deterministic demand
   check compares unit counts and is structurally price-blind. The demand machinery is
   dormant.

## RULING SHEET (each item: the research's recommended shape; nothing built)

| # | Item | Recommended shape (from the research) | Blast radius |
|---|---|---|---|
| 1 | **Capture: one figure, one home** + stated-basis exclusion ("$3,300 *a month*" can only be annual as ×12) + disjoint shape sets (price-shaped ≠ count) + crush-needs-consent (>N× collapse routes through confirm) + close the prose-guard bypass | The smallest change that prevents the entire turn-112→119 arc | `_reconcile_driver_correction` + disposition; re-run CW-012/016 landing fixtures |
| 2 | **Anchor-vs-ops coherence at gate entry** (both numbers already computed in `ops_line_split`; hold/reconcile on divergence) | Catches both directions (26× low here; also anchor above physical ceiling) | section.py gate path; policy needed for legitimately-divergent shapes |
| 3 | **Absolute price ceilings in bounds** (stamp authoring-time price / dollar ceiling; clamp rounds + custom prices + corner) | Kills the multiplier ratchet; makes the author's judgment mean what its rationale says | bounds stamp shape (+fallback for old stamps), constraint_author, controller, section |
| 4 | **Demand response**: client clarifier on price acceptance first ("will your customers stay at $X?" — she already tried to tell us), judged volume-retention as the price lever's wall second; hardcoded elasticity RULED OUT (heretic class) | The lever's missing wall, per "no lever without its wall" | clarifier: one sub-turn, smallest; retention: constraint_author schema + `_price_move_basis` |
| 5 | **Cost lever semantics**: essential DOLLAR floors with per-item reasons in the bounds author (one `max()` in the controller), fed by component capture at intake; un-hardcode `recommended=True`; dollar-sanity of floor×revenue vs stated spend; fix the 500-char rationale truncation; map "gna" to client-facing language | Would have capped the cut at her stated committed spend even on the corrupted basis | constraint_author + controller + capture hook + phrasing |
| 6 | **Verdict honesty**: PASS branch computes the free flat eval + judged already in hand → suffix and panel disclose both ("at the strongest authorable path ~2× today: $X; at today's scale: $Y"); fence-pass + judged-fail routes to consult wording instead of "clears every test" (boolean trigger, no thresholds); fix panel "typical quarter"; router gets a verdict-grounding block whenever coherence state exists (never disclaim the gate) | The client who can't do the math gets the truth the client who can extracts | section suffix + PASS branch + CoherencePanel + intent_router prompt (additive) |
| 7 | **closes math**: align `_price_move_basis` to hold all dollar-denominated costs; rescale cogs_pct in the accept patch (stop inflating stated supplies); surface negative closes (a negative on a price INCREASE is a corrupt-anchor tripwire — would have auto-filed this bug on first occurrence) | UI stops lying; corrupt anchors self-report | one function + accept patch + display |
| 8 | **Owner-comp one-place collapse** (10-step plan in the R1 section of this research; HIGH-risk step is the baseline restamp). Sub-rulings: plan-forward vs historical wage; `intake_submissions.owner_compensation` column external consumers | The two-representation class dies | concentrated in intake capture + gate; engine already role-anchored |
| 9 | **Demand machinery dormancy** (empty since 7/22, never on a submission) | Separate investigation — why it stopped populating | unknown until traced |
| 10 | **Tier-1 cohort grading** | Wire LAST, after 1-8 make the P&L honest (per standing ruling) | known (naics + date-parse fixes) |

**Sequencing the research supports:** 1+2 first (capture integrity — everything else was
downstream of a corrupted anchor), then 3+7 (price/closes honesty, small), then 6 (verdict
honesty), then 5 (cost semantics), then 8 (owner comp), then 4 (demand wall), then 9, then
10. The Fetch & Fluff rerun after 1+2+8 measures what survives.
