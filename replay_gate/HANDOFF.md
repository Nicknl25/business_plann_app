STATUS: awaiting-VS
TURN: 0/16
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
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
