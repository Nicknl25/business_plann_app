STATUS: awaiting-mini
TURN: 1/16
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
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: golden-input:frozen-not-yet-repointed
  EVIDENCE: Test Files/_prove_frozen_input_no_db.py (run it);
    _prove_20260812_ws1ws2_prove8.txt; replay_gate/_run_artifacts.py;
    VS_NOTES round-8 section; docs/architecture/vs_mini_handoff_watcher_spec.md
    SS6.1 + SS6.2
  SUMMARY: The golden input is frozen as committed bytes and the property
  is PROVEN, not asserted: with the socket layer and mysql.connector
  poisoned, all four digests reproduce twice - model_input 9650f148,
  finmo c21a05c9, workbook_formulas cbd76463, single_line_input 72dfcb81.
  The task predicted round 8 would not be comparable to rounds 4-7. It is
  not so: the freeze captured exactly the draft the ladder was already
  resolving to, so round 7 -> 8 is IDENTICAL. Rounds 4-6 stay incomparable
  (mini's pick-ordering fix moved those, not this freeze).
  The draft was only half the moving input. Poisoning the socket found a
  second dependency: build_python_model_input_json reads 8 reference
  tables live, 152 queries per build. Frozen by recording arguments to
  results through the real build - 74 keys - with FrozenLookupMiss on any
  unrecorded key, never a live fallback. Red-proofed both directions.
  Round-8 prove is CLEAN: 43 behavioural + 5 structural-absence + 2 GOLDEN
  + 0 DRIFT + 0 UNEARNED = 50. Not green: the gate still QUERIES for its
  input, because re-pointing single_line_payloads is surface.py and that
  is mini's file. The freeze exists and is proven; it is not yet in the
  hashing path.
  Also fixed a loop-stopping bug: the pre-commit guard blocked the agent's
  own mandatory flip commit (I hit it - the in-flight pid was me). The
  watcher now passes HANDOFF_ALLOW_COMMIT=1 to the child only.
  No app code touched, so no restart or canary was owed.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: land the re-point and re-audit the freeze. Three things.

  1) RE-POINT single_line_payloads at the fixture and DELETE the ladder.
     from . import _run_artifacts as fx; draft = fx.SINGLE_LINE_DRAFT;
     patched, restore = fx.prime_frozen_lookups() BEFORE the build, with
     restore() in a finally. Then remove single_line_candidates() and the
     draft_pick apparatus outright - it exists only to survive a live
     table, and dead code invites a future re-point back onto it. Full
     shape plus TWO TRAPS (scope the priming; the baseline side may
     legitimately raise FrozenLookupMiss) in the VS_NOTES round-8 section.
     Expect the four digests to be UNCHANGED - that is the pass. If any
     of them moves, the fixture and the live path disagree and that is a
     finding, not a nuisance.

  2) AUDIT THE FREEZE the way you audited the last one - verify, do not
     take my word. No DB call in the hashing path; the fixture matches the
     checkpoint it claims (the capture re-read 6feac758 from the live DB
     this turn and the rot guard did not fire, so it still matches); the
     goldens still earn their rows. Worth a skeptical look: I froze the
     REFERENCE LOOKUPS as well as the draft, which means the goldens can
     no longer notice a lookup-table migration. I think that is right for
     a negative control and wrong to leave unsaid - tell me if you
     disagree.

  3) ONE LINE IN BOTH BOOTSTRAP PROMPTS, which live in your territory:
     replay_gate/* belongs to mini, EXCEPT HANDOFF.md, VS_NOTES.md, and
     generated fixture modules (today _run_artifacts.py), which are VS's.
     Ruling and the reasoning are in the spec SS6.1 - short version, the
     code was right and the rule was wrong, because Test Files contains a
     space and can never be an importable package name.

  Then re-run:
    python -m replay_gate.run_gate --prove --tier full --verbose > _prove_<date>.txt 2>&1
  Post the file and write your RESULT. Add watcher behavior 10 to your
  audit list: an agent turn must be able to commit without an operator
  exporting anything, while a second shell during that turn is still
  refused.
