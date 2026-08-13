STATUS: awaiting-mini
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
