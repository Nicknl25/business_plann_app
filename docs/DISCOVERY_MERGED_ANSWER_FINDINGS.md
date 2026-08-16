# Discovery findings — Corvid Press and Litho (draft e3af1f24, run 7c00eef3) — for Nick's ruling

Status: RESEARCH/TRIAGE for Nick (2026-08-16). NOTHING BUILT. Cowork run
on HEAD e661dfc; ended FAILED at the intake→post-intake boundary. Nick
saw the run play out live and chose to let it run.

## What happened (artifact-verified)
Commercial print house (NAICS 323111), two lines described and captured
(standard print job $690 / 30 wk / 66% contract; wide-format $420 / 9 wk
/ 55% contract). Discovery fired at the seam correctly in FORM: 4
proposals (cap held), why-clause, serial comma:
> "…a lot of commercial print houses also offer Digital printing
> services, Copying and duplicating services, Graphic design and
> prepress services, or Bindery and finishing services - is any of that
> part of your business today? (If so I'll include it as a revenue
> line.) …"

Client (turn 23): "Digital printing is **already part of our commercial
print line, it's the same jobs, not a separate thing.** No copying…
No graphic design… And no bindery… as a line."
- Reader: three plain no's → NO (correct). First clause → **YES** →
  appended `Digital printing services` as its OWN line, receipt "Noted -
  Digital printing services is its own line; a few quick numbers for it
  next", asked its capacity.
- Client (turn 25): "**No, don't make digital printing a separate line.**
  I already counted those jobs in the 30… you'd be counting the same
  work twice. **Please drop that line.**"
- App: NO acknowledgment, NO removal — went straight to the
  competitive-advantage question; ops wrapped; the row survived
  `consultant_finalize` (the discovery carry-forward re-attached it) with
  ALL drivers null (`unit_name=None`, no price/capacity/util,
  `origin=discovery_confirmed`).
- Financials cogs stage then PROPOSED a rate for the rejected line
  ("Digital printing services: about 25%") — client sees the dropped
  line again.
- Intake completed (converged, 57 turns, ~55 min); system run 7c00eef3
  FAILED at `validate_intake_draft_at_boundary`:
  `ContractViolation: INTAKE->POST_INTAKE: field
  'operating_model_json.lob_models.2.products.0.unit_name' expected a
  valid string (and 5 more errors), got None` → HTTP 500, run failed.
  The contract caught it fail-loud (no wrong plan shipped), but the
  client's ~55-minute intake ended in a dead run over a line they
  explicitly told the app to drop. Cowork filings: 0 (as of terminal).

## Findings (triaged)

D1 **READER: "affirmative but MERGED" is a third answer shape.** F4's
    intent routing has yes / no / unclear. "It exists but it's inside a
    line you already have — not separate" was read as yes-own-line.
    Receipt contradicted the client's exact words ("not a separate
    thing"); had numbers been captured, revenue would double-count.
    DEAL BREAKER class (false receipt; wrong number in the plan if
    numbers land). Fix shape: the classifier's outcome set gets
    "merged-into-existing" (the same intent door, one more class) →
    NO append; receipt: "Got it - digital printing stays inside your
    commercial print line; I won't split it out." Discovery-path only.

D2 **NO DROP DOOR + carry-forward resurrects the rejected row.** An
    explicit "don't make it a separate line / drop that line" was not
    acknowledged and not honored; wrap proceeded because GPT's finalize
    snapshot omitted the row (honoring the client), and then the
    discovery carry-forward — the mechanism that keeps latch/origin rows
    alive across finalize — re-attached it. Result: a null-driver
    phantom product entered the model, resurfaced at the cogs stage,
    and killed the run at the boundary. DEAL BREAKER class (receipt law
    on the correction; a rejected line in the plan; a dead run for the
    client). Fix shape: (a) an explicit drop of a discovery-confirmed
    line (intent: negative/retract on a named line while its capture is
    open) removes the row and updates the latch (`answer: retracted`),
    with a receipt that says so; (b) the carry-forward must NEVER
    re-attach a row the client dropped (respect the latch's retracted
    state; carry forward only rows still present in the finalized
    snapshot OR still confirmed in the latch); (c) belt-and-braces: a
    discovery row with null drivers must not pass ops wrap — the
    completeness gate should see the SAME row set that gets persisted
    (today it evaluated GPT's snapshot while the persisted model had the
    extra row). Discovery-path + the finalize carry-forward seam.

D3 **JUDGE: proposed a SUB-CATEGORY of a stated line.** "Digital printing
    services" is a subset of "Commercial print"; F1's dedup passed it on
    the shared category noun alone (as designed), leaving the client to
    catch it. WATCH / judge-prompt refinement: propose PEER streams, not
    sub-categories or delivery methods of a line already stated (tell
    the judge the client's lines are to be treated as covering their
    sub-types). Not a deal breaker on its own (D1/D2 are what made it
    bite).

D4 **Contract validator = the last line held.** The boundary contract
    refused the null-driver row fail-loud (500, run failed) — correct
    behaviour under the fallback-class law; the failure surface is the
    working internal-email path (off-limits, unchanged).

## Recommendation for the ruling (nothing built until Nick says)
D1 + D2 as ONE discovery-path turn (both are the reader/append/drop
surface + the carry-forward guard; VS declares tier — expect spot-check
for D1 and the drop door, NEIGHBOR-CHECK for the carry-forward guard
since it sits on the finalize seam both hooks and the latch flow
through; split per the law if VS judges so). D3 as a judge-prompt
tweak riding the same turn or parked. Red-proof on the exact Corvid
transcript: PRE reads "already part of our commercial print line" as
yes and resurrects the row after "drop that line"; POST reads it as
merged (no append, honest receipt), and an explicit drop removes the
row, the latch records retracted, finalize does not re-attach, the
boundary contract never sees a null-driver row. Then a Cowork re-run.
Also relevant to the queued seam move (:16794): asking BEFORE capture
would make "merged into an existing line" a more natural answer to
handle, but D1/D2 stand regardless of where the ask fires.
