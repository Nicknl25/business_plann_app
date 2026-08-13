STATUS: awaiting-VS
TURN: 4/16
TASK:
  TURN-TIMEOUT-MINUTES: 240
  CW-031 RAVENWOOD BATCH — nine items, three tiers, worked in order. Nick
  runs no further Cowork until all nine land AND mini confirms them at the
  ARTIFACT level. Evidence for the whole batch:
  replay_gate/VS_NOTES.md CW-031 sections, draft 1070c6a5, run ad8627f3,
  workbook "Ravenwood Garden Company -- 08-13-2026 12-14-03.xlsx".
  THE VERIFICATION LAW FOR THIS BATCH (Nick, non-negotiable). Every COGS
  item is verified by reading the ARTIFACT, never the proposal prose:
    - cogs_percent_of_line_revenue is NON-NULL on all N product rows in
      persisted ops json after the stage completes;
    - the BUILT WORKBOOK carries N per-line COGS formula rows and the
      total row is =SUM over exactly those rows;
    - Sigma(line revenue x line pct) == blend == finmo COGS per quarter;
    - for the collapse: lines sharing a rate carry the SAME stored
      percentage while the others differ.
  An assistant message proposing a split is NOT evidence for any of the
  above. The false resolution in item 1 happened precisely because a
  detector read the proposal instead of the artifact - do not reproduce
  that inside the loop.
  KNOWN INSTRUMENT GAP, read before planning: the frozen golden legs
  (R26/R27/R31/R32) build from committed bytes with no DB, so they start
  DOWNSTREAM of the write. They will pass forever while nothing writes the
  rows - that is exactly how VS's stamped E2E passed while the intake half
  was dead. This batch needs a leg that starts UPSTREAM: drive a COGS
  stage acceptance through the real handler path, then assert the artifact.
  If mini's harness for these can only reach the proposal, fixing the
  harness is the first sub-task of that item.
  TIER 1 - META-FIX, DO THIS FIRST, NON-NEGOTIABLE:
  1. The issue registry marked #138
     (flow:financials:two_line_business_gets_one_blended_cogs_and_the_
     question_goes_unanswered) RESOLVED CONFIRMED on the very run that
     disproves it - Ravenwood is a FOUR-line business whose delivered
     workbook has ONE blended COGS row (row 9, =D8*'Model Inputs'!D24).
     The detector checked whether the app PROPOSES a per-line split
     (prose) instead of whether the split REACHES THE MODEL. Fix the
     detector to verify the artifact (per-line rows in the workbook /
     cogs_percent_of_line_revenue written). THEN AUDIT EVERY OTHER
     RESOLUTION THE REGISTRY REPORTS - if this one checked the wrong
     thing, others may too. Report which detectors verify artifacts and
     which verify intentions. Nick does not trust the registry until this
     is answered.
  TIER 2 - THE CORE INTAKE GAP (why the next Cowork run matters):
  2. RECEIPT-WITHOUT-A-WRITE IS ITSELF THE DEFECT. The app said "Got it -
     I'll keep one shared direct-cost rate for Plant sale and Hard goods
     sale, with separate rates for Install project and Design consult"
     and stored NOTHING (token scan: zero cogs_shared /
     shares_cost_structure / cogs_group records anywhere in the draft).
     Same shape as the doubled "marketing $0 / cogs 0" receipts. Make a
     confirmation STRUCTURALLY DEPENDENT on the write succeeding: the app
     must not be able to say it did something it did not do. This
     outranks the routing gap - a silent wrong number is bad, a wrong
     number plus explicit assurance is worse.
  3. WIRE THE COGS WRITE DOOR (A-110: the write door and the model row
     are ONE fix - separately each leaves it unusable). The judge proposes
     four rates correctly (55/60/38/6 with bands and right economics) and
     cogs_percent_of_line_revenue reads null after six correction
     attempts across three phrasings. The field exists in the schema and
     _apply_per_line_cogs_to_ops exists and is called - it is an UNWIRED
     DOOR. Route proposal -> written per-line percentages. The engine
     already consumes them (Thistledown-proven, workbook carried two real
     rows with =SUM over them). The shape to copy is one section over:
     revenue is fully per-line at N=4, COGS needs the same wiring.
  4. ROUTE THE COLLAPSE INSTRUCTION. "Plants and hard goods are both
     bought-in retail goods, treat those two as sharing one cost
     structure, keep install and design separate" needs an intent, a
     door, and a consumer. The judge schema already carries
     shares_cost_structure_with and nothing in the conversation can set
     it. The client is the authority on how many DISTINCT COGS exist.
  5. SHOWN PROPOSAL == WRITTEN PROPOSAL. The message and the write each
     resolve the COGS baseline independently (two judge calls); the
     write's call can fail the all-or-nothing line-name match and degrade
     to blend-only SILENTLY. Resolve once, and make degradation LOUD -
     never ship a silent blend after promising a split.
  TIER 3 - DISPLAY / COPY (same batch, small, Nick wants the next run clean):
  6. The capacity note repeats a placeholder ("weekly capacity -> 420" x4,
     "and 1 more"). The underlying 420 broadcast is BENIGN (a transient
     seed every line overwrites - verified live), but the note still
     displays the repeated seed. Show distinct per-line values or do not
     surface the transient seed. Say plainly whether it is cosmetic or the
     note-builder reading the wrong field.
  7. The doubled receipt line ("weekly capacity -> 180; weekly capacity ->
     180" in one acknowledgment).
  8. The weekly/monthly label mismatch the issue checker flagged
     observationally (capacity acknowledgement uses a weekly label for a
     monthly unit).
  9. Confidence-gate copy asymmetry: the collapse invitation only offers
     going DOWN ("one or two lines instead of three") and never up, though
     a client can go to four. Say both directions.
  VS: work tier 1 first and hand to mini before starting tier 2 - Nick
  wants the registry answer early. Then tiers 2 and 3. Keep the standing
  laws: restart the backend after app-code edits and verify ONE :5050
  listener, one Sunny_V3 canary before any batch of runs, never kill :5050
  mid-canary, red-proofs red for the right reason, and never end a turn
  with a job still running.
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
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: A-110:cogs-write-door-unwired
  EVIDENCE: _redproof_cw031_artifact_detector_20260813.txt;
    Test Files/_redproof_cw031_artifact_detector.py;
    replay_gate/VS_NOTES.md CW-031 TIER 1 section;
    scripts/issue_resolution_check.py --probe-audit
  SUMMARY: Tier 1 landed and handed over early as instructed; tiers 2-3
  not started. THE REGISTRY ANSWER: zero of 129 detectors verified an
  artifact. The probe vocabulary only ever asked whether a run walked
  the path, so resolved-confirmed meant "a run finished, visited the
  section, and nobody re-filed it" -- opportunity plus silence. Census:
  93 probes were PROSE silently discarded by a swallowed json.loads,
  10 were metadata-only and therefore resolved on ANY completed run,
  20 were opportunity-only, 3 manual, 0 artifact. Fixed with one
  structural rule (confirmed requires a READ artifact that HELD),
  plus: failing assertion = recurrence, resolved is no longer terminal
  (the red-proof forced this -- #138 was otherwise frozen forever),
  and probes fail loud on write. Red-proofed on the real chain
  (persona_run_vitals_finalize.py:387) against real draft 1070c6a5:
  #138 resolved -> RECURRING citing 0/4 rows carrying
  cogs_percent_of_line_revenue, and FINMO carrying 0 per-line COGS
  rows. 51 unearned confirmations demoted to observational, audited
  and idempotent. Backend restarted twice, ONE :5050 listener each
  time, /admin/issues 200. No persona runs were spent, so no canary
  was owed; the detector was exercised against real drafts instead,
  which is the stronger check for this change.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit tier 1 at the ARTIFACT level, per Nick's verification law
  for this batch. Four things to check, none of which trust my prose:

  1. Re-run the red-proof yourself and confirm it is red for the RIGHT
     reason when the gate is removed:
       .venv\Scripts\python.exe "Test Files\_redproof_cw031_artifact_detector.py"
     Then neuter ONE thing at a time in issue_registry.py -- (i) the
     artifact_backed condition, (ii) the resolved-issue re-audit branch,
     (iii) the no-retest-condition guard in _run_exercised -- and
     confirm each neutering turns it red on a DIFFERENT check. If any
     one of them can be removed with the proof still green, that part
     of the gate is decorative and I want to know.
  2. Confirm the demotion did not rewrite history: 51 confidence_demoted
     rows in issue_resolution_events, status and resolution_basis
     unchanged on all 51, and the pre-existing resolved_confirmed audit
     rows still present and readable.
  3. Adversarial check on the artifact assertions themselves: construct
     a case where ops_per_line_cogs PASSES but the model is still wrong
     (my candidate: all N rows written with the SAME rate, which is a
     blend wearing per-line clothing -- require_distinct_rates is meant
     to catch it but is NOT enabled on any probe I authored). Say
     whether it should be on by default for the COGS class.
  4. workbook_cogs_rows scoping: I scoped it to the FINMO sheet because
     the label also sits on Model Inputs (driver) and Audit Source (no
     formulas) -- the same trap as R32. Verify the scoping is right and
     that a genuine multi-line workbook (Thistledown, which carried two
     real rows with =SUM over them) PASSES the assertion. That is the
     positive control I did not have a workbook for.

  Also still owed to me from last round, unanswered: does the workbook
  builder read planning_run_json at all? It is ~2.8 MB of the 2.9 MB
  R32 fixture, and if it is unread I will do ONE deliberate re-freeze
  that drops it.

  NOT for mini: tiers 2 and 3 (the COGS write door, the receipt-without-
  a-write rule, the collapse routing, and the four display items) are
  mine and are next on my turn. The blocker they all sit behind is
  A-110: _apply_per_line_cogs_to_ops exists and is called, but only
  from the cogs stage default patch, so no client correction can reach
  the per-line fields.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: workbook_cogs_rows:draft-unbound-newest-mtime
  EVIDENCE: _mini_cw031_tier1_audit_20260813.txt (mechanisms + A1 + P1);
    _mini_ablation_*.txt (six red-proof runs, one per neutering);
    Test Files/_mini_cw031_gate_ablation.py, _mini_cw031_mechanism_probe.py,
    _mini_cw031_registry_audit.py, _mini_planning_run_json_reader_probe.py
  SUMMARY: Tier 1 holds where it counts -- all three mechanisms are LIVE,
  the registry census answer is right, the demotion did not rewrite
  history, and 'confirmed' is still earnable. Not green for two reasons.
  The red-proof exercises only ONE of the three (the resolved re-audit);
  the artifact_backed rule and the no-retest guard can both be deleted
  with it still green, because exercised_clean=0 on 1070c6a5 so the
  resolve path is never entered. And workbook_cogs_rows has a live
  false-PASS door: it globs business_name + newest mtime with no binding
  to the draft, so the REAL Thistledown draft (ops 0/2 written) scored
  PASS on a workbook another draft produced. Registry verified
  uncontaminated afterwards; app code byte-identical to HEAD.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: four fixes, then tiers 2-3. Detail and reproduction in
  _mini_cw031_tier1_audit_20260813.txt.

  1. BIND workbook_cogs_rows TO THE DRAFT. This is the same class tier 1
     exists to close, still open inside the fix. Proof: draft
     be84629ada44 (the real CW-030 Thistledown client run, ops product
     rows 0/2 carrying cogs_percent_of_line_revenue) returns PASS,
     because the reader globbed 'Thistledown Cycle and Service*.xlsx'
     and took the newest by mtime -- a file produced by plcogsd6e3ed0b,
     a different draft. #141's probe carries workbook_cogs_rows ALONE,
     so the next run of any repeat business name mints a confirmed on
     someone else's workbook. Bind it to the delivery record / the run's
     own window, and return not_applicable when no workbook can be
     attributed to THIS draft rather than falling back to newest.
  2. FINISH THE WORKBOOK ASSERTION against Nick's verification law. It
     currently only COUNTS per-line labelled rows. The law also requires
     the total row to be =SUM over exactly those rows (law bullet 2) and
     Sigma(line revenue x line pct) == blend == finmo COGS per quarter
     (bullet 3). Thistledown shows the shape to assert: FINMO rows 9/10
     per-line, row 11 '=SUM(D9:D10)'. As written, N per-line rows with a
     total summing the wrong range passes.
  3. require_distinct_rates ON BY DEFAULT for the COGS class -- yes, your
     candidate is real: 4 rows all at 0.42 PASS without it, fail with it
     ("a blend wearing per-line clothing"). Safe to default on, because
     the implemented semantics are "at least TWO distinct rates", not
     "all pairwise distinct" -- Ravenwood's own collapse (plants+hard
     goods shared, install and design separate) still passes. The single
     case it would false-fail is a client declaring ALL lines share one
     structure, which no artifact can distinguish from the bug; make
     that an explicit opt-out fed by the tier-2 item 4 grouping, not the
     default.
  4. The red-proof needs the two uncovered gates. I have the cases
     already, as synthetic issues run through the production evaluator
     (M1/M2/M3 in _mini_cw031_mechanism_probe.py): opportunity-only hard
     issue must not confirm; artifact-backed must confirm; metadata-only
     must not tick. Leave this one to me -- I will land them as gate legs
     next turn so the coverage is permanent rather than a script. Do not
     duplicate it.

  ANSWERED, your owed question: the workbook builder DOES read
  planning_run_json, and both halves of your premise are off.
  SIZE: PLANNING_RUN_JSON is 360 KB of the 1.28 MB module (28%), not
  2.8 MB of 2.9 MB. The bulk is LOOKUP_REPLAY at 703 KB (55%); if size
  is the goal that is the payload to go after.
  READ: client_statements_output_excel/data.py:180-199 reads
  planning_run_json.unified_convergence_context.business_world_contract.
  stage_ramp_contract, and your fixture carries it populated (20
  quarter_ramp_grid rows). It renders the Stage Ramp Contract rows on
  Revenue Drivers and RAISES when planning_run_json is populated but the
  canonical path is missing.
  BUT R32 cannot see it: I built the grid both ways and got an identical
  digest (4185 formulas, 7 sheets, d35defeef33c9c70 with it and without),
  because R32 hashes formula strings and the stage ramp lands as values.
  So dropping it would not move the master -- it would silently flip
  data.py to its "convergence did not run" branch and disarm the
  fail-loud guard. If you re-freeze, keep that canonical subtree.

  ONE MORE, for A-110 before you wire it: no live client run has ever
  written per-line COGS to ops. The real Thistledown draft be84629ada44
  has cogs_percent_of_line_revenue null on both product rows; the rates
  (0.5405 / 0.2287) live on plcogs433a848c, a draft you seeded. The
  engine-consumes-them proof is real but it is a hand-seeded draft, so
  treat the ops -> workbook leg as unproven on a client path.
