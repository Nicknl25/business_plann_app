# HANDOFF INBOX — plain English only. The WATCHER seeds the task and flips
# STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.

TURN-TIMEOUT-MINUTES: 240

CW-031 RAVENWOOD BATCH — nine items, three tiers, worked in order. Nick
runs no further Cowork until all nine land AND mini confirms them at the
ARTIFACT level. Evidence for the whole batch:
replay_gate/VS_NOTES.md CW-031 sections, draft 1070c6a5, run ad8627f3,
workbook "Ravenwood Garden Company -- 08-13-2026 12-14-03.xlsx".

THE VERIFICATION LAW FOR THIS BATCH (Nick, non-negotiable). Every COGS
item is verified by reading the ARTIFACT, never the proposal prose:
  - cogs_percent_of_line_revenue is NON-NULL on all N product rows in
    persisted ops json after the stage completes;
  - the BUILT WORKBOOK carries N per-line COGS formula rows and the
    total row is =SUM over exactly those rows;
  - Sigma(line revenue x line pct) == blend == finmo COGS per quarter;
  - for the collapse: lines sharing a rate carry the SAME stored
    percentage while the others differ.
An assistant message proposing a split is NOT evidence for any of the
above. The false resolution in item 1 happened precisely because a
detector read the proposal instead of the artifact - do not reproduce
that inside the loop.

KNOWN INSTRUMENT GAP, read before planning: the frozen golden legs
(R26/R27/R31/R32) build from committed bytes with no DB, so they start
DOWNSTREAM of the write. They will pass forever while nothing writes the
rows - that is exactly how VS's stamped E2E passed while the intake half
was dead. This batch needs a leg that starts UPSTREAM: drive a COGS
stage acceptance through the real handler path, then assert the artifact.
If mini's harness for these can only reach the proposal, fixing the
harness is the first sub-task of that item.

TIER 1 - META-FIX, DO THIS FIRST, NON-NEGOTIABLE:
1. The issue registry marked #138
   (flow:financials:two_line_business_gets_one_blended_cogs_and_the_
   question_goes_unanswered) RESOLVED CONFIRMED on the very run that
   disproves it - Ravenwood is a FOUR-line business whose delivered
   workbook has ONE blended COGS row (row 9, =D8*'Model Inputs'!D24).
   The detector checked whether the app PROPOSES a per-line split
   (prose) instead of whether the split REACHES THE MODEL. Fix the
   detector to verify the artifact (per-line rows in the workbook /
   cogs_percent_of_line_revenue written). THEN AUDIT EVERY OTHER
   RESOLUTION THE REGISTRY REPORTS - if this one checked the wrong
   thing, others may too. Report which detectors verify artifacts and
   which verify intentions. Nick does not trust the registry until this
   is answered.

TIER 2 - THE CORE INTAKE GAP (why the next Cowork run matters):
2. RECEIPT-WITHOUT-A-WRITE IS ITSELF THE DEFECT. The app said "Got it -
   I'll keep one shared direct-cost rate for Plant sale and Hard goods
   sale, with separate rates for Install project and Design consult"
   and stored NOTHING (token scan: zero cogs_shared /
   shares_cost_structure / cogs_group records anywhere in the draft).
   Same shape as the doubled "marketing $0 / cogs 0" receipts. Make a
   confirmation STRUCTURALLY DEPENDENT on the write succeeding: the app
   must not be able to say it did something it did not do. This
   outranks the routing gap - a silent wrong number is bad, a wrong
   number plus explicit assurance is worse.
3. WIRE THE COGS WRITE DOOR (A-110: the write door and the model row
   are ONE fix - separately each leaves it unusable). The judge proposes
   four rates correctly (55/60/38/6 with bands and right economics) and
   cogs_percent_of_line_revenue reads null after six correction
   attempts across three phrasings. The field exists in the schema and
   _apply_per_line_cogs_to_ops exists and is called - it is an UNWIRED
   DOOR. Route proposal -> written per-line percentages. The engine
   already consumes them (Thistledown-proven, workbook carried two real
   rows with =SUM over them). The shape to copy is one section over:
   revenue is fully per-line at N=4, COGS needs the same wiring.
4. ROUTE THE COLLAPSE INSTRUCTION. "Plants and hard goods are both
   bought-in retail goods, treat those two as sharing one cost
   structure, keep install and design separate" needs an intent, a
   door, and a consumer. The judge schema already carries
   shares_cost_structure_with and nothing in the conversation can set
   it. The client is the authority on how many DISTINCT COGS exist.
5. SHOWN PROPOSAL == WRITTEN PROPOSAL. The message and the write each
   resolve the COGS baseline independently (two judge calls); the
   write's call can fail the all-or-nothing line-name match and degrade
   to blend-only SILENTLY. Resolve once, and make degradation LOUD -
   never ship a silent blend after promising a split.

TIER 3 - DISPLAY / COPY (same batch, small, Nick wants the next run clean):
6. The capacity note repeats a placeholder ("weekly capacity -> 420" x4,
   "and 1 more"). The underlying 420 broadcast is BENIGN (a transient
   seed every line overwrites - verified live), but the note still
   displays the repeated seed. Show distinct per-line values or do not
   surface the transient seed. Say plainly whether it is cosmetic or the
   note-builder reading the wrong field.
7. The doubled receipt line ("weekly capacity -> 180; weekly capacity ->
   180" in one acknowledgment).
8. The weekly/monthly label mismatch the issue checker flagged
   observationally (capacity acknowledgement uses a weekly label for a
   monthly unit).
9. Confidence-gate copy asymmetry: the collapse invitation only offers
   going DOWN ("one or two lines instead of three") and never up, though
   a client can go to four. Say both directions.

VS: work tier 1 first and hand to mini before starting tier 2 - Nick
wants the registry answer early. Then tiers 2 and 3. Keep the standing
laws: restart the backend after app-code edits and verify ONE :5050
listener, one Sunny_V3 canary before any batch of runs, never kill :5050
mid-canary, red-proofs red for the right reason, and never end a turn
with a job still running.
