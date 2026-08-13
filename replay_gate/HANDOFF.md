STATUS: awaiting-Nick
TURN: 1/16
TASK:
  TURN-TIMEOUT-MINUTES: 240
  FINISH THE ROUND-9 TURN. Your last turn did the work — you re-pointed the
  golden legs at the frozen fixture and deleted the draft ladder (c292e5f) —
  but you launched the prove and then ENDED YOUR TURN while it was still
  running. Your session's children die with it, so the prove produced a 0-byte
  file and the watcher faulted on "exited without flipping STATUS". That
  0-byte artifact has been deleted.
  Do this now:
  - Re-run the full prove IN THE FOREGROUND and WAIT for it to finish. Never
    end a turn with a job in flight; if it would outlast your turn, return
    VERDICT: blocked and ask for a longer TURN-TIMEOUT-MINUTES instead.
      python -m replay_gate.run_gate --prove --tier full --verbose > _prove_<date>.txt 2>&1
  - Audit the durable freeze VS delivered in round 8, sceptically: that no DB
    call remains anywhere in the hashing path (VS poisoned the socket layer and
    mysql.connector and reports all four digests reproducing twice — verify
    that yourself rather than taking it), that the frozen constants are the
    REAL captured payloads with their provenance recorded, and that VS's second
    find is properly frozen too — build_python_model_input_json was reading 8
    reference tables live, 152 queries per build, now recorded as 74 keys with
    FrozenLookupMiss on anything unrecorded. Confirm a miss actually raises.
  - Confirm or refute VS's claim that round 7 -> 8 digests are IDENTICAL because
    the freeze captured exactly the draft the ladder already resolved to.
  - Then write the RESULT block and flip STATUS as your final act, in the same
    commit. Stage explicit paths only — never a bare index-wide add.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: R32:cogs-row-count-unscoped
  EVIDENCE: _prove_20260812_ws1ws2_prove6.txt (R32 block ~line 1125);
    replay_gate/_run_artifacts.py; VS_NOTES round-6 section
  SUMMARY: R32's frozen run artifacts are captured and committed from
  draft 6feac758 / stage post_intake_finalize_validation_completed --
  the same final-checkpoint row the byte-floor script reads. The
  payload carries capacity_labor_model, the exact gap round 5 named.
  Landed at replay_gate/_run_artifacts.py, NOT Test Files/, because
  surface.py imports it relatively; flagged in VS_NOTES.
  Round 6: 43 behavioural, 5 structural-absence, 1 GOLDEN (R31,
  digests unchanged from rounds 4/5), 0 DRIFT, 1 UNEARNED (R32).
  R32's grid now renders (4185 formulas, 7 sheets) with an IDENTICAL
  digest on both commits -- the negative control is earned. The one
  remaining red is a LEG BUG: it counts 'Cost of Goods Sold' across
  the whole grid, but the second row is the Model Inputs DRIVER row,
  not a duplicate P&L row. Not green: R32 stays quarantined.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: R32 is one assertion from GOLDEN. Scope its COGS-row count to
  the FINMO sheet before asserting -- the label legitimately appears
  on Model Inputs (driver row, =SUM(D12:G12)) and Audit Source (no
  formulas, never enters the grid). VS located all three rows; the
  FINMO P&L row is EXACTLY ONE and carries the documented legacy
  shape =C8*'Model Inputs'!C12. Single-line => one FINMO row labelled
  'Cost of Goods Sold'; multi-line => one 'Cost of Goods Sold - LINE'
  row per line plus a total =SUM over them. Full fix shape in the
  VS_NOTES round-6 section.
  Then re-run:
    python -m replay_gate.run_gate --prove --tier full --verbose > _prove_<date>.txt 2>&1
  Post the file and write your RESULT. Also answer one question in
  VS_NOTES so VS can act on it: does the workbook builder read
  planning_run_json at all? It is ~2.8 MB of the 2.9 MB fixture, and
  if it is unread VS will do ONE deliberate re-freeze that drops it.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: _prove_20260813.txt (counts at ~line 1990; R32 block ~1125,
    R31 ~1201); replay_gate/MINI_NOTES.md round-10 section
  SUMMARY: The prove ran to completion in the foreground this time and
  the table is clean: 43 proven behaviourally, 5 declared
  structural-absence, 2 GOLDEN, 0 DRIFT, 0 UNEARNED, 50 legs. R32 is
  out of quarantine — it asserts a real shape (one FINMO COGS row, 21
  period cells of the legacy driver formula, 5 SUM rollups, zero
  per-line rows) over 4,185 formulas.
  I did not take the round-8 freeze on VS's word. I made a database
  touch impossible rather than counting it — connect, socket, and
  cursor on both gate connections all raise — and the golden paths
  still produced all four digests byte-identical to the prove. The
  frozen payloads were re-queried live and match by sha256, all 97
  columns of the input draft included. Mutating the recorded lookups
  moves the digest and restoring returns it exactly, so the fixture is
  load-bearing, not decoration. FrozenLookupMiss fires on an
  unrecorded key, and both golden legs refuse to hash a hollow
  artifact instead of hashing it.
  Round 7 -> 8 digests are IDENTICAL: confirmed, three prove runs plus
  one out-of-band reproduction.
  Answering VS's open question: the workbook does NOT read
  planning_run_json — the grid digest is unchanged with it emptied.
  It is 28% of the fixture, not the 97% the round-6 task guessed;
  LOOKUP_REPLAY is the big one at 55%.
  Behaviour 10 is settled and passing: HANDOFF_ALLOW_COMMIT was 1 in
  my first tool shell, so the watcher's env fix does reach the agent
  and the explicit override can go away.
  For Nick, in plain English: the gate is clean and the golden legs
  now build from committed bytes, so they can no longer cry wolf when
  the database moves underneath them. It is safe to spend a Cowork
  run. Nothing needs flipping or editing by you.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: nothing is blocking. Three follow-ups, in order, and read
  replay_gate/MINI_NOTES.md first — that is mini's side of the notes
  channel, the mirror of VS_NOTES.md, and it carries the evidence for
  everything below.

  1. ONE deliberate re-freeze that drops PLANNING_RUN_JSON. Proven
     unread by the grid path (ok=True, sha cbd76463 unchanged with it
     set to {}); it is 359,636 bytes, 28% of the fixture file. Re-run
     --prove --tier full afterwards: "no digest moves" is the claim,
     so it has to be shown, not assumed.
  2. Close the lru_cache blind spot with the cheap durable fix mini
     proposed and you have not built yet: have the capture record
     which loaders were actually SERVED during the recording build,
     and have prime_frozen_lookups() report the served count, so a leg
     can refuse when a loader that used to serve goes silent. Two of
     the eight are warmed by a live read at import and patching cannot
     undo a memo — inert today, a silent trap tomorrow.
  3. Take one look at the finmo GOLDEN-SHA. Mutating the industry
     baselines moves model_input and leaves finmo unmoved. Probably
     benign, but a negative control nobody has seen move is not yet a
     control. If it is genuinely insensitive by construction, say so
     in the docstring and stop calling it a second instrument.

  Also fix two lines in VS_NOTES.md that are slightly wrong (neither
  is a defect, both will mislead the next reader): 6 of the 18
  recorded _query_cohort_rows results ARE empty — legitimately, they
  are the narrow revenue windows of the band-widening ladder — so the
  claim to make is "no loader recorded nothing", not "no key". And
  behaviour 10 now passes; the note still calls it unexercised.
