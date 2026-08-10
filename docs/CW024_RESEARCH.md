# CW-024 RESEARCH — Cedar Ridge run (7deeafb2): full mechanism map (NO BUILD)

Nick's frame: the honesty layer performed (wall caught 136%, demand judge good,
no cut-insurance, widening tripwire fired, honest park) — but the LISTENING
layer failed and the EXPERIENCE layer was never built. The client corrected the
one wrong number seven+ times and was never heard, wrapped in backend jargon.
The capture failure, the jargon, and the test gap are the SAME disease at three
layers: **the app's internal state diverging from what the client experiences
and can fix.** #112 shipped (be7dbb6, standing ruling). Everything below is
research; Nick rules the slate at once.

---

## TRACK 1 — CAPTURE, CORRECTION & ASK-THEN-IGNORE

### #108 crew double-count — mechanism
1. The people consultant captured the crew as a KEY-PERSON row: "Grounds
   Maintenance Crew Members" (a *group of four* as one person-row, $136k).
2. `_rest_of_team_payroll_pending` fires whenever `rest_of_team_payroll_year1`
   is None — it does not consider that a group row already covers the team.
3. The client restated the crew total (the most predictable behavior at that
   prompt), the patch landed `rest_of_team=136,000`, and the canonical rollup
   (correctly, given its inputs) summed rows + rest = 361,000.
**Root cause**: no reconciliation at the rest-of-team landing against rows the
app already holds, plus group-of-N captured as a key-person row.
**Fix shape**: (a) at the rest-of-team landing, compare the incoming figure to
existing non-owner rows — equal figure (±5%) or group-titled row → ONE
question: "is that the same crew I already have (your four at $34k), or
additional people beyond them?" — never a silent sum; (b) a rollup tripwire:
any single row equal to `rest_of_team` exactly is flagged as suspected
duplicate; (c) the people consultant captures crews as `rest_of_team` or
inferred group, not as key-person rows. **Blast**: people capture flow + one
guard at the rest landing; canonical rollup untouched.

### #109 seven dropped corrections — full mechanism (three interlocking causes)
1. **No door**: Phase 1 made the payroll trio unpatchable (correct — the Recalc
   owns the twins) but only OWNER pay got a one-door pseudo-field. A stated
   TEAM TOTAL has no landing: `people.total_team_payroll` does not exist;
   roster edits (remove/dedupe a row) have no patch shape at all;
   `payroll_adjustment` is a walk-lever field the router never chooses for a
   stated-fact correction.
2. **Mid-round funneling**: while a round is live, the router frame offers
   `coherence.option`, `assert_floor`, the round's own targets, and
   DISPUTABLE_FIELDS — which contains `people.owner_pay_monthly` but no
   team-total door. Everything else in the turn routes to option-intents or
   continue_chat and the numbers in it evaporate.
3. **Silent drop**: the walk paths have no write-receipt contract. The edit
   path has Layer-2 receipts and say-do notes; the round path returns the next
   round question with no "I could not record that." Seven corrections vanished
   without disclosure — the say-do doctrine's biggest hole.
**Fix shape**: (a) `people.total_team_payroll_statement` pseudo-field — lands
via the existing fold + sub-ruling-(ii) hold (rest absorbs; touching named
people HOLDS with the how question — machinery already shipped); (b) roster
edit shapes (`people.remove_role`, dedupe) through the scoped people branch;
(c) add both to DISPUTABLE_FIELDS so mid-round turns can carry them; (d) the
UNIVERSAL RULE: any turn whose message contains a numeric correction that
lands nowhere gets an explicit disclosure appended ("you gave me a number I
couldn't place — tell me which line it belongs to"), enforced at the receipt
layer, not per-path. **Blast**: intake_consult scoped patch + DISPUTABLE +
walk-turn receipt; fold untouched (already built for this).

### THE ASK-THEN-IGNORE CLASS (#109 / #117 / #118) — one disease
Three solicitations whose answers had no consumer:
- The wall/widening message asks **"tell me which figure looks wrong"** — the
  answer has no landing (see #109).
- The marketing stage records the default while the client says **"I don't
  spend anything like that today"** (#117) — the stage-answer path has a
  basis-clarify gate for figure conflicts but NO mismatch detector on the
  acceptance TEXT; "accept + explicit disagreement" lands as accept.
- The price clarifier asks **"tell me how many you'd keep and I'll rerun"**
  (#118) — `_pc_question` is TEXT ONLY: it registers no router frame, no patch
  target, no consumer. The ruled behavior (client answer overrides the judge)
  was built on the authoring side but the CONSUMPTION side was never wired.
  "30 of 34" and "24 of 34" both discarded for the 0.80 edge.
**The class rule for the slate**: every solicitation ships a LANDING CONTRACT —
the question registers its target (a controller frame like the rest-of-team
question already has) and the answer either lands there or triggers the
disclosure. No question without a consumer.
**#118 fix shape** (already ruled, wiring missing): the clarifier stamps a
pending frame {product, price_to, asked}; the router maps a retention answer
(count or fraction) to a `coherence.retention_answer` patch; landing scales
utilization/anchor to the CLIENT's fraction (replacing the 0.80-edge landing)
and records lever writes. **#117 fix shape**: an acceptance whose text carries
explicit-mismatch markers ("nothing like", "way more than I", "don't spend
that") triggers the same ask-first hold the basis gate uses.

### #115 capex-zero — regression autopsy
Original: **#84** "a correction sent between stages is recorded as the answer
to the pending stage question," resolved 08-07 (`retested_clean`). The fix
admitted corrections to fields whose stage was COMPLETE (the `correctable`
set) so they would not fall through to the pending-stage reader. **The
regression vector: Phase 1 (08-09) made the payroll trio UNPATCHABLE — a
payroll correction is no longer in any correctable set, so the #84 protection
no longer applies to it, and the message fell through to the capex stage
reader again — which synthesized $0 from a message containing no capex figure
at all.** Two sound changes, one silent interaction, zero pinned regression
test (Track 3). The zero-synthesis is its own violation: a stage answer must
never be manufactured from a message that names a different field.

### #116 answers-as-park + disabled inputs
The client answered the app's two questions (line contents + which figure is
wrong); the router mapped the turn to `coherence.parked`. Root: the park
intent's mapping is over-broad during rounds (a long "here's my situation"
answer pattern-matched "save it for now"), and parking DISABLES Send/Submit in
the frontend (parked rendering), stranding the client — recoverable only
because the un-park path worked. **Fix shape**: park requires an explicit
stop-intent marker (deterministic phrases or a confirmation question: "do you
want to pause here? Nothing is lost either way"); a turn that ANSWERS pending
questions can never park; frontend keeps Send enabled while parked.

### CATCH IT AT THE SOURCE — the map
Errors catchable where created vs. currently carried to coherence:
| Error | Source moment | Guard today | Catchable at source? |
|---|---|---|---|
| Crew double-count | rest-of-team landing (people) | none | YES — reconciliation question (#108 fix) |
| Group-as-key-person row | people consultant capture | none | YES — capture rule |
| 42% COGS on 6% materials | cogs stage proposal | fallback unguarded | YES — Track 4 #110 (band + reconciliation at proposal) |
| Marketing accept-with-mismatch | marketing stage | none on text | YES — #117 mismatch hold |
| Correction eaten by pending stage | any stage boundary | #84 fix (partially dead) | YES — restore + widen (#115) |
| Payroll share 136% | first rollup after both writes | wall fires only at GATE | PARTIAL — a source-side tripwire (rollup > ~1.0 × revenue at stage time) could ask in the room, stages earlier |
Existing source guards that DID work: derivability guard, basis gate, crush
consent, floors, deep-cut ask. The principle holds: everything in this run's
disaster chain was visible at a capture moment before coherence ever ran.

---

## TRACK 2 — CLIENT-FACING LANGUAGE / UX

### Jargon inventory (client-visible strings using internal vocabulary)
| Current string (site) | Problem | Plain replacement direction |
|---|---|---|
| "meet the market" / "top of the judged range" (pricing option labels) | judged = internal; "range" is DB-speak | "a middle step: $X" / "the top of what your market pays: $Y" |
| "the believable range for your market runs up to $X" (pricing narration) | believable plants doubt | "similar businesses in your market charge up to about $X" |
| "fill to the judged demand ceiling" / "grow the book a believable step" (volume labels) | judged, believable | "take on more properties: about N" / "a smaller step: about N" |
| "the believable demand for your market supports up to N" (volume narration) | believable, judged | "your market realistically has room for about N a year" |
| "range judged believable for your kind of business" (converged suffix band text) | judged, believable | "the range healthy businesses like yours actually run" |
| "a judgment from your market's own numbers" (retained-assumption line) | judgment surfaced | "based on what your market's numbers show" |
| "the plan builder enforces that ceiling exactly" (wall message) | internal machinery named | "a lender won't finance a plan above that level" |
| "stress test, not a forecast" (converged suffix) | borderline — finance-speak but honest | keep or soften ("a pressure-test of the numbers") |
| "(One note: I haven't recorded baseline marketing, baseline marketing percent and marketing adjustment yet...)" (say-do note, #89) | RAW FIELD NAMES to the client | plain names or suppress when derived fields |
| "(Noted: weekly capacity -> 40 ...)" (#95) | field-speak + wrong cadence label | "40 properties a month" per stored cadence |
**Why inconsistent**: CW-022 #5 reworded ONLY the costs-round labels and move
names (that is why "right-size all of it" reads well). The pricing/volume
labels and every narration string were authored per-feature with no shared
copy standard. **Fix shape**: one client-copy pass over the inventory + a
FORBIDDEN-VOCABULARY LINT ("judged", "believable", "range" as noun-of-record,
raw field names, "plan builder", internal keys) enforced by a test (Track 3) so
new strings cannot regress. Blast: strings only — zero mechanism change.

### "Tell me what's in those lines" — the app outsourcing its job
Sites: the deep-cut ask ("only if what's inside those lines can really shrink;
tell me what's in them first"), the wall's "tell me which figure looks wrong"
(doubly broken — no landing), and the lease ask (mild — one yes/no is fine).
**Doctrine tension to rule**: CW-022 #5 RULED ask-first for deep cuts; CW-024
says a consultant already knows overhead holds insurance. These conflict.
**Proposed resolution (needs Nick's supersede)**: an ESSENTIALS JUDGE — the
demand-judge pattern again: GPT classifies the opex line's likely composition
from the business type (licensed trade → insurance/comp/licence = essential
floor by default) and the round only ever offers the DISCRETIONARY slice; the
client can still assert or correct, but is never interrogated about their own
P&L. Deep-cut asks survive only where the judge itself says composition is
genuinely unknowable. Blast: costs-round floors + one new judgment; the
client-floors machinery unchanged.

### Ambiguity sweep (beyond jargon)
- Options don't state their CONSEQUENCE in client terms ("closes about $X of
  the gap" is good; "on these numbers that would WIDEN..." is good; labels
  alone are not).
- The park invitation ("we can leave it right here") reads as a soft
  suggestion — contributed to #116.
- The two-question turns (contents + which-figure) invite compound answers the
  router then mishandles — one question per turn during rounds.

---

## TRACK 3 — WHY THE TESTS WERE GREEN (the process failure)

### The honest answer
1. **Builder-not-chain tests**: F2b proved the default-patch DICT carried
   `cogs_basis=ratio`; the production applier filtered it. The 4-step E2E
   discipline says "confirm the test hits the exact production chain" — the
   test I wrote did not, and the suite stayed green through a ruling
   violation. (#112. Fixed with F2b-PROD through the normalize path.)
2. **Covered-path-only proofs**: fitted COGS was "proven live" on janitorial
   (COVERED → fit judge). 561730 is uncovered → plain fallback → no band, no
   reconciliation, no range wording, 42% vs ~6%. The fallback is the MAJORITY
   path (387 NAICS covered of ~1,000+). Inventory of the same hole elsewhere:
   - marketing `_fallback_marketing_estimate` (non-US / missing basis): untested
   - clarifier-answer consumption: untested (and unwired — #118)
   - mid-round multi-intent corrections: untested (#109/#115/#116)
   - park/un-park routing: untested (#116)
   - stage acceptance-with-mismatch text: untested (#117)
   - volume-cap denominator seam (612 vs 600 display): unit-tested at the
     wrong altitude
   - (Counterexamples that were done right: demand-judge THIN was tested and
     held; class backfill tested; lease gate tested.)
3. **No experience-layer tests**: nothing can fail on "meet the market" being
   incomprehensible — worse, the suites ASSERT the jargon (my W4c/L1 checks
   grep for the internal wording, cementing it).
4. **No regression pinning**: #84 was resolved with a live retest but no
   pinned test; Phase 1's unpatchables killed its protection silently. #112
   likewise had no post-ruling pin.

### Proposed test standard (rules, not aspirations)
1. **Production-chain rule**: an E2E must enter through the handler/applier
   the live turn uses (name the chain in the test header; builder-function
   tests never count as coverage for a ruling).
2. **Fallback parity rule**: every covered/uncovered, judge/fallback,
   rich/thin split ships BOTH sides in the same suite, and "proven live"
   claims name which side was proven.
3. **Client-copy lint**: a string-bank test over every client-facing string
   with the forbidden-vocabulary list; new copy fails the suite until it
   passes the lint. Suites may not assert forbidden vocabulary.
4. **Regression pinning**: an issue marked fixed gets a signature-named E2E in
   a dedicated regressions suite the same day; the issue DB links issue → test.
5. **Standing corrective-client E2E**: a scripted adversarial mini-persona
   (the Cedar Ridge shape: capture a fact wrong, then correct it N ways
   mid-round, assert it lands + is disclosed) run like the canary — a cheap
   Cowork between real Cowork runs.
**The named gap**: suite-green proves "the mechanisms I thought to test work
on the fixtures I wrote"; product-works means "a non-savvy client's actual
statements reach the actual state through the actual chain, on the paths most
clients hit." Rules 1-5 are the bridge.

---

## TRACK 4 — NUMBER/LEVER BUGS

### #110/#111 fallback COGS unguarded
Root: two estimators, one honesty standard applied to one of them. **Fix
shape**: ONE estimator — `fit_cogs_percent_from_evidence` with
`cohort_evidence` optional; band + reconciliation + range wording ALWAYS; the
plain estimator retires. Uncovered NAICS then gets: "materials for a grounds
operation like yours typically run X–Y%..." with the same anti-false-precision
floor. Blast: `_compute_cogs_baseline` fallback branch + retire one function.

### #113 the cross-epoch price ratchet — the shape for Nick's ruling
Mechanism confirmed: client correction → identity re-key → bounds re-author →
the author judges a RELATIVE multiplier against the CURRENT price (now the
just-accepted one) → `unit_price_at_authoring` re-stamps fresh. $650→$910→
$1,183→$1,597. CW-022 #3's dollar-absolute fix protects within an epoch only.
**Proposed shape (research-confirmed workable)**: the judged ceiling becomes a
DURABLE MARKET FACT in dollars, stored per line OUTSIDE the re-keyed artifacts
(`price_ceiling_market_fact: {line, ceiling_dollars, market_slice_hash}`):
- Re-authoring RECEIVES the prior ceiling as evidence with the instruction:
  "re-judge the MARKET; a client accepting a price is not market evidence."
- The fact re-judges ONLY when the MARKET-side identity slice changes
  (market_json/geography/segments/business-type — computable as a sub-hash),
  never on price/financials/acceptance changes.
- `_effective_pmax` anchors to the market-fact dollars permanently.
- **One necessary valve**: a CLIENT-STATED market fact ("the big management
  companies pay more than that for the same work" — which this client actually
  said) is market evidence and may re-open the judgment through the normal
  stated-fact door — acceptance never, statements yes. Without the valve the
  fact would be a one-shot cap that ignores real client knowledge; with it,
  the ratchet cannot feed on acceptance alone.
Blast: bounds authoring + `_ensure_bounds` stamp + effective_pmax; identity
machinery untouched.

### #114 volume past stated capacity
Root: bounds `volume_multiplier_max` (1.5×) judged without honoring
`capacity_driver=labor`, and the round's max option implies capacity growth
beyond the stored 40 silently (utilization-first landing covers only up to
100% of stored capacity; beyond that it grows capacity). **Fix shape**: options
cap at 100% utilization of STORED capacity; anything above requires an
explicit consent step ("this means taking on more than your current crew can
serve — is growing the crew on the table?"); `capacity_driver=labor` gates the
capacity-growth half entirely and points at hire-timing instead. Blast:
`_volume_round` mults + landing; bounds authoring optionally told the
capacity driver.

### #89/#95 — cheap closes riding along
#95: the capacity ack labels are hardcoded "weekly"; label from the stored
cadence (one string site). #89: the say-do "not recorded yet" note reads
pending-schema fields rather than the just-written store — point it at the
post-write state (and never name raw fields to the client per Track 2). Both
are one-site fixes; recommend bundling with the Track 2 copy pass.

---

## THE CROSS-CUTTING PICTURE
One disease, three layers: **internal correctness diverging from client
experience.** The capture layer holds state the client can see is wrong but
cannot reach (no doors, ask-then-ignore); the language layer describes honest
machinery in words the client cannot parse (judged/believable/field-names);
the test layer certifies the divergence as green because it tests the app's
own fixtures through the app's own vocabulary on the app's happy paths. The
slate's common spine: every question has a consumer, every number has a door,
every string passes the plain-language bar, every fix gets pinned, and every
split path gets both sides proven — so the app is never again dumber than the
client it is advising.

## THE SLATE FOR RULING (suggested order)
1. Correction doors + universal no-silent-drop receipt (#109 core, enables #115/#116 class) 
2. Rest-of-team reconciliation + group-capture rule (#108)
3. Ask-then-ignore landing contracts (#118 clarifier wiring, #117 mismatch hold, wall's which-figure landing)
4. Park requires explicit stop-intent; answers never park; Send stays enabled (#116)
5. Fallback COGS unification (#110/#111)
6. Price ceiling as durable market fact + client-statement valve (#113 — Nick rules the shape)
7. Volume capacity cap + labor gate (#114)
8. Client-copy pass + forbidden-vocabulary lint (+#89/#95 riding along) — with the CW-022 #5 deep-cut ask-first doctrine explicitly superseded by the essentials judge, if Nick rules so
9. Test standard adoption (rules 1–5) including the standing corrective-client E2E
#112 already shipped (be7dbb6).
