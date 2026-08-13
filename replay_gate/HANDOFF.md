STATUS: awaiting-VS
TURN: 0/16
TASK:
  TURN-TIMEOUT-MINUTES: 240
  DURABLE FREEZE of the golden-leg input — Nick's one condition before he
  calls per-line COGS closed. Round 7's table is clean and honest, but the
  golden input is still DB-DERIVED: it picks a draft by query, so a prune,
  a restore, or a new draft landing can move it. A GOLDEN that depends on
  database state is not frozen, and blessing it would repeat the mistake we
  just corrected — matching digests read as construction when they were
  coincidence.
  VS: pin the golden-leg input as a COMMITTED CONSTANT so no database
  change can move it.
  - Capture the chosen single-line draft's payloads ONCE and commit them as
    a literal frozen fixture, the way the R32 run artifacts were pinned.
    After this the golden legs must build from committed bytes with NO
    database query anywhere in the hashing path.
  - PROVE the property, do not assert it: show the digest reproducing with
    the database unreachable, so durable-by-construction is evidence.
  - Keep the determinism self-check and rot guard meaningful: the constant
    must be the REAL captured payload, never synthesized or trimmed, and
    its provenance (draft id, run id, checkpoint stage) recorded in the
    fixture itself.
  - Say plainly in the RESULT that round 8 digests are NOT comparable to
    rounds 4-7 (the input changed identity when frozen) — expected, not
    drift.
  - Then run the full prove, post the file, and flip to awaiting-mini
    asking mini to re-audit the freeze: no DB call in the hashing path,
    fixture matches the checkpoint it claims, goldens still earn their rows.
  Also settle the boundary the last cycle exposed: the R32 artifacts landed
  in replay_gate/ (mini's territory) because surface.py imports them
  relatively, contradicting the ownership law in both bootstrap prompts.
  State where frozen fixtures belong and make the import match, rather than
  leaving the rule and the code disagreeing.
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
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: _prove_20260812_ws1ws2_prove7.txt (R32 block line 1125);
    _prove_20260812_ws1ws2_prove7b_goldens.txt; VS_NOTES round-7 section
  SUMMARY: CLEAN TABLE, 50/50 - 43 behavioural + 5 structural-absence +
  2 GOLDEN + 0 DRIFT + 0 UNEARNED + 0 quarantine. R32 is GOLDEN: its
  COGS assertion is scoped to the FINMO sheet and now pins the SHAPE
  (one row, 21 legacy =<rev cell>*'Model Inputs'!<cell> cells all
  reading ONE driver row, 5 annual =SUM rollups, zero per-line rows).
  VS's diagnosis verified independently, including the fixture: its
  PLANNING_RUN_JSON digest-matches the finalize-validation checkpoint
  of run ddb61397 exactly.
  TWO GATE DEFECTS FOUND AND FIXED, both mine: (1) the golden legs were
  hashing a MOVING INPUT - the 6feac758 pin carries TWO product lines so
  it never qualified, and the silent fallback hashed whatever draft was
  written last; round 6 hashed Fernhill 5ce9bba8, minutes later the same
  call gave Sumac 8e84ba9d. A draft landing mid-prove would have fired a
  FALSE DRIFT. Now pin-then-oldest (created_at ASC) with the dead pin
  named in every evidence line, plus GOLDEN-SHA single_line_input so a
  divergent pick surfaces as a named DRIFT. Digests are NOT comparable
  to rounds 4-6. (2) The gate ENGINE was untracked - legs.py, surface.py,
  prove.py and the rest were never added to git, so no leg change was
  revertible or auditable. Committed.
  TWO THINGS NICK SHOULD KNOW, neither a red row: the golden input is
  now deterministic but still DB-derived (a prune moves it) - the
  durable freeze is one VS turn, TASK below; and a CONCURRENT session
  committed while my files were staged, so this round's gate work landed
  inside 6fc4382 ("Observability: heartbeat pulse") rather than its own
  commit. Nothing lost, history conflated. Two agents writing one index
  is a live hazard for this loop.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: freeze the golden legs' LAST live input. Capture ONE single-line
  draft that COMPLETED a planning run and embed its persisted sections
  (business_facts / operating_model / people / financials /
  financials_year1 / marketing) in replay_gate/_run_artifacts.py beside
  the run artifacts, same provenance stamp, same never-refresh rule.
  Use your existing generator (Test Files/_capture_workbook_fixture.py)
  - it already reads the right rows. Do NOT reuse 6feac758 for this:
  it carries two product lines and cannot serve a single-line control.
  Do NOT drop PLANNING_RUN_JSON while you are in there - the builder
  reads it twice (workbook_builder.py:54 boundary payload, and
  data.stage_ramp_contract -> schedule_sheets.py:99 quarter_ramp_grid,
  which resolves with 20 rows in your fixture and writes ramp VALUES).
  That is why dropping it leaves R32's grid byte-identical - invisible
  to R32, load-bearing for the workbook. If the file SIZE is what
  bothered you: the payload is 0.38 MB, not 2.8 MB; the 2.96 MB is
  pretty-printed repr inflation. Store the constants as compact JSON
  parsed at import and the file drops ~6x with zero digest risk.
  When it lands, mini re-points single_line_payloads at the fixture and
  deletes the candidate ladder - then the floor stops reading
  intake_consult_drafts at all.
