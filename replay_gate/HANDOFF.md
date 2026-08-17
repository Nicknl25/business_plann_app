STATUS: awaiting-mini
TURN: 1/16
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
