STATUS: awaiting-Nick
TURN: 2/16
TASK:
  FIX THE DISCOVERY READER THE RIGHT WAY — Nick's ruling 2026-08-17:
  OPTION A, CONVERGE ONTO THE SHARED READER AND DELETE THE PARALLEL ONE
  (delete, do not demote). Research with every citation:
  docs/DISCOVERY_READER_DIVERGENCE_RESEARCH.md (read it first; the code
  map and the Corvid evidence are there). DEAL BREAKER: on Corvid Press
  (draft e3af1f24) "digital printing is already part of our commercial
  print line, not a separate thing" made a phantom own-LOB line with a
  false receipt, and "drop that line, you'd be double-counting" was
  ignored - the null-driver row survived finalize via the carry-forward
  and killed the run at the boundary. Root: discovery built its OWN
  per-candidate yes/no reader instead of using consultant_chat_turn - the
  reader the whole rest of the intake uses, which already has
  merge/collapse authority. The good reader was there and got overridden.
  Use it. Delete the garbage. FIX THE CLASS.
  TURN-TIMEOUT-MINUTES: 180
  DELETE (the actual defect - a parallel comprehension engine):
   1. read_stream_discovery_answer + the per-candidate ACCEPT/REJECT/
      CLARIFY loop through _classify_restatement_response
      (gpt_stream_discovery.py ~:652-680, stream_discovery_intent_frame
      ~:616-646, _DOOR_TO_ANSWER :649; the door use in intake_consult.py
      _apply_stream_discovery_answer ~:11773-11866). Discovery no longer
      runs its own per-candidate boolean pass. _classify_restatement_
      response has other (restatement) callers - leave it for them; stop
      discovery calling it. If any discovery-only helper becomes dead,
      delete it (remove-don't-route-around law).
   2. append_confirmed_stream_rows (~:725-756) - the unconditional own-LOB
      minting. Delete the bespoke applier. Whatever the SHARED reading
      actually added gets origin=discovery_confirmed stamped (stamp only;
      the shared patch adds the row).
  CONVERGE:
   3. consultant_chat_turn (intake_consultant.py) is the PRIMARY reader of
      the discovery-window reply. It already receives the full conversation
      + the latch (+ stream_discovery_note) and returns a full lob_models
      snapshot; its prompt already carries "THE CLIENT IS THE FINAL
      AUTHORITY ... 'treat them as one' collapses a proposed split - honor
      it immediately" (:276). Let it comprehend natively: "stays inside
      commercial print" -> no new row; a genuine new stream -> real line
      added (product row w/ null drivers, then the normal cascade captures
      it); "drop that line" -> row removed. Give the shared reader the
      discovery context it needs to do this WELL (the note/latch already
      ride in intake_context; make sure the prompt/context tell it, in
      plain terms, that the ask just proposed these labels as possible
      revenue lines, that a yes means add a line, and that the client may
      say a proposed stream is already inside an existing line - keep it
      inside; may decline; may retract a line just added - remove it) and
      that its lob_models snapshot is authoritative for those decisions.
      Reconcile :426 "do not drop them" so an explicit client removal of a
      discovery-added (or any client-retracted) line is honored - the
      client is the authority (parent law) - without turning carry-forward
      of legitimately-known products into silent drops.
  JUSTIFY-OR-DELETE:
   4. carry_stream_discovery (~:764-850, called at ~:20357 every ops turn
      and at both finalize sites :19725 / :21077). Its legitimate job is
      surviving consultant_finalize's wholesale ops_json replacement (like
      competitive_advantage's rescue); its bug is rebuilding "confirmed"
      from answer=="yes" alone and resurrecting dropped rows (:779-783,
      :830-844). DETERMINE: if the shared reader's snapshot now carries
      discovery lines correctly through finalize, DELETE it. If finalize
      still erases a legitimately-added discovery line, FIX it - carry
      forward ONLY what the shared model actually contains (respect
      removals/merges), NEVER resurrect from a stale yes-latch. State which
      (delete vs fix) and why in the RESULT.
  ALSO FIX (the second-order bug that produced the exact failure):
   5. The wrap gate (~:20501-20509 gate_obj from a fresh consultant_finalize
      snapshot never passed through carry-forward) must evaluate the SAME
      row set that gets persisted - gate on the persisted ops_json, or
      carry the same state through the gate snapshot - so the gate and the
      persisted state can never disagree. No null-driver discovery row can
      reach validate_intake_draft_at_boundary (the phantom-line class is
      dead by construction).
  KEEP untouched: the proposal/judge side (evidence gate, judge, band-gate,
  F1 dedup, F2 size-strip, F3 cap-4, template + why-clause + serial
  comma, the ask at the seam) - that is discovery working. The LATCH as
  an auditable record stays - but its per-label answer now records what
  the SHARED reader did (added / merged_into:<line> / declined /
  removed), written from the shared model's outcome, not a boolean door.
  D3 (judge proposing a sub-category of a stated line) is SEPARATE and
  PARKED - not this turn. EMAIL / DELIVERY PATH OFF-LIMITS (fence).
  VERIFY at artifact level - red-proof on the EXACT Corvid transcript
  (e3af1f24, msgs 22-26) BOTH failing cases: (a) "already part of our
  commercial print line, not a separate thing" -> NO phantom line, honest
  receipt (stays inside the existing line), model has 2 lines not 3,
  latch records merged_into; (b) "drop that line, you'd be double-
  counting" (on a clone where a line WAS created) -> row removed, NOT
  resurrected at the next turn or at finalize, latch records removed, no
  null-driver row at the boundary. AND the WORKING case still works -
  Nine Fathom shape (6d2823db, "Yeah, we do sell retail coffee bags ...
  And yes, we do wholesale ... But no, we don't do brew gear") -> the two
  genuine yeses land as real discovery_confirmed rows captured through
  the cascade, the no is not added; deleting the second reader must NOT
  break the case that already works. Live: rewound Corvid + Nine Fathom
  clones through the real handler on a restarted backend (ONE :5050
  listener). Floor R31/R32 via --only. Declare the tier per fix in your
  TURN PLAN (this sits on the finalize/carry-forward/wrap-gate seam -
  likely NEIGHBOR-CHECK; the reader-primacy delete vs the carry-forward/
  gate change may be different radii - SPLIT per the law if so, land the
  reader convergence first) and confirm declared-vs-actual. Flip to mini.
  MINI: audit at the tier VS declared (verify the call): the parallel
  reader is GONE (grep: no per-candidate classify loop, no
  append_confirmed_stream_rows, no discovery call into
  _classify_restatement_response); the shared reader is the one binding
  authority; carry_stream_discovery deleted-or-fixed with the reason
  stated and, if kept, never resurrects a removed row; the wrap gate and
  persisted state agree on the Corvid clone; the three artifact cases
  (merged / removed / genuine yes) PRE red POST green; zero email lines
  touched; floor. Green -> stop -> Nick re-runs Cowork.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none-discovery-convergence-landed-awaiting-mini-audit
  EVIDENCE: replay_gate/VS_NOTES.md (section DISCOVERY READER CONVERGENCE, 2026-08-17); Test Files/_discovery_reader_convergence_redproof_20260817_POST.txt; Test Files/_live_discovery_corvid_clone_20260817_PRE_A.txt / PRE_B.txt (RED) and POST_A.txt / POST_B.txt / POST_A_final.txt (GREEN); Test Files/_live_discovery_ninefathom_answer_clone_20260817_POST.txt (GREEN); Test Files/_live_discovery_ninefathom_clone_20260817_POST.txt (GREEN); _handoff/tmp/floor_R31_R32_20260817.txt (2/2 GREEN); docs/STREAM_DISCOVERY_SPEC.md Q5 (re-ruled section)
  SUMMARY: Option A BUILT. The parallel per-candidate reader and the own-LOB
  applier are DELETED (read_stream_discovery_answer / intent frame /
  _DOOR_TO_ANSWER / append_confirmed_stream_rows / new_discovered_row /
  _apply_stream_discovery_answer; discovery no longer calls
  _classify_restatement_response); consultant_chat_turn is the ONE reader
  (window opener only decides the reply IS the answer; note + prompt section
  + removal rule + patch.stream_discovery_outcomes; snapshot authoritative);
  Python records the outcome FROM STATE (origin stamp, latch added /
  merged_into:<line> / declined / unclear / removed, receipt). carry_stream_
  discovery FIXED not deleted (latch + provenance survive finalize's wholesale
  replace; resurrection gone; finalize carries only the shared model's own
  FILLED row); wrap gate aligned to the persisted discovery row set. Corvid
  A+B PRE RED -> POST GREEN on the exact transcript through the real handler,
  Nine Fathom genuine-yes still lands + cascade captures, floor R31/R32 GREEN,
  declared neighbor-check == actual, zero email lines. Two triage flags
  (T1 drop-turn price clobber + lost numeric echo; T2 862.5 vs 690 stored
  price) recorded in VS_NOTES - not built.
TASK:
  MINI - audit at NEIGHBOR-CHECK (VS's declared tier; verify the call):
  1. The parallel reader is GONE: grep python/ for read_stream_discovery_answer,
     stream_discovery_intent_frame, _DOOR_TO_ANSWER, append_confirmed_stream_rows,
     new_discovered_row, _apply_stream_discovery_answer -> zero hits; the only
     _classify_restatement_response callers are the restatement ones (:11906 def,
     :16938 call); no per-label classify loop anywhere in the discovery window
     (_open_stream_discovery_window .. _is_guardrail_acknowledgement).
  2. The shared reader is the one binding authority: intake_consultant.py carries
     the Stream discovery prompt section, the removal rule (ONE exception to
     "do not drop"), stream_discovery_outcomes in schema + required; intake_consult
     ops patch block calls record_stream_discovery_outcomes AFTER
     _apply_model_ops_patch, then carry_stream_discovery (no restore) +
     note_stream_discovery_removals; the receipt is composed from state and
     leads the reply; the clarify path (ONE clarify) still holds the turn.
  3. carry_stream_discovery: kept-and-fixed with the reason stated (latch outside
     every GPT schema + provenance); confirm on the Corvid B clone artifact
     (POST_B.txt) that a removed row never returns across 5 turns + finalize and
     that finalize restore only fires from a FILLED before-row (offline redproof
     section 4: null-driver before-row -> nothing; yes-latch-no-row -> nothing).
  4. Wrap gate == persisted: align_gate_rows_with_persisted right after
     consultant_finalize in the gate; offline redproof sections 2/3/4 show both
     directions; on the Corvid B live artifact the wrap fired only after the row
     was gone (competitive advantage on the drop turn), and no null-driver row
     reached the boundary (focus market, rows 690/30 + 420/9).
  5. Three artifact cases PRE red POST green: Corvid A (merged) PRE_A 7 red ->
     POST_A green; Corvid B (removed) PRE_B 11 red -> POST_B green; Nine Fathom
     genuine yes (6d2823db msg 25) POST green with cascade capture 19/260/.6 +
     13/140/.55. Re-run any of them yourself against the running :5050 (final
     build) if you want a fresh artifact - clones self-delete.
  6. Zero email/delivery lines touched (git diff names no workbook_email /
     notify / delivery file). Floor R31/R32 GREEN via --only.
  7. Consider a gate leg for this class if it fits your leg law: the offline
     redproof (Test Files/_discovery_reader_convergence_redproof.py) is the shape -
     a NEGATIVE control that a persisted null-driver discovery row cannot pass
     wrap-readiness and that a removed row is never re-appended by carry.
  Nick's triage (NOT built, named in VS_NOTES): T1 the drop-turn unit_price=30
  clobber on both real lines + lost numeric echo when the gate cascade replaces
  assistant_text (PRE and POST alike - pre-existing); T2 stored 862.5/567 vs
  client-stated 690/420 on Corvid. D3 (judge sub-category) stays PARKED.
  Green -> awaiting-Nick -> Nick re-runs Cowork on Corvid Press.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_mini_audit_discovery_convergence_20260817.txt (R48 --prove PROVEN behaviourally: RED at b8f2697 "ordinary-turn carry re-appended the removed discovery row (latch answer 'yes')" -> GREEN at HEAD; R48+R31+R32 3/3 clear); replay_gate/legs.py R48 discovery-removed-never-resurrected (new, 66 legs); offline redproof re-run in the foreground GREEN (Test Files/_discovery_reader_convergence_redproof.py); artifacts read: _live_discovery_corvid_clone_20260817_PRE_A (7 red) / POST_A (green) / PRE_B (11 red) / POST_B (green), _live_discovery_ninefathom_answer_clone_20260817_POST (green); grep negatives on python/; git diff --name-only bd1a541~1..bd1a541 (no email/notify/delivery file)
  SUMMARY: AUDIT AT NEIGHBOR-CHECK (VS's tier call verified honest: the change
  sits on the ops-turn/finalize/wrap-gate seam + the shared reader's prompt;
  no engine math, no golden -> not full; not spot-check because the prompt
  removal rule + carry rides every ops turn). All 7 task items HOLD:
  (1) parallel reader GONE - zero hits for read_stream_discovery_answer /
  stream_discovery_intent_frame / _DOOR_TO_ANSWER / append_confirmed_stream_rows /
  new_discovered_row / _apply_stream_discovery_answer; _classify_restatement_
  response has exactly the two restatement sites (:11906 def, :16938 call).
  (2) shared reader binding: prompt "Stream discovery" section + removal rule as
  the ONE exception to do-not-drop; stream_discovery_outcomes in schema+required;
  ops patch block: _apply_model_ops_patch -> record_stream_discovery_outcomes ->
  carry_stream_discovery (no restore) -> note_stream_discovery_removals -> receipt
  leads; ONE clarify holds the turn (:20313). (3) carry KEPT+FIXED, reason
  stands (latch lives outside every GPT schema, erased by finalize's wholesale
  replace; origin is Python's provenance); resurrection gone - confirmed on
  POST_B (row gone on the drop turn, absent across 5 turns + finalize, latch
  'removed' survives finalize) and offline (null before-row -> nothing; yes-latch-
  no-row -> nothing; FILLED before-row carried from itself). (4) wrap gate ==
  persisted via align_gate_rows_with_persisted right after consultant_finalize
  (:20503); both directions proven offline; POST_B boundary rows 690/30 + 420/9,
  no null-driver row. (5) three cases PRE red -> POST green read from the
  artifacts (Corvid A merged_into:Standard commercial print job + honest receipt,
  2 lines; Corvid B removed; Nine Fathom added/added/declined + cascade 19/260/.6
  and 13/140/.55). (6) zero email lines; floor R31/R32 GREEN by my own --only.
  (7) GATE LEG ADDED: R48 discovery-removed-never-resurrected (fast, offline, no
  GPT/DB): ordinary-turn omission never re-appended (yes + added latch), finalize
  seam mints nothing from the latch and never restores a null-driver row, gate
  carries a persisted null-driver discovery row and strips one the persisted
  model lacks; positive controls present-in-both stamp + filled-before-row carry.
  Proved RED on b8f2697 for the RIGHT reason (first attempt was CRASH-RED on a
  new-only helper - the prove harness caught it, re-fixtured to a local finder,
  now PROVEN behaviourally). VS DECLARED-vs-ACTUAL: matched (watcher.log
  10:34:35 plan = neighbor-check, named neighbors a/b/c all evidenced in
  VS_NOTES; loaded files == declared). Bundle: reader delete + carry/gate change
  in one turn is the SAME discovery-only seam (align early-returns without an
  asked latch) - not a mixed-radius bundle, no process finding. MY DECLARED-vs-
  ACTUAL: matched (neighbor-check; offline redproof + artifacts + greps + floor;
  canary skipped; legs R31/R32 + new R48).
  TRIAGE (this RESULT closes them; nothing queued as auto-work):
  - T2 (stored 862.5/567 vs stated 690/420 on Corvid e3af1f24): WONT-FIX -
    design working. Read the source transcript: msg 100 offered the market
    ceiling ($862.50 / $567.00), msg 107 "Let's go with option 2 - the top of
    what your market pays" - the client CHOSE those prices in the coherence
    walk; utilization .528/.44 = .66/.55 x 80% retention the client gave at
    msg 109. Not a wrong number.
  - Nine Fathom placement (wholesale row nested under the retail LOB): WONT-FIX/
    watch - the engine consumes product rows; LOB placement is the shared
    reader's call now; no number moves.
  - Ordinary-turn model OMISSION of a discovery row = recorded+said removal
    (parity with every other line, which has only the prompt guard): WONT-FIX/
    watch - the receipt is truthful ("dropped as a separate line") and the
    client can correct; the ruling made the shared reader the authority.
  - T1 (drop-turn unit_price 690->30.0 written onto BOTH real lines from "30
    commercial print jobs a week", PRE and POST alike, echo lost when the gate
    cascade replaced assistant_text): NEEDS-RULING - a wrong number WAS stored on
    the guided path on a real client-shaped turn; it self-healed only because
    the model happened to re-confirm $690/$420 over the next two turns; the
    existing _guard_underivable_ops_lever_writes ran and let it through (the
    figure "30" appears in the message). If it had not been re-confirmed a $30
    price would have reached the plan. Named guard gap; see TASK.
TASK:
  NICK: the discovery reader convergence is AUDITED GREEN - Cowork can be
  re-run on Corvid Press (fresh tab, :5173/business-plan-form). One decision
  for you (plain English is enough): T1 above - a correction-turn snapshot
  clobbered a captured price with a capacity figure and the underivable-lever
  guard passed it. If you say "chase T1", the next VS turn is:
  VS (T1, only if Nick says go) - NEIGHBOR-CHECK (touches
  _guard_underivable_ops_lever_writes, which every ops turn flows through):
  1. Reproduce deterministically: replay Corvid B clone drop-turn (msg 25 on
     messages[:25], Test Files/_live_discovery_corvid_clone.py case B) and
     assert unit_price stays 862.5/567.0 (or the client's stated 690/420) on
     the two real lines after the turn - PRE red (30.0/30.0 per POST_B.txt).
  2. Determine WHY the guard passed a price rewrite whose only "derivation" is
     a capacity count in the message; fix at the guard (a captured unit_price
     may only move on a turn whose message states a price/dollar figure or
     an explicit price correction) - no new behavior, no engine math.
  3. Deal breaker named: a $30 stored price for a $690 job reaches the
     workbook if the model does not happen to re-ask. Neighbors: R30 price-
     change-stamps-retention, I01/I07 forward-move:price/ack-matches-stored,
     R44 via --only; floor R31/R32; canary skip. Flip to mini.
  D3 (judge sub-category) stays PARKED. EMAIL/DELIVERY PATH OFF-LIMITS.
