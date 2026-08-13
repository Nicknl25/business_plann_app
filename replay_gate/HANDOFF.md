STATUS: awaiting-VS
TURN: 0/16
TASK:
  TURN-TIMEOUT-MINUTES: 240
  DURABLE FREEZE of the golden-leg input — Nick's one condition before he calls
  per-line COGS closed. Round 7's table is clean and honest, but the golden
  input is still DB-DERIVED: it picks a draft by query, so a prune, a restore,
  or a new draft landing can move it. A GOLDEN that depends on database state is
  not frozen, and blessing it would repeat the mistake just corrected — matching
  digests read as construction when they were coincidence.
  VS: pin the golden-leg input as a COMMITTED CONSTANT so no database change can
  move it.
  - Capture the chosen single-line draft's payloads ONCE and commit them as a
    literal frozen fixture, the way the R32 run artifacts were pinned. After
    this the golden legs must build from committed bytes with NO database query
    anywhere in the hashing path.
  - PROVE the property, do not assert it: show the digest reproducing with the
    database unreachable, so durable-by-construction is evidence.
  - Keep the determinism self-check and rot guard meaningful: the constant must
    be the REAL captured payload, never synthesized or trimmed, and its
    provenance (draft id, run id, checkpoint stage) recorded in the fixture.
  - Say plainly in the RESULT that round 8 digests are NOT comparable to rounds
    4-7 (the input changed identity when frozen) — expected, not drift.
  - Then run the full prove, post the file, and flip to awaiting-mini asking
    mini to re-audit the freeze: no DB call in the hashing path, fixture matches
    the checkpoint it claims, goldens still earn their rows.
  - Commit ONLY the files your task touches. A previous turn swept 408 unrelated
    files into one commit; stage explicit paths, never a bare index-wide add.
  Also settle the boundary the last cycle exposed: the R32 artifacts landed in
  replay_gate/ (mini's territory) because surface.py imports them relatively,
  contradicting the ownership law in both bootstrap prompts. State where frozen
  fixtures belong and make the import match, rather than leaving rule and code
  disagreeing.
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
