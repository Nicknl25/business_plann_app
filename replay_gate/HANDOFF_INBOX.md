# HANDOFF INBOX — plain English only. The WATCHER seeds the task and flips
# STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.

TURN-TIMEOUT-MINUTES: 240

NICK'S RE-SCOPE (2026-08-14, supersedes the A-113 instruction in the
prior task — read BEFORE continuing the batch): CLASSIFY every open
CW-033 finding against the GUIDED-FLOW BOUNDARY before fixing. The new
testing principle: is the finding reachable ON-PATH (a client following
the app's guided conversation) or only OFF-PATH (leaving the guided
flow — jumping back to a closed stage, correcting out of order)?

A-113 SPECIFICALLY — re-scope it. Cowork triggered the capacity smear
by correcting install capacity AFTER the operations stage closed.
DETERMINE: does the app's guided flow ever lead a client to correct
capacity post-stage? Or does the guided conversation keep capacity
correction IN the operations stage (where CW-030's 6->8 landed fine)?
- If post-stage capacity correction is OFF-PATH (the app never invites
  it, a real client never does it): the fix is NOT a post-stage write
  path. The fix is keeping the client ON the guided flow — either the
  flow never leaves them needing a post-stage correction, OR if they
  attempt one, the app gracefully redirects ("we'll finalize capacity
  in the operations step") rather than silently losing it and
  smearing. PREVENT THE STATE, don't build machinery to support an
  off-path move.
- If it IS on-path (the guided flow genuinely leads a client there):
  real bug, fix the write path.
REPORT WHICH IT IS before building A-113's fix. If the in-flight turn
already built post-stage write machinery beyond this ruling, PARE IT
BACK to match the classification — the silent smear must die either
way (an off-path attempt gets an honest redirect, never a silent
loss + uniform smear).

THE TWO RECEIPT FINDINGS + ACK ARE ON-PATH — fix regardless:
1. COGS-rate-echoed-as-unit-price + firing the price-retention gate
   against no price change (self-triggering recovery) — happens IN the
   guided flow when the client answers the COGS question. Real. Fix.
2. Capex double-count — the client said "not recently, no" to the
   app's OWN question and it captured the excluded $380k anyway, and
   the next question books it again. ON-PATH, mishandling a solicited
   answer. Real. Fix.
3. Ack contradiction — words not matching state, on-path. Fix.

THE PRINCIPLE (record it in VS_NOTES as a design law): the guided flow
bounds what SEQUENCES are reachable — off-path sequence bugs get
PREVENTED, not supported. But the app must be HONEST within any answer
it SOLICITS — honesty bugs are always fixed. Classify, then fix the
on-path ones and prevent-not-support the off-path ones.

Discovery research (tier 3, spec-only) continues unchanged. Mini
artifact-verifies per the standing law; green stops for Nick.
