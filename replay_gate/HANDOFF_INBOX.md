# HANDOFF INBOX — plain English only. The WATCHER seeds the task and flips
# STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.

TURN-TIMEOUT-MINUTES: 240

CW-033 FIXES + DISCOVERY RESEARCH (Nick, 2026-08-14) — blockers first,
artifact-level verification throughout. Per-line COGS is PROVEN
end-to-end and CLOSED (A-110/A-111/A-114); do not reopen it. Evidence
base: CW-033 Thornfield draft d9b17850 run 76b2553b, the A-113 filing,
VS_NOTES CW-033 sections.

TIER 1 — A-113 CAPACITY SMEAR (rank 1, the ONE open blocker):
A post-stage per-line capacity correction (install 5 -> 7) is LOST —
three correction shapes tried live (bundled, standalone-both-values,
standalone-single-number-line-named), three receipts, ZERO writes; one
receipt echoed back the value being corrected AWAY from. And the loss
SILENTLY SMEARS: the build applied a uniform 1.106527 factor across
ALL FOUR lines, inflating three lines the client never touched by
10.65% to absorb install volume never booked, install itself 21% below
the corrected value. FIX: a post-stage per-line capacity write path
that lands the correction on the NAMED line, OR an honest refusal —
NEVER a silent uniform smear. The app must not silently alter what the
client declared (the parent law, same as A-110).
ARTIFACT VERIFICATION (mini): the corrected line carries the client's
value; the OTHER lines are unchanged; no uniform factor anywhere in
the build; the receipt speaks the written value (never the corrected-
away-from one).

TIER 2 — RECEIPT/ROUTER FIDELITY (two findings, one shape: the router
mistakes what KIND of number it is):
1. A COGS rate echoed as "Recorded: unit price 58" and fired the
   price-change retention gate against NO price change; correcting via
   restated prices reproduced it ("unit price 95") and fired the gate
   again — the recovery path SELF-TRIGGERS. Fix: the router classifies
   a COGS rate as a COGS rate, never a price; a COGS correction must
   not fire the price-retention gate. Verify: a COGS-rate turn writes
   the COGS field, no unit_price write, retention_pending NOT stamped.
2. An explicit "Not recently, no" to the capex question was DISCARDED
   and the $380k the client EXPRESSLY EXCLUDED in the same sentence
   was captured as current-year capex — and the next question asks
   equipment worth, so an unattended client BOOKS THE EQUIPMENT BASE
   TWICE. Fix: honor the client's no; never capture an expressly-
   excluded figure as capex; prevent the double-count. Verify:
   the "no + excluded figure" turn stores capex 0/none, and the
   equipment base appears ONCE in the built model.
3. Ack contradiction (clean recurrence of the receipt law): the note
   named "units per week capacity and unit price" as unrecorded in the
   very message that recorded and restated both. Words match state,
   one source — fix at the source that composes the note.

TIER 3 — DISCOVERY RESEARCH (RESEARCH ONLY — produce a spec, BUILD
NOTHING; runs alongside tiers 1-2 since it touches no code):
Proactive stream discovery: the app surfaces revenue streams the
client's business type USUALLY has but didn't mention, so real revenue
is not left out of the plan. Nick's framing, non-negotiable:
- DISCOVERY not upsell: capture streams the client ALREADY HAS but
  didn't mention ("a lot of garden centers also do design work — do
  you?"). NEVER propose streams to ADD ("have you considered adding
  design?") — that fabricates revenue.
- Ask about EXISTENCE, not addition. The client's actual business is
  the authority.
- Only the 2-3 streams GENUINELY COMMON for that specific business
  type (use the category knowledge the demand judge already has),
  never a generic checklist.
- Ask ONCE per likely stream, believe the answer, no re-probing.
- A discovered stream lands as a real LOB through the confidence gate.
RESEARCH THE SHAPE: where the category knowledge comes from, how it
asks without over-proposing, how a discovered stream lands through the
confidence gate into the per-line machinery, where in the flow it
fires. REPORT THE SPEC for Nick's review (a docs/ design note is the
deliverable). The build waits on A-113 closing AND Nick approving the
spec.

PROCESS: A-113 first, then tier 2; tier 3 research alongside. Mini
artifact-verifies each fix. Standing laws hold (backend restart + ONE
listener, canary before batches, foreground-only long jobs, red-proofs
red for the right reason). When A-113 + tier 2 are clean AND
live-verified AND the discovery spec is ready for review: VERDICT
green so the watcher stops and pings Nick.
