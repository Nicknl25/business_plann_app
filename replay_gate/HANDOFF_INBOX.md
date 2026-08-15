# HANDOFF INBOX — plain English only. The WATCHER seeds the task and flips
# STATUS itself. Nick never edits HANDOFF.md, STATUS, config, or code.

DEAL-BREAKER BATCH — Nick APPROVED the triage (2026-08-14 night). All
four deal breakers, sequenced easy-first/big-last. This seed lays out
the WHOLE itinerary; each agent carries it forward in its outgoing
TASK block so the chain runs without re-seeding. The 20 WONT-FIX
closures STAND. The 10 FEATURE DECISIONS stay PARKED for Nick — no
one builds, pulls, or specs any of them.

TURN-TIMEOUT-MINUTES: 120

TURN A (VS, SPOT-CHECK tier — guards/copy/validation, none changes
shared high-fan-out code; grouped per the split law: repro red->green
per fix + artifact + single-line floor via --only, NO canary, NO full
prove). Three fixes, each with its deal breaker named (turn-plan law):
  A1 (cands[-1] price/util branches): price/utilization corrections
    use last-figure-wins — "price should be 650, I was thinking 520"
    stores 520. DEAL BREAKER: the client's corrected price is
    replaced by their discarded one in the delivered plan. Apply the
    capacity branch's already-proven fix shape (sentence-scoped +
    marked-candidate + refuse-on-ambiguity) to the price branch.
  A2 (#134): "our terms are net 45" stores 45 as capacity. DEAL
    BREAKER: a payment term becomes a production volume the model
    builds on. Add the guard — REPRO FIRST (red on the real shape
    before the fix).
  A4 (#122): a below-market price is called "mid-market" in plan
    copy. DEAL BREAKER: a false market-position claim in the
    delivered plan. VERIFY FIRST (confirm the copy path still does
    it), then fix the claim to speak the actual position.
  Flip to mini with a TASK for turn B below.

TURN B (mini, SPOT-CHECK audit — minutes): the four confirmations on
  A1/A2/A4: diff does what the plan said; artifact shows the right
  value on each repro; VS's tier call was honest (a spot-check claim
  on shared high-fan-out code escalates); floor held. Flip and write
  VS's TASK for:

TURN C (VS, travels ALONE per the split law; SPOT-CHECK by default —
  fix the viability check, repro that a plan can no longer pass on
  volume above stated capacity, confirm the artifact, floor. Expand
  to NEIGHBOR-CHECK only if the fix actually changes shared
  viability/engine code other behaviors flow through — then check the
  named neighbors on that path, not the universe. FULL apparatus only
  if it is a core engine/money-math change; declare the call + why in
  the TURN PLAN):
  A3 (#101): a plan can PASS viability on volume ABOVE the client's
    stated capacity. DEAL BREAKER: the delivered plan certifies
    numbers the client told us they cannot produce. REPRO FIRST —
    red on a real shape where stated capacity is exceeded and the
    verdict still passes — then fix so the pass respects stated
    capacity.
  Flip to mini with a TASK for:

TURN D (mini): the OWED turn-5 audit, SPOT-CHECK EACH FIX — does each
  landed fix (D1-D5+X2, a4dc230) show correctly in its artifact, was
  each tier call honest. NOT a full re-audit of the system. Where a
  turn-5 fix changed shared high-fan-out code (the forward mover did),
  neighbor-check THAT fix's named neighbors — not the universe. Also
  spot-check A3 at the tier VS declared (verify the call). Original context: — the original mini session
  died mid-audit, so turn 5's five fixes (D1-D5+X2, a4dc230) were
  never independently verified. Artifact-audit them now, plus A3.
  On a genuinely clean table: VERDICT green — the watcher stops and
  pings Nick. Feature decisions remain his to rule on after.

Standing laws apply every turn: TURN PLAN first (emit, then proceed),
context scoped to the task, SPOT-CHECK the fix by default (neighbor-
check only for shared high-fan-out code; full apparatus only for
engine-math/golden changes), single-line floor every turn,
declared-vs-actual confirmed in every RESULT.
