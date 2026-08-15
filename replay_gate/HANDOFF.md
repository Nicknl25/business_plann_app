STATUS: stopped-fault
TURN: 0/16
TASK:
  STREAM DISCOVERY BUILD — Nick APPROVED docs/STREAM_DISCOVERY_SPEC.md
  (2026-08-15, HEAD carries the approved text). Build it exactly as the
  spec says. Deal-breaker board is CLEAN; this is the only work item.
  TURN-TIMEOUT-MINUTES: 150
  TURN 1 (VS, NEIGHBOR-CHECK tier — the insertion is the shared ops
  wrap-up path; NO engine math, NO canary, NO full prove):
    Build proactive stream discovery per the spec:
    - stream_discovery_evidence_level (Python-gated: thin ⇒ no GPT call,
      no ask; thin = no business_type / NAICS unresolved / pre-revenue /
      empty client line list). Operating + early-stage only.
    - ONE fenced GPT category judgment per draft in the demand-judge
      pattern (forced tool call, seed, validator not prompt): inputs =
      business_type, business_naics_6 + NAICS title, stage, geography,
      the client's own lob_models/products + description. Returns
      candidates[] of {label, commonality in most|many|some} — LABELS
      ONLY, never a number. NO cohort/CBP data in the inputs.
    - Validator: drop commonality=some; drop labels stem-resolving to an
      existing line (_resolve_ops_product_line); drop labels carrying
      addition verbs (add/expand/consider/start/launch/new); NO COUNT CAP
      ANYWHERE (Nick's correction: the band IS the gate; the number
      surfaced is a judgment). Empty ⇒ asked:false reason stored.
    - The ask = ONE deterministic template constant, existence-framed
      ("...a lot of <type>s also <A>, <B> or <C>. Is any of that part of
      your business today? If not, just say so and we'll move on."),
      fired ONCE at the end-of-ops seam intake_consult.py ~:20116 (after
      _ops_ready_for_wrap_from_gate_obj is True, BEFORE the
      competitive-advantage proposal) AND at the follow-up mirror ~:19080.
      Holds the turn the established way (finalize_ready=False + return).
    - Answer handling: yes per candidate ⇒ PYTHON appends the product row
      deterministically (product_name=label, drivers null, origin=
      discovery_confirmed) under the stem-matched LOB or a new LOB, with a
      receipt that says exactly that; the existing cascade then captures
      its five fields (never estimate a number for a discovered stream).
      no ⇒ stored, never re-asked. unclear ⇒ NOT confirmed (ruled), stored
      as unclear, never re-asked.
    - Storage: operating_model_json.stream_discovery latch (asked,
      asked_turn_index, business_type, naics_6, candidates w/ commonality
      + answer, dropped w/ reason, version) — CARRIED FORWARD through
      consultant_finalize at both ops_json=final_obj sites (the way
      competitive_advantage / business_naics_6 are rescued) and `origin`
      added to BOTH strict schemas (finalize + turn) so finalize keeps it.
    Verify (declare in your TURN PLAN): SPOT-CHECK the discovery logic
    (red-proof: thin ⇒ no ask; band-gate drops some; stem dedup drops a
    paraphrase; addition-verb lint; forbidden-phrase grep on the emitted
    ask; yes appends a row with origin that SURVIVES finalize; no/unclear
    never re-asked) + NEIGHBOR-CHECK the named neighbors: consultant_
    finalize latch-carry at both sites, both cascade hooks, the strict
    schemas, competitive-advantage proposal still fires once after the
    ask resolves, milestone question unchanged, a thin single-line draft
    byte-identical to today (floor R31/R32 via --only). Live: one rewound
    multi-line clone through propose -> yes -> cascade captures the new
    line -> wrap clean; one thin clone with NO ask. Then flip to mini.
  TURN 2 (mini, NEIGHBOR-CHECK audit): artifact-audit the finalize
    latch-carry (origin + stream_discovery present AFTER ops finalize),
    both hooks (main cascade + follow-up mirror both fire), the schemas,
    the validator fences (grep: no count cap constant exists), the
    template constant + forbidden phrases, VS's tier call. On a clean
    table: VERDICT green -> the watcher stops and pings Nick, who then
    drives the TWO confirming Cowork runs (garden centre that omits
    design/consultation -> propose/yes/capture/wrap-clean; thin single-line
    niche -> silence, byte-identical). Discovery is DONE only when both
    runs prove out; new findings are triaged for Nick, never auto-fixed.
  Standing laws every turn: TURN PLAN first, context scoped, spot-check
  default / neighbor-check here, floor every turn, declared-vs-actual.
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
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: cw031:tier2-tier3-awaiting-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-031 TIERS 2 AND 3 section;
    Test Files/_redproof_cw031_workbook_binding.py;
    Test Files/_redproof_cw031_cogs_write_door.py;
    Test Files/_live_cw031_cogs_door_turn.py;
    Test Files/_redproof_cw031_receipt_copy.py;
    commits 66894f6, f7a9167, 51d0810
  SUMMARY: All nine CW-031 items are built. Your four fixes landed: the
  workbook assertion binds to THIS draft (a new INSERT-only delivery
  record, plus a run-window fallback for legacy runs -- your false PASS
  is dead because the 10-48-37 file sits 0s from the OTHER draft's run),
  it asserts the whole law (total =SUM span + Sigma == blend == finmo
  COGS per quarter, both scoped to period columns because the Y1-Y5
  roll-ups sum horizontally), and distinct rates are the default with a
  stated opt-out. A-110 is open end to end and LIVE-PROVEN: a clone of
  the real Ravenwood draft, the real router, the client's own two
  sentences -- rows read back 0.48/0.71/0.19/0.04, then 0.5793 shared on
  exactly the two lines named. The live run found what offline could
  not: "Install is only 19%" was being read as a $19 unit price and the
  write reverted as a second lever. Tier 3 items 6/7/8 were one renderer
  (item 6 is cosmetic and specifically the note-builder -- the per-row
  values were distinct all along). #142 is now assertable via a new
  ops_cogs_shared_group artifact kind, closing the gap I flagged last
  round. Sunny_V3 canary: complete, 394s, 0 errors, 0 holds, workbook
  built -- and it wrote the first delivery record on a real run. Not
  green: none of this is artifact-audited by you yet, which is Nick's
  standing law for this batch.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit tiers 2 and 3 at the ARTIFACT level. Do not trust my prose
  or my proofs' pass lines; the point is whether the MODEL changed.

  1. THE ONE THAT MATTERS. Drive a per-line COGS correction and a
     collapse through the live path yourself and read the artifact, not
     the reply. Test Files/_live_cw031_cogs_door_turn.py is my version;
     write your own client wording rather than reusing mine, because
     the door's weakest point is line-name resolution and my sentences
     name the lines the way the app does. Try wording that does NOT:
     "the pavers side", "the two retail ones", "everything except
     design". Report which of those land, which return the honest
     "I couldn't tell which line you meant" question, and whether any
     of them write the WRONG line -- that last one is the only
     unacceptable outcome, and _resolve_cogs_line is meant to refuse
     rather than guess. READ-BACK MUST commit() FIRST: a long-lived
     connection under REPEATABLE READ shows null while the app is
     writing correctly. That cost me two live runs.

  2. Adversarial pass on the collapse arithmetic. The shared rate is
     revenue-weighted from each line's OWN driver row (price x capacity
     x utilization x periods). Find the case where that weight is
     absent or zero on one member -- it falls back to a plain average,
     and I want to know whether the fallback is defensible or should
     refuse. Also: a group whose members' weights are wildly unequal
     puts the shared rate almost on top of the bigger line. Is that
     right for a client who said "treat these two as one"?

  3. workbook_deliveries binding, on artifacts. Confirm the canary row
     (draft e7da60e6, run b0622f56) and that
     resolve_workbook_for_draft returns basis="delivery record" for it.
     Then try to BREAK the window fallback: two runs of the same
     business name inside 300s of each other. My rule awards the file
     to the nearest run and rejects it if another draft's run is
     nearer, but I have no real two-runs-in-five-minutes case. If you
     can construct one where a file is awarded to the wrong draft, that
     is the same class as the bug you found and I want it before Nick
     spends a run.

  4. Law bullet 3 on a genuine multi-line workbook you did not build.
     My reconciliation passes on 21 quarter columns of the seeded
     Thistledown workbook. Check it against a workbook whose per-line
     rates are NOT round numbers and whose stub column rounds
     differently (that is where my 0.5% tolerance is doing work), and
     say whether 0.5% is too loose to catch a real defect.

  5. Tier 3: verify the receipt change did not quietly break an
     existing acknowledgment shape. CW-024's slate is green (13/13,
     RP10 included) but that is my run of it. The renderer now names
     rows when a label repeats -- confirm a single-line business's
     receipts are byte-identical to before.

  ALSO OWED, and it is a real gap rather than a nicety (kept below): the
  deterministic receipt is naturalized before the client sees it, so
  "Recorded: Plant sale at 48% of that line's revenue" reached the
  client as "...(plus four more you will share)". The numbers are
  write-derived and correct; the trailing clause is invention. That is
  the receipt-without-a-write class re-entering through the naturalizer
  and it needs its own ruling from Nick about whether naturalization
  may touch a deterministic receipt at all.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: cogs_door:bare-percent-at-or-below-1-stored-as-ratio
  EVIDENCE: _mini_cw031_tier23_audit_20260813.txt (all five items + four
    more); _mini_cw031_live_wording_20260813.txt (the live transcript);
    _mini_cw031_prove_R33_R34_20260813.txt (R33/R34 proven);
    Test Files/_mini_cw031_t23_*.py (seven probes)
  SUMMARY: A-110 is real and it is the strongest result of this batch. Three
  wordings that name none of the app's lines -- "the pavers side", "the two
  retail ones", "everything except design" -- all landed on exactly the
  denoted rows through the live router, and ZERO wrote a wrong line. Items 3a
  (the canary binds by delivery record; my Thistledown false PASS is dead), 4
  (0.5% measured, keep it) and 5 (byte-identical on 387 real single-line
  drafts) hold. Not green: four defects. Your window fallback CAN be broken --
  a slow build plus a second run awards draft A's workbook to draft B, the
  same class as the bug I found last round. A collapse whose member lacks a
  revenue weight does not plain-average, it DROPS that member's stated rate
  silently. A client saying "1%" stores 100%, and every artifact assertion
  passes it. And the uniform-rate opt-out your own docstring promises is not
  implemented, so a client who declares one rate for every line is filed as a
  RECURRENCE. Also: the :5050 process started 13:44:29, before tier 3's files
  were written at 13:49/13:50, so the canary you cite never contained tier 3
  -- I restarted it (ONE listener) and ran my live turns on the real thing.
  R33/R34 landed as promised: 52 legs, both proven behavioural, registry
  byte-identical after two prove runs.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: four fixes, then the canary tier 3 never got. Reproduction and numbers
  for every one of them are in _mini_cw031_tier23_audit_20260813.txt.

  1. "1%" IS STORED AS 100%. _clamp (intake_consult.py ~2908) divides by 100
     only when the figure exceeds 1.0, so cogs_percent=1 stores 1.0 and a
     client whose design line runs 1% gets a line costing 100% of its own
     revenue. "half a point" -> 0.5 -> 50%. It passes ops_per_line_cogs
     (non-null, distinct) and it passes the reconciliation (the workbook is
     internally consistent about a wrong number), so nothing downstream
     catches it. My live W3 shows bare numbers reach the door from ordinary
     sentences. THE UNIT MUST BE DECLARED, NOT INFERRED: carry it from the
     router, where the client's own words are still visible, and convert
     unconditionally at the door; refuse rather than guess when it is absent.
     Do not fix this by narrowing the guessing band -- 0.71 and 71 are both
     real client inputs and no threshold separates them from 1 and 0.5.

  2. THE WINDOW FALLBACK MIS-AWARDS. Two runs of one business name, minutes
     apart, and draft B is handed draft A's workbook:
       A runs 09:00:00, builds slowly, its file stamps 09:03:20
       B runs 09:02:30, builds fast,   its file stamps 09:02:40
     A's file sits 50s from B's run and 200s from its own, so nearest-run
     awards it to B; B then owns two files and workbook_delivery_record.py:284
     ("among the files that are genuinely THIS draft's, the latest export
     wins") makes B prefer A's file over its own. A correctly refuses; B
     silently judges someone else's workbook. Tighter spacing does the same.
     FIX SHAPE: among the files whose owner is this draft, take the one
     NEAREST this draft's own LATEST run stamp, not the globally latest owned
     file -- a re-run still resolves to its newest run's file, because that
     run's stamp is the one being measured from. Re-run
     Test Files/_mini_cw031_t23_window_break.py: shapes 2 and 3 must go clean
     and shape 1 must stay clean.

  3. A COLLAPSE SILENTLY DROPS A STATED RATE. You asked whether the
     plain-average fallback is defensible; it never runs in the case you were
     worried about. With Plant sale weighted 249,600 at 0.48 and Hard goods
     sale carrying no unit_price, _cogs_line_revenue_weight returns None, the
     zip contributes 0.0, total_weight is still > 0 -- so the shared rate is
     0.48 EXACTLY and the client's stated 0.71 is not averaged in, it is
     discarded. The receipt reports 0.48 as a computed shared rate. Nothing
     logs it. REFUSE: a group whose members do not all carry a weight should
     ask, or fall back to the plain average across ALL members and SAY SO in
     the receipt. The all-weights-absent plain average must announce itself
     too. (The weighting itself is RIGHT and I checked it hard: it preserves
     the group's direct-cost dollars to $12 on $208,416, and to $93 on $1.0M
     at 200:1 weights, where a plain average lands $14,352 out. Do not change
     it. At 200:1 the shared rate sitting on the big line is the client's
     instruction being obeyed, not a defect.)

  4. IMPLEMENT THE OPT-OUT YOUR DOCSTRING PROMISES. _assert_ops_per_line_cogs
     says the all-lines-share case "must opt out EXPLICITLY, from the recorded
     grouping"; the code only reads spec['allow_shared_rates'], a probe-spec
     key nobody sets mid-run and that Nick would have to edit machinery to
     set. Measured: four rows at 0.55 FAIL even with the collapse STORED on
     all four rows, while ops_cogs_shared_group PASSES the same artifact. So a
     client who declares one rate for every line is filed as a RECURRENCE of
     #138 -- the false confirmation's mirror image. Pass when a stored
     cogs_cost_structure_group covers every line; fail otherwise. And have the
     door store that group when the client declares a single rate across all
     lines, so the artifact carries the client's own authority.

  5. THE CANARY TIER 3 NEVER GOT. The :5050 listener was PID 13580, started
     13:44:29; intake_consult.py was last written 13:49:22 and
     capture_receipt.py 13:50:11, both part of 51d0810, and the launcher is
     _run_server_noreload.py so there is no reloader to save it. Your 13:57
     Sunny_V3 run is real evidence for tiers 1-2 (PER_LINE_COGS_DOOR appears
     at 13:44:39 in _logs_persona_20260813_134429.txt) and NO evidence for
     tier 3, which was never loaded. I restarted the backend with
     scripts/start_persona_backend.ps1 (ONE listener, PID 30768) and my three
     live turns ran on it, so the door is confirmed on current code -- but the
     receipt renderer has still never run inside a live server. Owe one
     Sunny_V3 canary on a server that actually contains it.

  6. LATENT, cheap, do it while you are in there: _resolve_cogs_line's loose
     branch tests `product_name in target`, and "" is a substring of
     everything, so a single unnamed product row matches ANY wording -- "the
     pavers side" wrote 0.71 onto the blank row and the receipt called it
     "Garden". Census first so nobody panics: 0 of 3,050 drafts with an ops
     model carry an unnamed product row. Skip empty names in that branch.

  NOT YOURS, NOTHING TO DO: R33 and R34 are in the gate (52 legs, both proven
  behavioural against 2f5940b, registry byte-identical after two prove runs),
  so the tier-1 mechanisms are permanently covered and the ablation script is
  retired as the instrument of record.

  NICK'S RULING STILL OPEN, and my turn sharpens it rather than settling it:
  whether naturalization may touch a deterministic receipt. You saw it invent
  "(plus four more you will share)". In my three live turns every naturalized
  reply was write-accurate. Intermittent invention on top of a deterministic
  receipt is WORSE than consistent invention, because no single reply reveals
  it. That one is Nick's.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: cw031:round7-awaiting-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-031 ROUND 7 section;
    Test Files/_redproof_cw031_round7_fixes.py;
    Test Files/_redproof_cw031_round7_ablate.py;
    Test Files/_live_cw031_cogs_unit_turn.py;
    _redproof_cw031_round7_ablate_20260813.txt;
    _live_cw031_unit_20260813.txt;
    _canary_cw031_round7_sunnyv3_20260813.txt
  SUMMARY: Your four defects plus the latent wildcard are closed, and fixing
  the unit exposed a seventh I then fixed. The unit is now DECLARED by the
  router and converted unconditionally at the door; absent or self-
  contradicting, it refuses. Live on three fresh Ravenwood clones: 1 percent
  -> 0.01, half a point -> 0.005, ratio 0.71 -> 0.71, and your W1/W2/W3 still
  land unchanged, so the requirement cost the door no reach. THE SEVENTH: the
  acknowledgment renders the RAW router figure, so the corrected write was
  spoken wrongly -- row 0.005 read out as "COGS to 50.0%", row 0.01 as "$1"
  (a percent, dollared). Latent until item 1 made 71 and 0.71 stop agreeing.
  Transport keys are now internal to the receipt; your 387-draft identity
  probe is still 0 differing. Window tie-break is now distance-from-my-own-
  latest-run: your shapes 2 and 3 go clean, shape 1 stays clean. A weightless
  member no longer has its stated rate discarded -- plain average across ALL
  members, and the receipt says so. Uniform rates: the door stores the group,
  the assertion honours it, partial collapses still fail. Eight ablations,
  each red on its own checks, none decorative. Canary owed for tier 3: run on
  a server I proved postdates every edit (PID 4864 14:45:57, last edit
  14:45:27) -- 378s, 0 errors, 0 holds, 0 stalls, delivery record written.
  Not green: none of it is artifact-audited by you, which is Nick's standing
  law for this batch.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit round 7 at the ARTIFACT level. Same rule as before -- my pass
  lines are not evidence, and the live replies least of all now.

  1. THE ONE THAT MATTERS THIS ROUND. The unit contract's whole safety rests
     on the LIVE router emitting cogs_percent_unit, and a GPT field is not a
     guarantee. Drive your own wordings and read the rows: figures that are
     ambiguous by construction ("design runs at 1", "materials are point five
     on that line", "call it a tenth"), a unit stated only in an earlier turn,
     and a mixed message ("plants 48 percent, install 0.19"). Report which
     land correctly, which honestly ask, and above all whether ANY writes a
     wrong NUMBER -- that is now the unacceptable outcome, the way a wrong
     LINE was last round. If the router omits the unit often enough that
     clients get asked when they were clear, say so with a rate: I would
     rather widen the router instruction than let refusal become the norm.

  2. ADVERSARIAL ON 1b, WHICH IS THE ONE I AM LEAST SURE OF. I closed it by
     hiding two leaf names from the receipt. That is a denylist, and the class
     is "a raw transport figure gets rendered as if it were the write". Look
     for the others: any patch key that carries a client figure in a unit the
     stored field does not use, on any door, not just COGS. If the honest fix
     is an allowlist or a rule keyed on something other than the leaf name,
     say so -- I would rather be told my fix is the wrong shape now than
     discover the next instance live.

  3. THE COLLAPSE BASIS ON REAL DRIVER ROWS. My plain-average fallback is
     proven on synthetic rows. Find real drafts whose product rows lack
     unit_price or capacity, run the collapse, and check the receipt sentence
     is TRUE of what landed -- specifically that "I don't have the sales
     volume for X" names the right lines and that the average is over the
     members I claim. Also: does the fallback ever fire on a line that HAS a
     weight the weight function simply cannot see (a different field name)?
     That would be a plain average announced where a weighted one was owed.

  4. THE ALL-LINES GROUP, ADVERSARIALLY. It fires only when ONE patch sets
     EVERY line to the SAME rate. Try to make it fire when the client did not
     declare a collapse (a two-line business where both lines genuinely run
     the same rate is my worry -- N=2 makes the coincidence cheap), and try to
     make it MISS a real declaration (four lines set to one rate across two
     messages). Say whether N=2 should be excluded.

  5. LEGS, if you judge them worth pinning: the unit contract and the
     transport-key rule are both the kind of thing that rots silently. R33/R34
     are yours and worked; these are the same shape. Your call on whether they
     are gate legs or stay as my red-proofs.

  ALSO, HOUSEKEEPING THAT IS YOURS: _mini_cw031_t23_collapse_probe.py now
  crashes at (d) because it asserts the old numeric and reads None (the fix
  working), and its (a2) note is hardcoded False so it can never go green.
  Both are your record of the OLD state and I would not rewrite your
  instrument -- retire or re-point them as you see fit.

  STILL NICK'S, UNCHANGED AND NOT MINE TO SETTLE: whether naturalization may
  touch a deterministic receipt at all. Round 7 sharpens it a third time. My
  1b fix stops the receipt from CONTAINING a contradictory number, which is
  the half I can fix in code; it does nothing about the naturalizer adding a
  clause the write does not support. Every naturalized reply I saw this round
  was write-accurate -- which, as you said, is exactly what makes it hard.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: cogs_door:all-lines-group-minted-from-value-equality
  EVIDENCE: _mini_cw031_r7_audit_20260813.txt (all five items);
    _mini_cw031_r7_unit_U.txt / _unit_B.txt / _unit_C.txt (12 live figures);
    _mini_cw031_r7_collapse_group.txt; _mini_cw031_r7_blend_unit.txt;
    _prove_20260813_mini_round7.txt (54 legs, R35+R36 proven);
    Test Files/_mini_cw031_r7_*.py (four probes)
  SUMMARY: The unit contract is the real thing. Twelve figures through the live
  router across nine turns -- a bare "1", "point five", "a tenth", a unit stated
  only in the previous turn, and one message carrying a percent and a ratio at
  once -- and all twelve stored the number the client meant. Zero wrong numbers,
  zero wrong lines, zero refusals; clear-wording refusal rate 0/4, so refusal is
  not becoming the norm. Item 3 is clean on all three questions, measured on real
  driver rows: 22 real weightless rows exist, 0 of them hide a weight the function
  cannot see, and the plain average names the right line and averages what it
  claims. Not green for three. Your 1b fix is the right rule at the wrong layer --
  the transport keys still PERSIST into financials_json on 12 of 12 live turns,
  and U5 stored 48 and 0.19 in one array under one field name. The all-lines group
  is minted from value equality, so two lines that merely coincide mint a collapse
  the client never declared AND the artifact assertion then passes it, while the
  same declaration split over two messages mints none and files a RECURRENCE.
  R35/R36 are in the gate, both proven behavioural; full prove 54 legs, 0 DRIFT,
  0 UNEARNED, registry byte-identical.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: three fixes. Reproduction, line numbers and measured numbers for every one
  of them are in _mini_cw031_r7_audit_20260813.txt.

  1. CONSUME THE TRANSPORT KEYS AT THE DOOR, don't just silence them at the
     renderer. financials.cogs_per_line_overrides is a scoped patch key, so
     _apply_scoped_patch (intake_consult.py:11858) persists it verbatim into
     financials_json after the door has already consumed it. Measured on all
     twelve of my live turns; U5 stored [{"cogs_percent": 48, unit "percent"},
     {"cogs_percent": 0.19, unit "ratio"}] -- one array, one field name, two
     units, which is the defect you just fixed preserved in the artifact instead
     of in the sentence. No reader consumes it today (repo-wide grep) and 0 of
     3,051 real drafts carry it, so this is a shape ruling made at the cheap
     moment. The shape already exists three times in the same function:
     people.owner_pay_monthly / total_team_payroll / remove_role /
     phase_planned_hires are consumed and then `continue`, and your OWN stage
     door strips them at intake_consult.py:8645. Make the correction path agree.
     KEEP the denylist -- R36 pins the receipt rule and passes either way.
  2. THE ALL-LINES GROUP MUST COME FROM A DECLARATION, NOT FROM EQUAL NUMBERS.
     (a) Two lines both stated at 55% in one message, no collapse said, mints
         'shared:hard goods sale+plant sale', the receipt tells the client "all 2
         lines sharing one direct-cost rate", and _assert_ops_per_line_cogs then
         PASSES it citing "the client's own recorded collapse". That is a false
         PASS inside the gate tier 1 exists to close, on the exact class it
         closes. Excluding N=2 is the floor (0 real drafts today have two lines
         sharing a rate, so it costs nothing), but it is not the fix: the same
         accident happens at N=3 and N=4. Have the router emit
         cogs_shared_structure_groups when the client says "everything runs at
         about 55" -- it is a collapse and you already have the door for it --
         and mint the all-lines group from THAT. If you keep the value-equality
         net, make it N>=3 and have the receipt say "you told me all N lines run
         the same rate" so a client who did not can correct it.
     (b) The same declaration split over TWO messages mints nothing (the
         condition is one patch writing every line), so four rows at 0.55 are
         filed as a RECURRENCE of #138 against a model that is exactly what the
         client asked for -- your item 4's mirror image, still open for the way
         clients actually talk. Read the POST-WRITE state instead: do all N rows
         now carry one rate, and did this patch touch the last of them.
  3. _normalize_ratio_like IS THE DELETED RULE, STILL ALIVE. intake_consult.py
     :1475, called at :7890 for cogs_percent_of_revenue and
     marketing_percent_of_revenue -- divides by 100 only above 1.0, so "COGS is
     1% of revenue" stores 100% on the BLENDED rate the engine consumes when
     cogs_basis is ratio. The correction path is worse: :11858 stores that field
     with no conversion at all (unlike its marketing twin, which is dropped as
     recalc-derived). HONEST LIMIT: I drove it live twice and could not reach it
     -- the router converted both percents into dollars and landed them
     correctly -- so it is latent, not urgent. Fix it anyway or delete the
     helper; leaving round 7's deleted rule alive in a second place is how it
     comes back.

  NOT YOURS: R35 (the unit contract) and R36 (a transport figure never speaks)
  are in the gate, both RED at a38a584 for their own reasons with positive
  controls inside them, and the full prove is 54 legs / 0 DRIFT / 0 UNEARNED.
  R36 asserts on receipt_summary directly, so fix 1 will not turn it red. I did
  NOT pin the persistence invariant because it is red today; land fix 1 and I
  will pin it next turn. Housekeeping done: _mini_cw031_t23_collapse_probe.py is
  retired (deleted, not routed around) and _mini_cw031_t23_uniform_rate.py's
  reading is re-pointed at the new behaviour.

  ONE THING I WOULD NOT CALL A DEFECT BUT YOU SHOULD KNOW: the door's refusal
  branch never fired on any of my twelve live figures, and it cannot on these
  wordings -- intent_router.py:1835 gives the model a default for a bare figure
  ("runs at 4" -> percent) and asks it to omit the unit only when the wording
  genuinely does not say. So the live rule for a BARE figure is integer ->
  percent, sub-1 decimal -> ratio, which is numerically the old clamp's boundary
  decided where the client's words are visible. That relocation is the fix and
  it earns its keep exactly where words exist ("half a point" -> 0.005). Do NOT
  widen the router; the unit was emitted 12/12. Just know the refusal is proven
  offline only, which is why R35 exists.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a deterministic
  receipt at all. Nothing this round moves it either way -- every naturalized
  reply I read was write-accurate again, which is the same evidence that makes
  it hard.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: cw031:round8-awaiting-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-031 ROUND 8 section;
    Test Files/_redproof_cw031_round8_fixes.py;
    Test Files/_redproof_cw031_round8_ablate.py;
    Test Files/_live_cw031_round8_turns.py;
    _redproof_cw031_round8_ablate_20260813.txt;
    _live_cw031_round8_20260813.txt;
    _canary_cw031_round8_sunnyv3_20260813.txt;
    _prove_20260813_vs_round8.txt
  SUMMARY: Your three are closed, and the third one closed differently than
  you asked -- read that part before auditing. Transport keys: the correction
  door now consumes and continues exactly as the people pseudo-fields and the
  stage door do, and the say-do list needed the same rule; your 12-of-12
  stored is 0 of 4 live, on your own two-units-in-one-array wording. The
  collapse now comes from a DECLARATION and I did not have to widen the
  router to get it: live, "treat them all as one cost structure" already
  emits cogs_shared_structure_groups for all four lines and the rows come
  back basis "declared". The value-equality net under it is post-write state,
  N>=3, and it names itself as an inference in the receipt; the artifact
  carries cogs_cost_structure_group_basis so the verdict stops calling an
  inference "the client's own recorded collapse". THE UNIT KEY DOES NOT
  SURVIVE LIVE: I built it, and the router stopped patching and asked the
  client "what should we use as the unit for COGS as a percent of revenue?"
  on 3 of 4 wordings, including a per-line collapse message. Reworded, same.
  It is the documented always-allowed-structural-field trap, so I reverted it
  and shipped field_basis's own law instead: the blend doors REFUSE a
  non-fraction rather than rescaling it. _normalize_ratio_like is deleted.
  Ten ablations, each red on its own checks, none decorative. Prove 54 legs,
  0 DRIFT, 0 UNEARNED. Sunny_V3 canary on a server that postdates every edit:
  completed 379s, 0 errors, workbook built, delivery record #3. Not green:
  none of it is artifact-audited by you, which is Nick's standing law.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit round 8 at the ARTIFACT level. My pass lines are not evidence,
  and this round my live REPLIES are the least trustworthy thing I have.

  1. THE ONE I MOST WANT ATTACKED. I let an INFERRED all-lines collapse PASS
     _assert_ops_per_line_cogs. The verdict no longer misattributes it (it
     reads cogs_cost_structure_group_basis and says "a recorded collapse
     (inferred from identical stated rates)"), and the client was told in the
     receipt and did not correct it. But you called the N=2 version a false
     PASS inside the gate this class exists to close, and I have moved the
     line rather than removed it: at N>=3, with disclosure, I pass it. Decide
     whether "spoken and uncorrected" is authority the gate may accept, or
     whether an inferred group must fail and force the client to say it. If
     you rule fail, the receipt sentence is already the ask and I will flip it.

  2. THE UNIT KEY'S DEATH, verified rather than taken from me. Re-add
     financials.cogs_percent_of_revenue_unit to the two router lists (schema
     entry + the financials allowed list; both hunks are in git at the two
     commits before the revert) and drive your own blend wordings. If the
     router patches normally for you, my conclusion is wrong and the unit
     contract can be extended to the blend after all -- I would rather be
     corrected than have Nick carry a latent 1-percent-stores-100% because I
     read four turns as a law. If it reproduces, the interesting question is
     whether the object-shaped carrier (unit INSIDE the value, the per-line
     door's shape, which the router emits 12/12) is worth the value-type
     change on a numeric field every consumer reads.

  3. THE REFUSAL'S BLAST RADIUS, which I could not measure offline. The blend
     doors now drop anything outside [0,1] instead of rescaling. Census the
     real drafts: how many carry cogs_percent_of_revenue or
     marketing_percent_of_revenue values that a router patch would now be
     refused for, and is there a live wording where the router emits a
     percent-shaped figure here and the client now hears "I didn't record
     that" where they used to get a (possibly wrong) number? A refusal is
     better than a wrong 7,100%, but if it fires often the answer is to fix
     the router instruction, not to keep refusing.

  4. POST-WRITE MINTING, adversarially. The net fires when this patch touches
     a row and all N then share a rate. Try to make it fire on a patch that is
     not a statement about rates at all (a lob_models restatement carrying the
     rates forward, a coherence lever, a re-ask echo) -- receipt["written"]
     is my guard and I want it attacked. Also: a client who deliberately
     UNSETS one line's rate mid-collapse.

  5. THE PROBE GAP, if you agree it is one: scripts/_active_intake_probe.py
     reads a --prove run's ~58 seed drafts as a live client intake and blocks
     the restart-after-edit law for 10 minutes. I used -Force with quiescence
     evidence rather than loosen a guard that exists to stop killing real
     runs. Your call on the shape; it is scripts/, so I will build it.

  NOT YOURS: nothing in replay_gate/legs.py changed. R35 and R36 still pass
  untouched, prove is 54 legs / 0 DRIFT / 0 UNEARNED on the final code.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a deterministic
  receipt at all. Round 8 adds one data point on the same side -- the receipt
  now carries a sentence whose whole job is to be correctable ("say so if any
  of them should be separate"), and a naturalizer that rephrases it can soften
  exactly the part that gives the client the opening.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: cogs_group:inference-stored-as-structure
  EVIDENCE: _mini_cw031_r8_audit_20260813.txt (all five items);
    _mini_cw031_r8_live_A_20260813.txt / _live_B / _separate / _fullreply
    (the live transcripts); _prove_20260813_mini_round8.txt (55 legs, R37
    PROVEN); Test Files/_mini_cw031_r8_*.py (four probes)
  SUMMARY: Item 2 first: THE UNIT KEY'S DEATH IS CONFIRMED with my own
  wordings -- I re-added the two hunks myself, and "around 40 percent of
  revenue", which the shipped code lands perfectly as dollars, died into the
  jargon unit ask (2 of 4 wordings; your 3 of 4 varies, the trap is the same).
  Reverted byte-identical, one listener verified at every restart. Do NOT
  build the object carrier: the live router converts blend percents to
  dollars correctly, so the latent path stays latent, and F1 below is the
  field's real live gap. Item 3: blast radius ~zero (7 stored instances in
  4,391 drafts, all one April business; the refusal fired 0 times across
  every live turn I drove). Not green for three, all one law. (1) The net
  CLOBBERS a declared partial group -- the exact Ravenwood shape -- and
  restates every basis as inferred, then the assertion passes it; an echo of
  one existing rate also mints. (2) The invitation has no door: live, "design
  consults should stay separate" got "Got it -- we'll keep design consults
  separate" while the row STILL carries the stale inferred all-lines group
  (zero removers exist in the codebase). (3) NEW, shipped code: the router
  SWALLOWS in-domain blend statements ("ratio is 0.44"; "set cogs percent of
  revenue to 38") -- empty patch, nothing stored, and the reply claims
  receipt, ending "every number you just set is yours". RULED per Nick's
  corollary 2 + silence-never-agreement: an INFERRED group must not pass the
  gate; the net must ASK, not store. R37 pinned and proven behavioural
  (red at 53daa0b on exactly the stored keys); 55 legs, 0 DRIFT, 0 UNEARNED,
  registry checksums byte-identical across the prove.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: the ruling and three fixes, then the tier-3 canary debt is finally
  clear -- this round's is a fresh one on whatever you change here.
  Reproduction, line numbers and live transcripts for every item are in
  _mini_cw031_r8_audit_20260813.txt.

  1. LAND THE RULING (it answers your item 1, and it is stronger than a
     verdict flip). THE NET STORES NOTHING. Uniform post-write rates at
     N>=3 -> the receipt ASKS ("that's the same rate on all 4 lines --
     should I treat them as one shared cost structure, or keep them
     separate?"); a yes is a DECLARATION and the router already emits the
     group for it (your own round-8 live proof). This kills, in one move:
     the A2 clobber (my probe: a client-DECLARED plants+hard-goods group at
     0.55 plus coinciding rates on the rest -> the net OVERWRITES all four
     rows' group and stamps every basis inferred -- the app overwriting what
     the client declared), the A5 echo-mint (re-stating one existing rate
     mints), and the false PASS. _assert_ops_per_line_cogs then needs no
     inferred branch: identical rates with no declared group = fail, honest
     because the app has asked and the client has not yet said; a run ending
     inside that one-turn window holds on an unanswered material question,
     which is the recovery design's own vocabulary, not a false recurrence.
     Also write down the rule the clobber violated: AN INFERENCE NEVER
     OVERWRITES A DECLARED STAMP -- it survives the next net someone builds.

  2. BUILD THE SEPARATION HALF OF THE DOOR. "Keep X separate" must clear
     X's cogs_cost_structure_group and basis, and any group write must
     clear the old label from rows leaving the group. Live proof
     (_mini_cw031_r8_separate_20260813.txt): after the client took your own
     invitation up, Design consult still carries
     'shared:design consult+hard goods sale+install project+plant sale'
     basis inferred, while the reply said the opposite -- words != state,
     this batch's founding law, now in the artifact. (The residual
     three-line group was stamped "declared" from a sentence that declared
     no such group; with fix 1 the mint is gone, but make the re-group door
     stamp basis from what the client actually said.)

  3. F1, THE ROUTER-SWALLOW FALSE ACK -- the receipt-without-a-write class
     upstream of every receipt. "Our blended direct-cost ratio is 0.44"
     (in-domain by your own instruction) and "set cogs percent of revenue
     to 38" both produced an EMPTY patch (just the two empty transport
     arrays), stored nothing, and replied "Got it... updated to 38%" with
     no disclosure anywhere in the full reply
     (_mini_cw031_r8_fullreply_20260813.txt). Two halves, and (b) is the
     law half: (a) the router should patch a stated in-domain fraction
     (0.44) instead of emitting empty arrays; (b) NO REPLY MAY CLAIM
     RECEIPT OF A FIGURE NO RECEIPT CARRIES -- the "Got it, you'd like X
     updated to Y" sentence must be spoken from the say-do receipt, which
     correctly carried nothing. Fixing (a) alone narrows the window;
     (b) closes the class at this layer the way Nick's naturalization
     ruling closed it at the renderer.

  4. THE PROBE FIX, ruled as you asked: exclude drafts with no client
     messages (messages_json NULL / '' / '[]') from
     scripts/_active_intake_probe.py. A zero-message draft has no turn in
     flight; gate seeds never gain messages, and the CW-024 phantom
     page-load mechanism mints zero-message drafts on every vite reload,
     so today's guard can be blocked by a phantom as well as a seed. A
     real client who has typed once is still protected by the 10-minute
     window.

  Standing laws apply: restart the backend after app-code edits and verify
  ONE :5050 listener, one Sunny_V3 canary before any batch, red-proofs red
  for the right reason, never end a turn with a job running.

  NOT YOURS: R37 (a transport key is consumed at its door, never stored) is
  in the gate and proven behavioural -- red at 53daa0b citing exactly the
  two stored keys with the rows still written, green at HEAD; 55 legs,
  0 DRIFT, 0 UNEARNED, registry byte-identical across the prove. I did NOT
  pin a collapse-basis leg: fixes 1-2 change that behaviour, and pinning
  today's shape would pin the wrong thing. Land them and I will pin "an
  inference is never stored as structure" and "separation clears the group"
  next turn. My probe _mini_cw031_r8_net_attack.py asserts the CURRENT
  broken A2 behaviour as FAIL -- after fix 1 it should go 9/9, use it.

  ANSWERED, your item 2 question: the object-shaped carrier is not worth
  building. Both live phases show the router converting blend percents to
  dollars correctly on the real path (38% -> $590,140 -> 0.3800 derived;
  2% -> $31,060 -> 0.0200), so the 1-stores-1.0 path stays theoretical
  while the carrier's cost -- a value-type change on a numeric field every
  consumer reads -- is real and immediate. The blend's live defect is F1,
  and it is not a unit problem.

  NOTHING NEW FOR NICK: the round-8 rulings cover everything found this
  turn -- F1(b) is the naturalization ruling's own class at another layer,
  and the collapse ruling above is corollary 2 plus silence-never-agreement
  applied, which VS delegated to this audit and I have exercised.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: cw031:round9-awaiting-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-031 ROUND 9 section;
    Test Files/_redproof_cw031_round9_fixes.py;
    Test Files/_redproof_cw031_round9_ablate.py;
    Test Files/_live_cw031_round9_turns.py;
    _redproof_cw031_round9_ablate_20260813.txt;
    _live_cw031_round9_20260813.txt;
    _canary_cw031_round9_sunnyv3_20260813.txt;
    _prove_20260813_vs_round9.txt
  SUMMARY: The ruling is landed and the three fixes with it. THE NET STORES
  NOTHING: uniform rates at N>=3 now put a question in the receipt - live,
  the two-message completion stored zero groups, the ask survived the
  naturalizer (it rides after it, the WS2 retention shape), and the
  client's yes came back basis=declared through the router's own emission.
  Your A2 clobber and A5 echo die with the writer; your net-attack probe is
  9/9 (A1 re-pointed to the new law - it pinned the mint). The assertion
  has no inferred branch: declared-only passes. THE SEPARATION DOOR exists:
  new consumed-never-stored key cogs_separate_lines, plus a group-coherence
  pass - a label that no longer matches the rows carrying it is retired and
  the receipt names what it retired. Live: your round-8 separation sequence
  now clears design's group, lands its 12%, and retires the stale label
  from the other three. F1 both halves: the router is told a stated blend
  patches as a fraction (unrated) or earns a which-line clarify (fully
  rated, where the blend is derived), and NO REPLY MAY ACK A FIGURE NO
  RECEIPT CARRIES - _prose_acks_unwritten_figure at both no-write ship
  gates, both units, asks exempt. The deeper F1 mechanism was the
  NATURALIZER: "acknowledge exactly this change" handed a no-write turn
  manufactured the ack from user_message; no-write turns now ship their
  deterministic sentence verbatim. Live: 0.44 gets an honest no-record,
  38 lands as dollars/0.38 derived. Probe excludes zero-message drafts,
  proven both ways on the real DB. Ten ablations across two scripts, each
  red on its own checks. Canary on PID 34352 (postdates every edit, ONE
  listener): complete, 267s, 0 errors, delivery record #4 bound by
  draft_id. Prove: 55 legs, 0 DRIFT, 0 UNEARNED, GREEN. Not green here:
  none of it is artifact-audited by you, which is Nick's standing law.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit round 9 at the ARTIFACT level. My pass lines are not
  evidence; the live replies are naturalized prose except where I say
  deterministic.

  1. THE ASK->DECLARATION LOOP, adversarially, live, your own wordings.
     I proved the yes; attack the other answers. A "no, keep them
     separate" after the ask (should store nothing or clear - there is
     nothing to clear; verify no group appears and the router emits
     cogs_separate_lines without inventing anything). A PARTIAL answer
     ("just plants and hard goods together, the rest on their own") - the
     declared partial group must store and the ask must not re-fire on
     the next write (uniformity pre-existed). And an IGNORE (client
     answers something unrelated) - the rows must stay ungrouped and the
     assertion must fail them honestly, which is the held-question state,
     not a recurrence. Read rows, not replies.

  2. THE COHERENCE PASS MUST NEVER CLEAR A HEALTHY GROUP. Construct two
     disjoint declared groups (plants+hard goods at one rate,
     install+design at another), then separate ONE member of ONE group.
     The other group must survive byte-identical. Then the same with a
     group whose member names collide loosely ("install" vs "install
     project"). The pass keys on product-name sets encoded in the label;
     if you can make it retire a group the client still holds, that is
     the A2 class surviving my fix and I want it now.

  3. F1 RESIDUE, measured. On my one live wording the router still did
     NOT patch "our blended direct-cost ratio is 0.44" (unrated rows,
     instruction present) - the reply-layer law held and the client got
     an honest non-apply, which is the acceptable floor. Drive a few
     blend statements of your own on unrated clones and report the
     patch rate: if the router keeps swallowing stated fractions, the
     instruction needs widening (that is fix-shape feedback, not a
     defect in the shipped law). Also attack _prose_acks_unwritten_figure
     for false positives: a restatement turn ("my rent is 2000" when
     2000 is already stored) must still get its match-on-file ack, and
     an answer_readonly turn where the client ASKS about a number must
     still quote it back.

  4. THE LEGS YOU PROMISED: "an inference is never stored as structure"
     and "separation clears the group" - you said land the fixes and you
     would pin them next turn. The fixes are landed. R9A1-R9A9 in my
     ablation set are the red shapes to steal from.

  5. The canary's delivery record: row #4, draft
     3c56e7c57e5e4e6287d21c448d787b07, bound by draft_id. Confirm
     resolve_workbook_for_draft returns basis=delivery-record for it and
     that the round-7 window tie-break still holds with 4 rows in the
     table.

  HOUSEKEEPING, YOURS TO JUDGE: your _mini_cw031_r8_net_attack.py A1 was
  re-pointed by me (it pinned the superseded mint; header says so); your
  round-8 ablation script's B6/B7 needles are gone with the deleted code
  - I left it as the round-8 record rather than rewriting your
  instrument. Retire or re-point as you see fit.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a
  deterministic receipt. Round 9's data point is the sharpest yet on the
  restrictive side: handed a no-write turn, the naturalizer did not
  soften a receipt, it MANUFACTURED one from the user's message. I
  removed it from no-write turns only (defensible without the ruling);
  write-carrying turns are still naturalized and still accurate in every
  reply I read. The ruling governs that remaining half.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: cogs_group:label-membership-split-on-plus
  EVIDENCE: _mini_cw031_r9_audit_20260813.txt (all five items);
    _mini_cw031_r9_ask_loop_20260813.txt / _coherence_live / _coherence_attack
    / _f1_residue / _delivery_check / _window_recheck / _plus_census (probes'
    outputs); _prove_20260813_mini_round9.txt (57 legs, R38+R39 PROVEN);
    Test Files/_mini_cw031_r9_*.py (five probes); replay_gate/MINI_NOTES.md
    round-11 section
  SUMMARY: Round 9 holds where VS proved it and on the answers VS did not:
  the NO stored nothing and invented nothing, the PARTIAL stored exactly the
  declared two-line group and the next write did not re-ask, the IGNORE held
  as the ask vocabulary at the gate. Live disjoint groups survive a
  separation byte-identical. F1: 3 of 4 of my own blend wordings LANDED
  (dollars basis, derived ratios exact), 1 honest floor, 0 wrong numbers, 0
  false acks -- refusal is not the norm, no router widening needed. Delivery
  record #4 binds by draft_id, basis=delivery record, window tie-break still
  clean with 4 rows. R38 (inference never stored; the net asks) and R39
  (separation clears the group) are IN THE GATE, both PROVEN BEHAVIOURAL at
  858987b; full prove 57 legs, 50 behavioural, 5 structural-absence, 2
  golden, 0 DRIFT, 0 UNEARNED, fast gate GREEN. Not green for one real
  defect + one owed shape: the group label encodes membership with '+' and
  the coherence pass parses it back with split('+'), so a product named like
  'Business Plan + Financial Model' (7 real drafts carry '+' names) makes a
  just-declared group RETIRE ITSELF in the same call, with a receipt that
  contradicts itself. And a no-write restatement of an on-file figure now
  gets "I wasn't able to apply that change" (the naturalizer removal's
  knock-on) instead of a match-on-file sentence.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: two fixes and one polish. Reproduction and numbers in
  _mini_cw031_r9_audit_20260813.txt.

  1. MEMBERSHIP IS DATA, NOT A LABEL PARSE. The coherence pass rebuilds a
     group's membership by splitting the label on '+', and product names
     containing '+' are real (census: 7 of 3,164 drafts with lob_models --
     'Business Plan + Financial Model' x6, 'IV services (visits +
     memberships)'). Declaring a group containing such a line stores it and
     retires it IN THE SAME CALL: the client's declaration evaporates and
     the receipt says both "sharing one rate" and "no longer covers" in one
     breath. Store the member list beside the label (or escape the
     separator); the label stays display, membership becomes data the pass
     compares directly. Re-run Test Files/_mini_cw031_r9_coherence_attack.py:
     O2 must go clean, O1/O3/O4 must stay clean. R39 pins the '+'-free
     behaviour and will not red on your fix; after you land it I will add
     the '+'-named tooth to R39 so the trap cannot return.

  2. A MATCHING RESTATEMENT DESERVES A MATCH-ON-FILE SENTENCE. "Just to
     confirm, our annual revenue is 1,553,000" (on file: 1,553,000) got
     "I wasn't able to apply that change just now - could you tell me
     exactly which field to change..." The figure gate itself behaved (its
     "I haven't recorded that figure" text never fired -- correct, the
     figure IS recorded), and this is honest about the write -- but it is
     wrong about the client's intent, and the next Cowork client who
     confirms a number meets it. Deterministic fix, no naturalizer needed:
     on the no-write tail, when every figure the client stated matches a
     stored value, say the match ("That matches what I have - annual
     revenue is $1,553,000") instead of the failed-change sentence. My
     probe Test Files/_mini_cw031_r9_f1_residue.py B1 is the check; B2 and
     the four A-cases must stay clean.

  3. POLISH, cosmetic: the separation acknowledgment names only the first
     three lines (separated[:3] slice) -- "keep every one of them separate"
     on four lines acked three by name. Say all of them or say "and N
     more"; the artifact is right, only the sentence under-counts.

  Standing laws apply: restart the backend after app-code edits and verify
  ONE :5050 listener, one Sunny_V3 canary before any batch, red-proofs red
  for the right reason, never end a turn with a job running.

  ANSWERED from your round-9 TASK, so you do not re-derive: (item 3) the
  blend patch rate is 3/4 on plain wordings, the floor fires on hedged
  forms ("about 45 percent") -- do NOT widen the router instruction on this
  evidence; (item 1) refusal rate on clear wordings 0/3 across my live
  cases; (housekeeping) your A1 re-point stands as written, verified 9/9 on
  current code, and with R38/R39 in the gate both round-8 instruments are
  records now, not instruments.

  NOT YOURS: R38 and R39 (fix 56717dd, baseline 858987b) are mine and
  proven; the '+'-tooth extension of R39 after your fix 1 is also mine.
  MINI_NOTES.md round-11 section documents both legs and the deliberate
  '+' limit.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a deterministic
  receipt. This turn's B1 finding is the same ruling's shadow: removing the
  naturalizer from no-write turns fixed the manufactured ack and exposed
  that the deterministic sentence has one register (failed change) for
  turns that are not change attempts. Fix 2 closes that deterministically;
  the ruling still governs write-carrying turns.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: match_on_file:first-matching-leaf-names-wrong-field
  EVIDENCE: _mini_cw031_r10_audit_20260813.txt (the full round-10 audit);
    _prove_20260813_mini_round10.txt (58 legs, R40 PROVEN, 0 DRIFT,
    0 UNEARNED, GREEN); _mini_cw031_r10_live_20260813.txt (W1-W5);
    replay_gate/MINI_NOTES.md round-12 section
  SUMMARY: Turn 13 is finished: the prove that died with the previous
  session was re-run IN THE FOREGROUND and read this turn. Table CLEAN:
  58 legs, 51 behavioural, 5 structural-absence, 2 golden, 0 DRIFT,
  0 UNEARNED, gate GREEN. R40 membership-is-data is PROVEN BEHAVIOURAL --
  red at 5dcbca4 citing exactly its two reasons (the '+'-named group died
  in its own declaring call via the split('+') trap; members=None), with
  the agreeing-mixed positive control still green there, green at HEAD.
  Round 10's fixes are real and held live ('Hard goods + Sundries'
  declared through the real router, members read back off the rows).
  Not green because the AUDIT is not clean: D1 LIVE -- the match-on-file
  sentence names the FIRST leaf whose value matches, so a client who
  restated their annual interest payment (9,800) was told "monthly rent
  expense is $9,800" (census: 92.7% of 4,674 real drafts carry one value
  under 2+ leaf names -- the collision is the norm, not the edge). D2
  latent -- the 0.5% tolerance can speak a swallowed near-miss CORRECTION
  as a match. D3 structural, low reach -- the retire's grouping key is
  still the label string, so a label collision or a stale legacy row
  kills a fresh declaration in its own call.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: three fixes, all with reproductions, line-level mechanisms, censuses
  and fix shapes in _mini_cw031_r10_audit_20260813.txt.

  1. D1, THE LIVE ONE. A match may name a field ONLY when exactly one
     DISTINCT leaf name matches the stated value. Multiple distinct names
     -> speak the value with no field claim: "That matches a figure I have
     on file - $9,800." Exactly one (the common case) -> name it as today.
     Deterministic, no NLP, no router change; do not fix it by consulting
     the client's words. Ravenwood's own rent==interest is the live case;
     _mini_cw031_r10_match_attack.py A-cases are the checks.

  2. D2, ONE CONSTANT. The match tolerance max(0.5, 0.005*|v|) is doing
     unowed work: 1,548,000 "matches" a stored 1,553,000, so a swallowed
     near-miss correction gets "that matches what I have" and the client
     keeps the old number. The only legitimate need is float dust --
     make it max(0.5, 1e-9*|v|). Nothing legitimate needs 0.5%.

  3. D3, COMPLETE YOUR OWN PRINCIPLE: membership became data, identity
     did not. The coherence pass still groups carrying rows BY LABEL
     STRING, so (a) 'A+B','C' vs 'A','B+C' collide on 'shared:a+b+c' and
     declaring the second retires ALL FOUR rows including the group being
     declared in that call, and (b) a stale label-only legacy row kills a
     fresh members-carrying declaration. Partition by stored member
     frozenset: a partition whose stored set equals the names of the rows
     carrying it is coherent and survives; retire only failing claims.
     Re-run Test Files/_mini_cw031_r10_retire_attack.py: O1 and O2 must
     go clean, O3/O4/O4b must stay clean.

  Standing laws apply: restart the backend after app-code edits and verify
  ONE :5050 listener, one Sunny_V3 canary before any batch, red-proofs red
  for the right reason, never end a turn with a job running.

  NOT YOURS: R40 is in the gate and proven; the prove file is
  _prove_20260813_mini_round10.txt. I did NOT pin the match-on-file
  sentence -- pinning today's shape would pin D1/D2 (the round-8 lesson).
  Land fixes 1-2 and I will pin R41 next turn: "a match never names an
  ambiguous field, a near-miss never claims a match" -- the shape is
  ready in my probes. After fix 3 I will extend the retire coverage the
  same way. Housekeeping already done: _mini_cw031_r9_coherence_attack.py
  is the round-9 record, not an instrument; my round-10 probes are
  Test Files/_mini_cw031_r10_{match_attack,retire_attack,live,peek}.py.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a
  deterministic receipt. Nothing this turn moves it; D1/D2 are
  deterministic-sentence defects, which is exactly why they are fixable
  in code without the ruling.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: cw031:round11-awaiting-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-031 ROUND 11 section;
    Test Files/_redproof_cw031_round11_fixes.py;
    Test Files/_redproof_cw031_round11_ablate.py;
    _redproof_cw031_round11_ablate_20260813.txt;
    _canary_cw031_round11_sunnyv3_20260813.txt;
    _prove_20260813_vs_round11.txt; commit b0607e0
  SUMMARY: Your three round-10 fixes are landed. D1: a match names a field
  only when exactly ONE distinct leaf name matches; two or more distinct
  names return leaf None and the sentence speaks the bare value ($9,800 on
  file) - the distinct-NAME rule, so a value mirrored under one name still
  names it. D2: the tolerance is max(0.5, 1e-9*|v|); dust matches, a 0.32%
  correction never does. D3: the coherence pass partitions carrying rows by
  stored member frozenset - your O1 collision yields two coherent
  partitions and BOTH survive, O2's stale twin retires ALONE, O3/O4/O4b
  unchanged; the label parse survives only for pure-legacy labels. Your
  match_attack A1/A2 are re-pointed to the new law as RED conditions
  (header says so); retire_attack runs CLEAN unmodified. Twelve green
  checks, five ablations each red on their own check, none decorative.
  Canary on PID 12544 (postdates every edit, ONE listener): 471s,
  system_run_complete, 0 errors, delivery record #6 bound by draft_id.
  Prove: 58 legs, 0 DRIFT, 0 UNEARNED, GREEN; R40 held untouched. Not
  green: none of it is artifact-audited by you, which is Nick's standing
  law for this batch.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit round 11 at the ARTIFACT level. Mechanisms, edges, and one
  deliberate judgment call are in VS_NOTES ROUND 11.

  1. THE LEGS YOU PROMISED. R41 (a match never names an ambiguous field,
     a near-miss never claims a match) - you said land D1/D2 and you
     would pin it; the shapes are in your probes and my
     _redproof_cw031_round11_fixes.py checks 1a-2c. And the retire
     coverage extension you promised after D3.

  2. THE JUDGMENT CALL I MADE WITHOUT YOU, ratify or overturn: at the
     PURE-LEGACY tier (no member list anywhere under a label), an
     off-claim row now retires ALONE and the coherent remainder
     survives; round-10 code retired the WHOLE label set. Consistent
     with retire-only-failing-claims, but it is my reading of your
     principle, not your ruling. Check 3d/3e in the redproof are the
     shapes.

  3. D1's LIVE RATE, the honest cost of the law. Your own census says
     92.7% of drafts carry a collision, and most are DERIVED TWINS
     (current_revenue == revenue totals, annual_wage ==
     year1_payroll_amount - your W5b). Under the new law those
     confirmations speak the bare value with no field name. Drive live
     restatements on a real clone and say whether the bare-value
     sentence is acceptable client-speak at that rate, or whether
     derived twins (mirrors of the SAME quantity) deserve a same-
     identity rule so the common case can keep its name. I did not
     build that - it needs a mirror map nobody has ruled on.

  4. MY LIVE GAP, stated plainly: no live router turn this round. All
     three fixes are deterministic functions proven at function level
     plus a clean canary; the match sentence and the retire have not
     been driven through the live router since the change. Your live
     wordings are the check that counts under Nick's law.

  Standing laws apply: restart the backend after app-code edits and
  verify ONE :5050 listener, one Sunny_V3 canary before any batch,
  red-proofs red for the right reason, never end a turn with a job
  running.

  NOT YOURS: nothing in replay_gate gate code changed; R40 passes
  untouched on the D3 rewrite (the prove file is
  _prove_20260813_vs_round11.txt).

  STILL NICK'S, UNCHANGED: whether naturalization may touch a
  deterministic receipt. Nothing this round moves it - all three fixes
  are deterministic-sentence or state-coherence changes, which is
  exactly why they were fixable without the ruling.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: cogs_group:legacy-parse-partition-order-dependent
  EVIDENCE: replay_gate/MINI_NOTES.md round-13 section (the full audit);
    _prove_20260813_mini_round11.txt (60 legs, R41+R42 PROVEN, 0 DRIFT,
    0 UNEARNED, GREEN); _mini_cw031_r11_live_20260813.txt /
    _mini_cw031_r11_live_b_20260813.txt (live transcripts);
    Test Files/_mini_cw031_r11_*.py (four probes)
  SUMMARY: Round 11 holds everywhere it is live. R41 and R42 are in the
  gate, both proven behavioural at 55f0ae0 on exactly their own teeth (rent
  named on an interest restatement + 0.32% swallowed as a match; both
  collided groups retired + a stale twin killing the fresh declaration).
  The deterministic branch is proven live with my own wordings: the
  rent==interest collision speaks '$9,800 on file' bare, a derived twin
  speaks bare against real stored float dust, a unique name keeps its
  field, and no restatement changed state. The near-miss correction now
  LANDS as a real write. Disjoint groups + separation through the live
  router: clean, retire spoken, other group byte-identical. Item 3 RULED:
  keep the bare-value sentence, build no mirror map (6 of 39 stored values
  collide on the real clone; question-form confirmations already get the
  field named back via the answer path). Not green: your judgment call's
  PRINCIPLE is ratified but its implementation is an accident of row order
  (T1a stale-last retires alone; T1b stale-FIRST retires everything,
  because the first legacy row creates and joins the parse partition even
  when off-claim), and a stale label-only twin under a duplicate product
  name attaches to a fresh members partition and keeps a group it never
  earned (the name set dedups). Census: both LATENT, zero reach today (0
  label-only rows, 2 dup-name drafts, 0 of them grouped).
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: two fixes, both in the coherence pass's legacy handling
  (intake_consult.py ~3189-3201), both latent-by-census so no canary debt
  beyond the standing one. Reproductions:
  Test Files/_mini_cw031_r11_legacy_order_attack.py (T1b, T2) and the
  round-13 section of MINI_NOTES.md.

  1. MAKE THE LEGACY TIER A LAW, NOT AN ACCIDENT OF ORDER. The parse-
     fallback partition is created by whichever legacy row iterates FIRST
     (`elif not _parts`), and that row JOINS it even when its own name is
     off-claim, poisoning the partition: same rows, stale-last retires it
     alone, stale-first retires all three. Two acceptable shapes; pick one:
     (a) derive the parse partition from the LABEL once per label and
     attach only rows whose name sits in the parsed key - off-claim rows
     go stale regardless of order (keeps your redproof 3d/3e as written);
     (b) delete the pure-legacy fallback entirely per Nick's remove-legacy
     law - census says 0 real rows carry a label without a member list,
     so the branch is dead code; re-point your 3d to the new behaviour.
     KEEP the legacy ATTACH path either way: R40's agreeing-mixed control
     pins it. T1a AND T1b must both go clean; R42 deliberately does not
     pin this tier, so either shape lands without redding the gate.
  2. A LEGACY ROW MUST NOT ATTACH TO A PARTITION THAT ALREADY CARRIES ITS
     NAME. T2: a stale label-only twin named 'Alpha' (duplicate product
     name, other LOB) attaches to the fresh {alpha,beta} members partition
     and SURVIVES with the group/basis it never earned, because the
     coherence test compares name SETS and the duplicate disappears in the
     dedup. A legacy row whose name is already present on a members-
     carrying row in that partition is stale, not homed. Reach today: 2 of
     3,303 ops drafts carry duplicate names, 0 grouped - fix it while it
     costs nothing.

  After both land I will extend R42 with the legacy-tier tooth so the
  order-independence is pinned permanently.

  ANSWERED, your four items: (1) R41 + R42 are in the gate, both proven
  behavioural, full prove 60 legs / 0 DRIFT / 0 UNEARNED / GREEN. (2) Your
  pure-legacy judgment call: PRINCIPLE RATIFIED - retire-only-failing-
  claims is the right reading and I am keeping it; the implementation is
  the defect above, not the ruling. (3) The bare-value sentence is
  acceptable client-speak at the measured rate - live it reads naturally,
  the client's own words carry the field one sentence earlier, and
  question-form confirmations still get the field named back through the
  answer path (part-A transcripts). Do NOT build the mirror map; it is
  standing machinery with drift risk to buy one word. If a live Cowork
  client ever stumbles on the bare sentence, that is the moment to bring
  it to Nick, with the transcript. (4) Your live gap is closed: the
  deterministic branch fired on all three registers with my wordings and
  zero state changes (_mini_cw031_r11_live_b_20260813.txt).

  Standing laws apply: restart the backend after app-code edits and verify
  ONE :5050 listener, one Sunny_V3 canary before any batch, red-proofs red
  for the right reason, never end a turn with a job running.

  NOT YOURS: R41/R42 and the round-13 notes are mine. Your round-11
  instruments stand as written - I re-ran both redproofs and both of my
  round-10 instruments unmodified before attacking.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a
  deterministic receipt. Nothing this round moves it - the deterministic
  match sentence shipped verbatim in every live reply I read, which is
  the no-write rule from round 9 doing its job.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: cw031:round12-awaiting-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-031 ROUND 12 section;
    _redproof_cw031_round12_prefix_20260813.txt (pre-fix red);
    _redproof_cw031_round12_ablateA_20260813.txt / _ablateB (per-fix
    ablations); _redproof_cw031_round12_postfix_20260813.txt (4/4);
    _canary_cw031_round12_sunnyv3_20260813.txt;
    _prove_20260813_vs_round12.txt
  SUMMARY: Your two legacy-tier fixes are landed, shape (a). The parse
  partition is derived from the LABEL once per label before any row is
  looked at; legacy rows join listed and parsed partitions by ONE rule
  (name in key), so the `elif not _parts` first-row minting is deleted,
  not routed around. And no legacy row attaches to a partition that
  already carries its name - I broadened your rule from members-carrying
  rows to ANY row, so a second same-named twin cannot ride in behind a
  first legacy attach. Your probe was this round's red-proof: red on
  exactly T1b+T2 at pre-fix HEAD, 4/4 after; two single-fix ablations
  each red on their own check alone. Round-11 redproof 12/12 with 3d/3e
  as written; your retire_attack and match_attack clean unmodified.
  Canary on listener 21208 (21:26:36, postdates last edit 21:25:53):
  system_run_complete 369s, zero error lines, delivery record #7 bound
  by draft_id, basis delivery record. Prove: 60 legs, 53 behavioural,
  5 structural-absence, 2 golden, 0 DRIFT, 0 UNEARNED, CLEAN. Not
  green: not artifact-audited by you, Nick's standing law.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit round 12 at the ARTIFACT level, then the tooth you
  promised. Mechanisms and the honest edges are in VS_NOTES ROUND 12.

  1. THE R42 LEGACY-TIER TOOTH. You said after both fixes land you
     would extend R42 so the order-independence is pinned permanently.
     The red shapes are your own T1b and T2; pre-fix HEAD for this
     round is commit b0607e0 (the round-11 final), where both red for
     their own reasons (_redproof_cw031_round12_prefix_20260813.txt).

  2. TWO JUDGMENT CALLS I MADE WITHOUT YOU, ratify or overturn:
     (a) SHAPE (a) OVER (b). I kept the label-parse fallback (lawful,
         order-free) rather than deleting it, because deleting retires
         every pure-legacy COHERENT group on its next unrelated write,
         which contradicts retire-only-failing-claims for a claim that
         holds when read. The order-dependent branch itself is deleted.
         If you rule the whole tier should die per the remove-legacy
         law (census: 0 label-only rows), it is now a three-line
         deletion and my 3d re-points.
     (b) THE GUARD IS ANY-ROW, NOT MEMBERS-CARRYING-ROW. Your rule
         said a name "already present on a members-carrying row"; mine
         refuses on any row already in the partition, so twin #2 cannot
         attach behind twin #1's legacy attach. Attack it: is there a
         legitimate attach my broader guard now refuses?

  3. THE RESIDUAL ORDER EDGE, stated plainly in VS_NOTES: two
     same-named legacy rows competing for one on-claim slot - first in
     document order attaches, second goes stale. Partition outcome is
     order-free; WHICH twin keeps the label is not. Census reach 0
     today. Rule whether both should be refused instead (two-line
     change) or the edge stands documented.

  4. THE EMPTY PARSE PARTITION. When every legacy row under a label is
     off-claim, the pre-created partition ends the pass empty and
     retires nothing extra. I claim no behaviour rides on the empty
     container - verify, since it is a new object the old code never
     created.

  Standing laws apply: restart the backend after app-code edits and
  verify ONE :5050 listener, one Sunny_V3 canary before any batch,
  red-proofs red for the right reason, never end a turn with a job
  running.

  NOT YOURS: nothing in replay_gate gate code changed this turn; R40,
  R41, R42 all pass untouched on the rewrite
  (_prove_20260813_vs_round12.txt).

  STILL NICK'S, UNCHANGED: whether naturalization may touch a
  deterministic receipt. Nothing this round touches prose at all.
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
  ERROR-SIGNATURE: cw033:awaiting-mini-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-033 TURN 2 section;
    python/client_intake_and_finmo/post_intake_headcount/
    deterministic_revenue_proposer.py:204-212 (the stamp);
    revenue_critique.py:78-98 (the hash the stamp cannot re-key);
    intake_consult.py:17879-17906 (the naturalization enforcement);
    intake_coherence/section.py:2648 (_safe_naturalize)
  SUMMARY: Nick's revision is landed, all reading and rulings, zero app-code
  edits (so no canary owed). (a) The forward-only law is recorded in
  VS_NOTES; it also settles turn 1's LEFT-FOR-A-RULING - the CW-032 (#264)
  and CW-017b doors STAY. (b) The anchor_reconcile stamp is INERT: written
  after all driver math, read by no consumer (every reader takes named keys
  only), and excluded from the critique lock hash - KEPT per the condition.
  (c) The naturalization ruling IS landed (VS_NOTES ~1817) and enforced at
  every prose layer; NO code path re-derives a number in prose; one residual
  named not rebuilt (write-carrying acks see user_message as context -
  instruction-bounded, works, pre-existing). A-116 stands adjudicated
  ON-PATH on the app's own written contract, already fixed + pinned (#115
  retested_clean, R02/R15 PROVEN). THE BOARD CONFIRMED: A-115's two
  kind-misreads rank 1 (BOTH FIXED turn 1, live-proven L5/L6, awaiting your
  artifact audit), A-112 receipt fidelity, A-106 retention probe, CW-023
  owner-pay (needs a completed build), and owner_draw_ceiling now formally
  ON the board. Discovery spec stands delivered (docs/STREAM_DISCOVERY_
  SPEC.md, five open questions for Nick).
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: artifact-audit CW-033 turn 1 (the audit task Nick's revision
  superseded - this restates it, merged with the revision). My pass lines
  are not evidence. Mechanisms in VS_NOTES CW-033 TURN 1 + TURN 2.

  1. A-115a ON THE REAL SHAPES. Rewind clones of Thornfield d9b17850 to
     [75]-[78] with your own wordings ("one shared rate at 58 percent"
     variants): NO unit_price write, NO retention_pending stamp, no
     self-triggering recovery; the 58% lands only as the COGS collapse
     group. Read rows, not replies. The retention stamp is read-back
     gated now - try to make it stamp without a landed price write.
  2. A-115b CAPEX. [89]'s "not recently, no" shape: capex stores 0, the
     excluded $380k is captured NOWHERE (equipment base asked once, no
     double-count), and "No wait, it was 380,000" still lands via the
     lookahead. KNOWN EDGE handed forward: a negative-lead answer that
     ALSO states a real purchase ("none of it this year - but we did
     spend 15,000 on a mower") is forced to 0 by
     _capex_answer_expresses_none. Confirm the reach and rule the
     but-we-did carve-out fix shape (flagged in VS_NOTES, not built).
  3. A-112 ACK CONTRADICTION - the one fix with NO live artifact. Drive
     an ops-section multi-line capture whose router patch drops driver
     fields and read the reply: the unapplied-fields note must be
     re-validated against post-followup state (fields recorded in the
     same reply must not be claimed unrecorded).
  4. THE REDIRECT (A-113 retraction shape). Mid-interview ops-lever
     correction: honest redirect leads, NOTHING written, no fabricated
     receipt, ops forward-moves suppressed that turn. At the wall,
     corrections still land (CW-026 machinery untouched). Attack the
     single-row boundary: a single-row draft whose message names a
     DIFFERENT product than the row - the applier lands it on the one
     row (CW-026 worst-case-correctable-proposal); say if you rule
     otherwise.
  5. (b) INDEPENDENT CHECK, cheap: confirm the anchor_reconcile stamp
     cannot re-key the critique lock (hash covers lines only) and no
     reader consumes it - my evidence is VS_NOTES TURN 2.
  6. REGISTRY HYGIENE, yours or Cowork's: the A-113-family rows
     (capacity_correction_after_stage_close_never_lands x2,
     ack_claims_a_capacity_write) still read open-blocker; they predate
     the retraction and need the off-path/observation stamp.

  NOT YOURS: the forward-only law means NO retrofit hunting - audit the
  turn-1 fixes and the reachable path only. Discovery spec is Nick's to
  answer (five questions in the doc). Green stops for Nick.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: interview_ack:claims-suppressed-ops-write
  EVIDENCE: _mini_cw033_t1_audit_20260814.txt (the full audit);
    _mini_cw033_t1_live_20260814.txt / _live2 (live rounds 1-2);
    _mini_cw033_t1_detect_20260814.txt (offline detector diagnosis);
    _mini_cw033_registry_stamp_20260814.txt (item 6);
    _prove_20260814_mini_cw033.txt (61 legs, 0 DRIFT, 0 UNEARNED, CLEAN);
    Test Files/_mini_cw033_*.py (five probes);
    replay_gate/MINI_NOTES.md round-16 section
  SUMMARY: The turn-1 fixes HOLD where they were built: A-115a is clean on
  my own wordings (58% lands only as the declared COGS group, no price/
  capacity/util write, retention never stamped - read at its REAL home,
  _coherence; VS's L6 checked a key that never exists), A-115b stores 0
  with 380k nowhere and the lookahead lands the correction, the wall
  landing works with both capacity twins agreeing, the single-row landing
  is RATIFIED, the stamp is confirmed inert, and my own foreground prove
  is CLEAN (61 legs, 0 DRIFT, 0 UNEARNED). Not green for three live
  defects. M1: one reply carried the honest redirect PLUS "Got it -- I'll
  update the hard goods checkout ticket price to 99" (nothing written),
  two phantom unapplied-notes, and "Also recorded:" over three unwritten
  figures - F1(b) is unenforced on the financials interview path, and it
  is VS's turn-2 "residual" observed as reachable. M2: the redirect's
  detector needs the word capacity/price/utilization while the lander
  understands "7 jobs a week" - my wording LANDED install 7/7
  mid-interview with a Recorded receipt and no redirect: the retracted
  off-path landing survives through the back door. M3: at the wall, "40 a
  week" on Sumac's contract-cadence row stored period=40 / wk=9.23 with
  receipt "Recorded: capacity 40" - the stated cadence is discarded and
  the client cannot see it. Also: the B3 capex edge is CONFIRMED live
  (the mower's 15,000 dies into a forced 0) and reachable. A-112's note
  re-validation is code-sound but still has NO live artifact - both my
  rewind attempts produced unreachable states, documented. Registry:
  #264 stamped off-path per the retraction; #132 KEPT OPEN deliberately
  (honesty row - M1 is its class, live today).
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: four fixes. Reproductions, line numbers, and ruled fix shapes for
  every one are in _mini_cw033_t1_audit_20260814.txt.

  1. M1, THE ONE THAT MATTERS. No sentence of the financials INTERVIEW
     reply may claim a write the turn did not make. My A4b turn (full
     reply in _mini_cw033_t1_live2_20260814.txt) shipped, in ONE reply
     with ZERO writes: the honest redirect, then "Got it -- I'll update
     the hard goods checkout ticket price to 99", "(One note: I couldn't
     apply your rent change...)" (rent never mentioned; the router
     misread the bare 99), "(One note: I haven't recorded other
     operating costs yet...)", and "Also recorded: cogs total year1
     $745,353, current revenue $1,730,000, marketing percent of revenue
     2%" - three on-file values spoken as newly recorded. This is the
     receipt-without-a-write class on the path the round-8/9 gates never
     covered, your own turn-2 residual now observed live, and #132's
     class recurring as a price variant. Trace the emitting layers (the
     ack half looks like router prose surviving; 3-5 are say-do notes +
     disclosure composed from a misread patch) and put the F1(b) rule at
     this ship gate: acks and "recorded" claims speak only from the
     turn's receipt; on an ops-redirect turn the stage half must not
     re-ack the suppressed figure. My A4b wording is the red shape.
  2. M2, THE BACK DOOR. The redirect detector (_apply_cross_section_
     driver_correction leaf probe, intake_consult.py:6858-6863) requires
     the literal words capacity/price/utilization; the forward-move
     lander understands "7 jobs a week", so my D1 wording landed install
     7/7 MID-INTERVIEW with a "Recorded:" receipt and no redirect
     (offline: triggered_leaf=None on my wording, triggers on your
     verbatim [99]/[107]/[111]). RULED SHAPE: enforce at the WRITE door,
     not the detector - the forward-move ops branch refuses/redirects
     when a financials stage is active, and the wrapper's detect stays
     only for the redirect copy. One authority; widening the regex just
     re-splits the vocabulary and it drifts again.
  3. M3, THE CADENCE MISREAD. At the wall, "capacity should be 40 a
     week, not 34" on a unit_cadence='contract' row (periods 12) wrote
     period=40 and derived wk=9.2308; receipt "Recorded: capacity 40."
     The client said 40 A WEEK and the model now holds 9.23 a week.
     RULED SHAPE: parse the stated cadence from the correction text;
     matching cadence lands as today; differing cadence CONVERTS into
     the canonical field (40/wk -> 173.3/period at periods=12) or asks
     when ambiguous; the receipt always speaks the client's own cadence
     ("capacity 40 a week"). Red shapes: my D3 (wrong number today) and
     D2 as the weekly-row control (must stay 7/7).
  4. THE CAPEX CARVE-OUT, now confirmed live (B3): "No, none of it was
     bought this year - but we did spend 15,000 on a mower back in
     January" stores 0 and the 15,000 dies. Reachable answer to the
     solicited capex question -> fix-as-bug under the forward-only law.
     Shape: in _capex_answer_expresses_none (:8347), a but-we-did
     carve-out (`but we did|except|apart from|other than|aside from` +
     figure) returns False, with the landing numeric scoped to the
     post-carve-out clause so the EXCLUDED figure still cannot land.
     Red-proof both halves in one message (15,000 lands, 380,000 does
     not).

  HOUSEKEEPING, yours: _live_cw033_capacity_turns.py L6 reads
  fin.get("intake_coherence") - a key that never exists (the real home
  is financials._coherence.retention_pending, section.py:104-111), so
  its retention check is vacuously green. Re-point it. Also know your
  rewind clones inherit the STALE retention frame the pre-fix run
  stamped at [78] - strip it at clone time (my live2 make_clone shows
  the hygiene) or retention checks false-fail.

  A-112, still owed A LIVE ARTIFACT (not by synthetic rewind - both of
  my attempts produced unreachable states, documented in the audit):
  on the next real early-stage run (Cowork or persona), grep the
  transcript for a reply opening "(One note: I haven't recorded" and
  verify the named fields were NOT stored that turn. The mechanism is
  code-sound; the class's live face this turn is M1.

  Standing laws apply: restart the backend after app-code edits and
  verify ONE :5050 listener, one Sunny_V3 canary before any batch,
  red-proofs red for the right reason, never end a turn with a job
  running.

  NOT YOURS: the registry stamps are done (#264 resolved with the
  retraction in the note; #132 stays open until M1 lands with artifact
  evidence - do not re-stamp it). No gate legs changed this turn, on
  purpose: pinning today's M1-M3 shapes would pin the wrong thing. After
  your fixes land I will pin three legs: "a reply never acks an unlanded
  ops figure", "mid-interview ops landings are impossible regardless of
  wording", "a stated cadence is never silently re-based".

RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: cw033:turn3-awaiting-artifact-audit
  EVIDENCE: replay_gate/VS_NOTES.md CW-033 TURN 3 section;
    Test Files/_redproof_cw033_turn3_fixes.py;
    Test Files/_redproof_cw033_turn3_ablate.py;
    Test Files/_live_cw033_turn3_turns.py;
    _redproof_cw033_turn3_prefix_20260814.txt (pre-fix RED);
    _redproof_cw033_turn3_fixes_20260814.txt (24/24 GREEN);
    _redproof_cw033_turn3_ablate_20260814.txt (4 ablations);
    _live_cw033_turn3_20260814.txt (W1-W5b GREEN);
    _canary_cw033_turn3_sunnyv3_20260814.txt;
    _prove_20260814_vs_cw033_turn3.txt; commit 02effe1
  SUMMARY: All four fixes are landed at the layers you ruled. M1: the
  interview reply speaks only from the receipt - your A4b turn now reads
  redirect + a bare ack + the standing question; the fabricated price ack,
  both phantom notes, and the false Also-recorded are gone at four distinct
  emitting layers (ack fallback gated by the write-claim/figure-ack probes;
  redirect-consumed figures are turn-wide references that a misread patch
  cannot re-land or re-note; Also-recorded speaks only values that CHANGED).
  M2: the boundary lives at the write door - _apply_forward_move's ops
  branch refuses with the honest redirect whenever a financials stage is
  active, whatever the wording; your keywordless 7-jobs-a-week now
  redirects mid-interview and still lands 7/7 at the wall. M3: the stated
  cadence converts (40/wk -> 173.33/period on Sumac live, week twin reads
  exactly 40) or asks when ambiguous; the receipt speaks the client's own
  cadence and discloses the modeled figure. B3: the mower's 15,000 IS the
  capex, the excluded 380k lands nowhere, the plain no still stores 0.
  Pre-fix red on exactly the fix checks, four ablations each red on their
  own checks alone, none decorative. Sunny_V3 on PID 11032 (postdates every
  edit): system_run_complete, 484s, zero error lines, delivery record #22
  bound by draft_id. Prove: 61 legs, 54 behavioural, 5 structural-absence,
  2 golden, 0 DRIFT, 0 UNEARNED, CLEAN. L6 re-pointed + clone hygiene
  landed. Not green: none of it is artifact-audited by you yet.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  mini: audit turn 3 at the ARTIFACT level - my pass lines are not
  evidence, and W1's clean reply least of all (the router still composed
  it; the gates just filtered it). Mechanisms in VS_NOTES CW-033 TURN 3.

  1. M1 ADVERSARIALLY, live, your own wordings. The fix is four separate
     gates and the class is "a sentence outruns the receipt" - attack the
     seams between them: a redirect turn whose message ALSO carries a
     genuine stage answer ("...price to 99 - oh and rent is 2000": the
     2000 must land + be receipted, the 99 must not be spoken as recorded,
     the rent note must not die with the phantom filter); a redirect turn
     where the router figure-parse fails (consumed_figures then carries
     candidates, not a landing - do the filters still hold); a NON-redirect
     turn with a genuinely dropped stated field (the say-do note must
     STILL ship - my filter is redirect-turns-only by design, verify the
     scoping). And the Also-recorded change filter: a correction that
     moves a field by less than the no-op tolerance must not be spoken.
  2. M2: try to land ANY ops lever mid-interview through the forward
     mover - volunteered first-captures ("my unit price is 650" on a
     null-price row mid-rent), not just corrections; the door refuses on
     stage-active alone. Then the leg you promised: "mid-interview ops
     landings are impossible regardless of wording" - the door is the
     choke point now, so the leg pins the door, not the detector.
  3. M3 ADVERSARIALLY: wordings where a cadence word is present but NOT
     the capacity's ("40 contracts, we bill monthly" - does "monthly"
     mis-bind to the 40?), a weekly row told a monthly figure, and the
     no-op edge (stored period=40, client says "40 a week" - must CONVERT,
     not silently no-op; the early-check bypass exists for exactly this).
     Your D3 red shape + D2 control are in my live script, rerun them.
  4. THE XSEC DOOR'S CADENCE (flagged, not built): the CW-017b
     market/people door lands capacity without the reconciler
     (intake_consult.py ~6990). Pre-existing door, no artifact, so under
     the forward-only law I left it. If you can produce a reachable
     wrong-number there, that is the exception clause and the fix is the
     same helper at that door's capacity branch - say so and I build it.
  5. THE LEGS: the three you promised are now pinnable ("a reply never
     acks an unlanded ops figure", "mid-interview ops landings are
     impossible regardless of wording", "a stated cadence is never
     silently re-based") plus the capex carve-out if you judge it leg-
     worthy. Pre-fix red shapes are in _redproof_cw033_turn3_prefix (the
     13 reds at 6d38c54, each for its own reason).
  6. #132 closes on YOUR artifact read of M1, not mine - the registry
     stamp is yours when W1's class holds under your attack wordings.

  A-112, STILL OWED (unchanged): a live artifact from a real
  conversational early-stage run. The bypass canary has no interview
  turns. Partial evidence this turn: W5's reply carried the initial-assets
  note and the field was verifiably unstored - the note spoke truly; the
  re-validation half (a note dropped because the same reply recorded the
  field) remains unexercised live. Next real Cowork/persona run: grep for
  replies opening with the note and diff named fields against that turn's
  writes.

  NOT YOURS: nothing in replay_gate gate code changed this turn; R33-R42
  all pass untouched (_prove_20260814_vs_cw033_turn3.txt, table identical
  to yours). The board order stands: A-115's two were fixed turn 1, M1-M3
  landed this turn, then A-112 receipt fidelity, A-106 retention probe,
  CW-023 owner-pay, owner_draw_ceiling orphan.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a
  deterministic receipt on write-carrying turns (the one residual named
  in VS_NOTES turn 2). M1's fixes are all deterministic-layer - which is
  exactly why they were buildable without the ruling.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: forward_move:dropped-field-figure-rehomed-onto-stage-write
  EVIDENCE: _mini_cw033_t3_audit_20260814.txt (the full audit);
    _mini_cw033_t3_live_20260814.txt (12 live turns, own wordings);
    _prove_20260814_mini_cw033_t3.txt (65 legs, R44-R47 PROVEN, 0 DRIFT,
    0 UNEARNED, CLEAN); Test Files/_mini_cw033_t3_live.py;
    _mini_cw033_t3_stamp132_20260814.txt;
    replay_gate/MINI_NOTES.md round-17 section
  SUMMARY: The four fixes hold where they were built. M2 is verified WHOLE
  (volunteered first-captures and corrections both refuse at the door, no
  writes, no false receipts); M1's gates against invention held on every
  seam I attacked (redirect+stage-answer, parse-fail, no-op restatement:
  zero false claims, and the genuine 2,000 rent landed beside the refused
  99); M3's core conversion is clean (26/mo -> 6.0/wk exact, D3/D2 rerun
  green); VS's redproof reran 24/24 unmodified. The four promised legs are
  R44-R47, ALL PROVEN BEHAVIOURAL at 6d38c54; #132 is CLOSED on the
  artifact read and stamped. Not green for four seam defects + one ruled
  build. D1, the one that matters: "rent is 2,400 a month, and we keep
  about 52,000 cash on hand" stored RENT = 52,000 - the forward mover
  re-attributed the dropped cash figure and OVERWROTE this turn's own
  correct 2,400 landing, while the same reply said cash was not recorded.
  D2: the cadence parse is message-scoped - "capacity should be 9, not 5.
  We invoice monthly." stored 2.08/wk. D3: the no-op edge is half-fixed -
  the disclosure's stored-value filter kills "40 a week" against a stored
  40 before the door's bypass can see it (dead-ends in the which-field
  register). D4/D5: register gaps (a landed stage answer ships as bare
  "Got it." on a redirect turn; a cadence ASK is followed by "intake is
  complete... every number you just set is yours"). And the xsec door:
  X2 offline proves the CW-017b capacity branch lands 40 RAW on the
  12-period row for "should be 40 a week, not 34" - reachable state,
  natural wording, live-precedented door, so the forward-only law's
  EXCEPTION CLAUSE fires: build it.
TASK:
  TURN-TIMEOUT-MINUTES: 240

  VS: five fixes. Reproductions, mechanisms, red shapes, and fix shapes
  for every one are in _mini_cw033_t3_audit_20260814.txt.

  1. D1, THE ONE THAT MATTERS. A figure whose OWN field was dropped by
     this turn's normalizer must never re-enter the forward mover as a
     homeless figure - its disposition IS the say-do note. And the
     forward mover must never overwrite a field this turn's stage patch
     just wrote (the turn's own write-set are references, the same law
     the redirect's consumed_figures already enforce). Live red shape:
     "Our rent is 2,400 a month, and we keep about 52,000 cash on hand"
     at the rent stage must end rent=2400.0 with cash noted - today it
     ends rent=52000.0 with a receipt speaking the clobber. This is a
     wrong number stored on the guided path; it outranks everything else
     here.
  2. D2, CADENCE BINDS TO ITS FIGURE. _stated_capacity_cadence scans the
     whole message, so "One fix - the install crew capacity should be 9,
     not 5. We invoice monthly." converts 9 into 2.0769/wk. A cadence
     counts as STATED only when it shares a sentence with a capacity
     figure; measured warning: "capacity sentence + next sentence" is
     NOT enough - my C1's "We invoice monthly." IS the next sentence.
     Cadence elsewhere = unstated (today's raw row-cadence landing).
  3. D3, THE OTHER HALF OF THE NO-OP BYPASS. Your fix makes the door's
     early no-op check stand aside for a stated cadence, but the
     disclosure's stored-value reference filters kill the figure first:
     stored period=40, then "Sorry - mowing capacity is 40 a week" ->
     no move, "could you tell me exactly which field to change" - the
     client named field, value, and cadence. Apply the SAME condition
     (_stated_capacity_cadence truthy on a capacity-keyword message) to
     the disclosure's restatement filters. Red shape: my C3 sequence;
     turn 2 must end period=173.3333.
  4. D4+D5, THE REGISTERS (both deterministic-layer). (a) A landed stage
     answer must be visible: on my A1 turn the rent 2,000 landed and the
     reply read redirect + "Got it." + next question - the client cannot
     know it landed. Make the write-derived stage ack name the landed
     value (at minimum when the reply also carries a redirect or a
     note); do NOT re-open the prose fallback - the gate is right, the
     code ack is thin. (b) An ASK holds the turn: the mixed-cadence ask
     shipped followed by "intake is complete... every number you just
     set is yours" in the same reply (C6). When the forward move returns
     an ask, ship the ask alone and stop.
  5. THE XSEC DOOR, ruled buildable under the exception clause: the same
     _reconcile_stated_capacity_cadence at
     _apply_cross_section_driver_correction's capacity branch (write at
     ~:7014) - convert or ask, receipt in the client's cadence. X2 in my
     audit is the offline proof (period=40 raw, ack "updated capacity to
     40"); reachability argument in the audit item 4. On ask, use the
     door's existing honest-refusal note path.

  ALSO KNOW, no action ruled: an ask turn's completion sync re-derived
  Sumac's stale week twin (34 -> 7.8462, canonical unchanged) - a
  written-nothing turn can still move a derived cell at rest (audit C6
  note). If you think that deserves more than documentation, say so.

  Standing laws apply: restart the backend after app-code edits and
  verify ONE :5050 listener, one Sunny_V3 canary before any batch,
  red-proofs red for the right reason, never end a turn with a job
  running.

  NOT YOURS: R44-R47 are in the gate and proven (do not touch legs.py);
  R46 deliberately does not pin D2/D3's shapes - after your fixes land I
  will extend it with the binding tooth and the disclosure tooth. #132
  is stamped resolved (manual/observational, artifacts in the note) - do
  not re-stamp it; a failing R44 or a live recurrence re-opens it. The
  #132-adjacent findings this turn (D1/D4/D5) are DIFFERENT classes and
  are filed above, not as recurrences.

  A-112, STILL OWED (unchanged): a live artifact from a real
  conversational early-stage run; my clones hit the same
  unreachable-state wall (X1's focus recompute included). Next real
  Cowork/persona run: grep replies opening "(One note: I haven't
  recorded" and diff named fields against that turn's writes.

  STILL NICK'S, UNCHANGED: whether naturalization may touch a
  deterministic receipt on write-carrying turns. Nothing this turn moves
  it - all five fixes above are deterministic-layer, which is exactly
  why they are buildable without the ruling.
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
  ERROR-SIGNATURE: none-turnA-awaiting-audit
  EVIDENCE: Test Files/_redproof_dealbreaker_turnA.py;
    _redproof_dealbreaker_turnA_PREFIX.txt (RED 10 on the stashed pre-fix
    tree); _redproof_dealbreaker_turnA_POSTFIX.txt (ALL GREEN);
    _prove_20260815_turnA_floor.txt (R31 + R32 GOLDEN, 0 DRIFT);
    VS_NOTES "DEAL-BREAKER BATCH TURN A" section (full fix shapes)
  SUMMARY: Turn A landed - A1, A2, A4, each SPOT-CHECK as declared.
    DECLARED-vs-ACTUAL: matches. Tier per fix = spot-check (A1: two
    value-selection branches inside one door, capacity branch untouched;
    A2: a reference exclusion that fires ONLY on messages carrying a
    net-N payment-term token - lives at the top of the shared
    _unlanded_figures_disclosure but is a broken-case-only branch; A4:
    prompt copy + a text scrub on the market finalize output). Loading
    as declared. Verify as declared: repro red->green per fix, artifact
    = stored ops row / move dict / rendered text in the proof output,
    floor via --only R31,R32 GOLDEN, canary SKIPPED, no full prove.
    Backend restarted after the edits, ONE :5050 listener. One
    divergence to note: the A1 repro wording needed a correction MARKER
    word ("fix the price - it should be 650 ...") - "should be" alone
    was never a marker and I did not widen the marker set (that would be
    new behavior). Flag for mini: Test Files/_redproof_cw033_fixes.py is
    stale on the PRE-FIX tree too (T1 attempt2 red, T4 tracebacks on the
    4-value _apply_forward_move) - pre-existing leg-craft, not this
    turn's regression, not repaired (out of scope).
TASK:
  TURN-TIMEOUT-MINUTES: 60
  mini - TURN B (SPOT-CHECK audit, minutes): the four confirmations on
  A1 / A2 / A4, per the itinerary in the seed above:
    1. Diff does what the plan said - git show HEAD for
       python/api_handlers/intake_consult.py (A1 ~6912-7010: price +
       utilization branches; A2: _payment_term_figures + the one-line
       _door_refs.extend in _unlanded_figures_disclosure) and
       python/client_intake_and_finmo/target_market_consultant.py (A4:
       three prompt copies + _strip_undeclared_price_tier +
       _scrub_finalized_copy on both finalize return points).
    2. Artifact shows the right value on each repro - run
       .venv\Scripts\python.exe "Test Files\_redproof_dealbreaker_turnA.py"
       yourself; compare with the PREFIX/POSTFIX files. Red-for-the-
       right-reason: PREFIX shows capacity 45.0 proposed on the real
       Fernhill sentence and 520/60% stored on the A1 shapes.
    3. Tier call honest - the one to scrutinize is A2: the guard sits at
       the top of the shared unlanded-figure path but only adds
       references when a net-N / N-day-terms token is present. If you
       judge that neighbor-check, name the neighbors (the small-figure
       attribution's price/capacity rules; the main path's
       _infer_figure_landing) and check them - my control leg ("40
       clients a month" still moves) covers the capacity one.
    4. Floor held - _prove_20260815_turnA_floor.txt, R31 + R32 GOLDEN.
  Also weigh, as a note not a build: A4 resolves "speak the actual
  position" as "state the price, claim no tier" because the app holds no
  market price fact at market finalize; a real position statement would
  need a captured market price = feature decision for Nick.
  Then flip and write VS's TASK for TURN C (A3 #101, travels ALONE,
  spot-check by default, neighbor-check only if the viability fix
  changes shared viability/engine code, full only if core money math;
  REPRO FIRST on a real shape where stated capacity is exceeded and the
  verdict still passes) - carry the TURN D itinerary forward verbatim
  from the seed. Feature decisions stay PARKED; the 20 WONT-FIX
  closures stand.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: none-turnB-audit-clean-turnC-pending
  EVIDENCE: _prove_20260815_turnB_floor_mini.txt (my own --only R31,R32
    re-run: 2 GOLDEN, 0 DRIFT, digests 72dfcb81f6f3 / 24e38de4dc98 /
    1d50e46ab8e6 / cbd764631e98 == VS's _prove_20260815_turnA_floor.txt);
    my own re-run of Test Files/_redproof_dealbreaker_turnA.py on HEAD =
    ALL GREEN (17/17), byte-equal to _redproof_dealbreaker_turnA_POSTFIX.txt;
    git show 4b8c581; _handoff/logs/watcher.log:6137 (VS TURN PLAN)
  SUMMARY: TURN B SPOT-CHECK audit of turn A - all four confirmations
    HOLD, tier calls HONEST, VS declared-vs-actual MATCHES (plan named
    intake_consult.py + target_market_consultant.py + a new redproof +
    floor via --only R31,R32 + canary skip; the commit touches exactly
    those, nothing else). (1) Diff: A1 = _xsec_scoped/_xsec_pick helpers
    + price & utilization branches only (capacity branch untouched); A2 =
    _PAYMENT_TERM_FIGURE_RE/_payment_term_figures + ONE _door_refs.extend
    at the top of _unlanded_figures_disclosure (feeds both the main
    reference filter and _small_refs); A4 = 3 prompt copies + scrub on
    both finalize return points. (2) Artifact: PREFIX red for the RIGHT
    reason (520/650/0.6/0.55 stored = the discarded figures; Fernhill
    net-45 -> capacity 45.0 move; net-30/net-60 too); POSTFIX + my rerun
    green with 650/700/0.75/0.8, move=None, control "40 clients a month"
    still moves 40. (3) Tier: A2 extends references only when the net-N
    regex fires - empty extend otherwise - so no live behavior flowing
    through the shared path changes on non-term messages; spot-check
    stands, no escalation. A1 confined to two branches; A4 no engine.
    (4) Floor held (independent re-run above).
    NOTES / CLOSURES (triage law): (a) A4 pre-fix red is STRUCTURAL
    (scrub absent + prompt string), not a behavioral copy red - the
    behavioral evidence is the Brightline transcript VS verified first;
    acceptable for a GPT-copy fix that cannot be red-proofed offline.
    (b) LATENT, unobserved, WONT-FIX unless a live artifact shows it: the
    market counter-edit path (intake_consult.py ~17514, router patch
    market.marketing_plan_summary) re-persists GPT-rewritten summary text
    WITHOUT the scrub; the client is dictating those edits and reads the
    result, no wrong claim observed - re-open on a live artifact.
    (c) _payment_term_figures also fires on "net 30% margin"-style
    phrasing; consequence is refuse-to-land (a reference), never a wrong
    write - WONT-FIX. (d) _declared() is substring-permissive ("value"
    in "we value quality" would license "value pricing") - cosmetic,
    requires GPT to also invent the tier - WONT-FIX. (e) VS's flag
    stands: Test Files/_redproof_cw033_fixes.py is stale on the pre-fix
    tree (T1 attempt2 red, T4 tracebacks on the 4-value
    _apply_forward_move) - I will handle it in TURN D with my own audit
    script rather than trust that file. (f) A4 "speak the actual
    position" = state the price, claim no tier: a real position
    statement needs a captured market price fact = FEATURE DECISION,
    parked for Nick with the other 10 - nobody builds it.
    Not green: turns C and D remain.
TASK:
  TURN-TIMEOUT-MINUTES: 120
  VS - TURN C (travels ALONE per the split law; nothing else rides):
    A3 (#101): a plan can PASS viability on volume ABOVE the client's
    stated capacity. DEAL BREAKER: the delivered plan certifies numbers
    the client told us they cannot produce. REPRO FIRST - red on a real
    shape where stated capacity is exceeded and the verdict still passes
    (name the production call chain first, per the E2E law; use a real
    transcript/draft shape, not a manufactured one) - then fix so the
    pass respects stated capacity.
    TIER: SPOT-CHECK by default - repro red->green, artifact (the
    verdict + the volume/capacity figures it judged), single-line floor
    via --only R31,R32. Expand to NEIGHBOR-CHECK only if the fix
    actually changes shared viability/engine code other live behaviors
    flow through - then name and check the neighbors on that path, not
    the universe. FULL apparatus (canary + full prove) ONLY if it is a
    core engine/money-math change. DECLARE the call + why in your TURN
    PLAN (turn-plan law) and confirm DECLARED-vs-ACTUAL in your RESULT.
    Restart the backend after app-code edits, ONE :5050 listener. Never
    end the turn with a job running. Feature decisions stay PARKED; the
    20 WONT-FIX closures stand; do not touch legs.py.
    Flip to mini with a TASK for TURN D, carried forward verbatim:
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
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none-turnC-A3-landed-turnD-audit-pending
  EVIDENCE: Test Files/_redproof_a3_capacity_fence.py (+ _PREFIX.txt red /
    _POSTFIX.txt ALL GREEN); Test Files/_neighbor_sweep_a3_capacity_wall.py
    (PRE/POST sweep of 40 real drafts, summary in VS_NOTES TURN C);
    _prove_20260815_turnC_neighbors.txt (R19,R21,U02,U05,R25,R30 GREEN);
    _prove_20260815_turnC_floor.txt (R31+R32 GOLDEN, digests unchanged);
    VS_NOTES 'DEAL-BREAKER BATCH TURN C' section
  SUMMARY: A3 (#101) LANDED. Bug re-proven live first: the fence tier
    (1.07^10) had no capacity term - F&F turn 96 (real draft 50658fff,
    first-capture facts) PASSED at $96,390/yr on a $70,200/yr physical
    ceiling (30/wk x $45 x 52). Fix = ONE home, evaluator.basis_from_intake:
    every coherence basis (fence/judged/corner/walk) caps its growth
    multiple at (stated capacity x price x periods at 100% util) x the
    engine's own 1%/q price path / anchor; non-unit models no wall; flat
    tier untouched; wall visible in the stamp (_coherence.eval.growth =
    requested/capacity_ceiling_multiple/used/capped). Anchor-hold ceiling
    arithmetic delegated to the same function. F&F now FAILS at 1.5825x
    (fixed_cost_burden/band/ni), stamp shows it. DECLARED-vs-ACTUAL:
    MATCHES - NEIGHBOR-CHECK as declared (shared basis code; not engine
    math), files touched exactly evaluator.py/controller.py/section.py +
    two new Test Files scripts + VS_NOTES; neighbors named and checked
    (gate tiers, refresh stamp, corner, anchor hold, non-unit/low-util
    shapes; 40-draft PRE/POST sweep: only 3 fence flips, all the
    fence-pass+judged-fail class; 6 gate_and_turn legs green); floor
    GOLDEN; canary SKIPPED as declared. Backend restarted, ONE :5050
    listener. Not green: turn D (mini audit) remains.
    ASSUMPTION stated for Nick (not a ruling gate): the wall admits the
    engine's own 1%/q price drift (PRICE_PATH_Q11=1.1046) so it bounds
    units, not the price the engine already authors; a stricter
    stated-price wall is a one-constant change if he rules otherwise.
    FLAGS (not built, triage law): (i) lever closes-projections carry
    the pre-move wall (narration precision, never a false pass);
    (ii) bounds-author payload q11 still at raw fence (GPT input);
    (iii) FAIL narration does not yet NAME capacity as the cause =
    feature decision.
TASK:
  TURN-TIMEOUT-MINUTES: 120
  TURN D (mini): the OWED turn-5 audit, SPOT-CHECK EACH FIX - does each
    landed fix (D1-D5+X2, a4dc230) show correctly in its artifact, was
    each tier call honest. NOT a full re-audit of the system. Where a
    turn-5 fix changed shared high-fan-out code (the forward mover did),
    neighbor-check THAT fix's named neighbors - not the universe. Also
    spot-check A3 at the tier VS declared (NEIGHBOR-CHECK - verify the
    call): re-run Test Files/_redproof_a3_capacity_fence.py on HEAD
    (expect ALL GREEN) and read _PREFIX.txt (T1a/T1b/T2a must be
    behavioural reds, T3 import traceback is structural); confirm the
    diff is confined to evaluator.basis_from_intake + the ceiling helper
    move + result/stamp plumbing; confirm the 40-draft sweep claim (only
    3 fence flips, each with eval_judged_shortfall already stored);
    re-run --only R31,R32. Original context: the original mini session
    died mid-audit, so turn 5's five fixes (D1-D5+X2, a4dc230) were
    never independently verified. Artifact-audit them now, plus A3.
    On a genuinely clean table: VERDICT green - the watcher stops and
    pings Nick. Feature decisions (incl. VS's three A3 flags and the
    price-path assumption) remain his to rule on after.
  Standing laws apply every turn: TURN PLAN first (emit, then proceed),
  context scoped to the task, SPOT-CHECK the fix by default (neighbor-
  check only for shared high-fan-out code; full apparatus only for
  engine-math/golden changes), single-line floor every turn,
  declared-vs-actual confirmed in every RESULT.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: reopen-surface:receipt-label-and-saydo-contradict-stored-capacity
  EVIDENCE: _prove_20260815_turnD_mini_a3.txt (R31,R32 GOLDEN digests
    72dfcb81/24e38de4/1d50e46a/cbd76463 unchanged + R19,R21,U02,U05,R25,R30
    green, 0 DRIFT); _prove_20260815_turnD_mini_mover.txt (mover neighbors
    R07,U04,R30,R44,R45,R46,I01-I06: 11 PROVEN + R07 struct-absence as
    before, 0 DRIFT); Test Files/_redproof_a3_capacity_fence.py re-run on
    HEAD ALL GREEN; _redproof_cw033_turn5_fixes.py 25/25 + _ablate.py 6/6
    re-run on HEAD; independent PRE(2d57218 worktree)/POST(HEAD) 40-draft
    sweep via Test Files/_neighbor_sweep_a3_capacity_wall.py; the finding's
    artifact = _live_cw033_turn5_20260814.txt W3 t2 FULL REPLY.
  SUMMARY: A3 (#101) CONFIRMED at NEIGHBOR-CHECK, tier call HONEST (the
    cap lands in evaluator.basis_from_intake, shared by fence/judged/corner/
    walk; NOT engine/money math). Diff confined to evaluator.py
    (basis_from_intake + ops_implied_and_ceiling/capacity_growth_ceiling +
    PRICE_PATH_Q11), controller.evaluate_current result["growth"],
    section.py stamp plumbing + _ops_implied_and_ceiling delegation - all
    four bases route through basis_from_intake (section 478/795/2530/2536,
    controller 1148); flat tier passes 1.0 and wall>=1.0 so untouched.
    PREFIX reds T1a/T1b/T2a behavioural (fence PASS $96,390 > $77,544
    wall), T3 structural import; POSTFIX/HEAD ALL GREEN. Sweep claim
    REPRODUCED independently: 40 drafts, 34 walls below fence, EXACTLY 3
    fence flips (b1f4fac7/2ecc759c/3de095cb, each with eval_judged_shortfall
    stored), 0 judged flips, 0 gap-only, anchor-hold/flat/corner identical
    on 40/40. VS declared-vs-actual MATCHES (watcher log 11:16 plan vs
    files touched/loaded/verify). TURN 5 (a4dc230) ARTIFACT-AUDITED: diff
    hunks confined to the declared sites (ack builder D4+R44-latent, xsec
    door+reconcile X2, cadence regex/reconciler D2, mover D1/D5, disclosure
    D1/D3, turn-inner wiring, reopen handler D3-third-layer/D5); redproof
    25/25 green on HEAD, PREFIX behavioural reds on D3/D4/X2 with D1/D2/D5
    pre-fix reds structural (new kwargs) but each ablation red on its own
    fix's checks (AB5 is a section-granularity crash-red, documented by VS;
    D5's behavioural evidence is live W5); live W1-W5 artifact shows each
    fix (rent 2400 kept, install 9/9, C3 t2 period 173.3333, rent named,
    ask alone). Mover neighbors green. Tier honesty for turn 5: declared +
    ran full apparatus under the then-law; the mixed bundle is already the
    named exemplar of the split law - not re-flagged.
    ONE NEW FINDING (triaged DEAL BREAKER, receipt clause, spot-check
    radius): the reopen-surface W3 t2 reply contradicts itself AFTER a
    correct leading receipt: "Recorded: capacity 40 a week (about 173.3 per
    operating period ...). Updated: Property contract: monthly capacity ->
    40; Property contract: monthly capacity -> 173. ... (I didn't end up
    using 40 and 40 - if that should change the model, tell me where.)"
    (a) capture_receipt.py:253-258 applies the cadence label to BOTH twin
    leaves, so the units_per_week_capacity cell (40) is spoken as "monthly
    capacity -> 40" - a false statement of what was stored; (b) the xsec
    door's say-do tail (intake_consult.py ~8006) lists the client's stated
    40 as unused after the cadence conversion consumed it - a false claim.
    Stored numbers are RIGHT (period 173.3333 / wk 40); the plan is right;
    the receipt lies twice on the guided reopen path (the C3 sequence).
    VS's live check asserted the presence of the right sentence, not the
    absence of a wrong one (leg-craft note). Handed to VS as TURN E below.
    DECLARED-vs-ACTUAL (mine): MATCHES - neighbor-check as declared; loaded
    exactly the listed artifacts/diffs/sections; canary skipped; legs run =
    R31,R32 floor + 6 A3 gate legs + 12 mover-neighbor legs; redproofs
    re-run; sweep reproduced with a throwaway pre-fix worktree (removed).
    Not green: TURN E open. Feature decisions (VS's three A3 flags, the
    price-path assumption, C1-C10) remain Nick's; 20 WONT-FIX stand.
TASK:
  TURN-TIMEOUT-MINUTES: 90
  TURN E (VS, SPOT-CHECK - two receipt fixes, both copy/branch-only, no
    shared high-fan-out code; grouped per the split law):
    E1 capture_receipt.py cadence-aware label: units_per_week_capacity
      must ALWAYS render "weekly capacity" (the cadence label belongs to
      units_per_period_capacity only). DEAL BREAKER: the receipt tells the
      client their MONTHLY capacity is 40 when it is 173 (false statement
      of a stored number, guided reopen path). REPRO FIRST on HEAD with
      the W3 t2 shape (Sumac clone, t1 "40 a month, not 34", t2 "Sorry -
      mowing capacity is 40 a week." on the completed/reopen surface; the
      backend must be restarted on HEAD, ONE :5050 listener; do NOT touch
      a live Cowork draft) - if the tail is already gone on HEAD, close
      E1+E2 in your RESULT with the artifact and skip the fix.
    E2 xsec-door say-do tail (intake_consult.py ~7985-8006, covered_vals):
      when _reconcile_stated_capacity_cadence CONVERTED the stated figure,
      the stated (pre-conversion) figure counts as covered - "(I didn't end
      up using 40 and 40 ...)" must not ship after "Recorded: capacity 40 a
      week". DEAL BREAKER: a false claim of non-use of the very number that
      landed. Broken-case-only branch (fires only on a conversion).
    VERIFY: repro red->green on the W3 t2 shape (offline redproof on the
    receipt builder + the say-do builder, plus ONE live reopen turn on a
    clone as the artifact: the full reply text must carry NO "monthly
    capacity -> 40" and NO "didn't end up using 40"; assert absence, not
    just presence); single-line floor --only R31,R32; canary SKIP; do not
    touch legs.py. Declare tier + declared-vs-actual per the laws.
    Flip to mini with a TASK: TURN F (mini) spot-check E1/E2 (diff matches,
    artifact shows the clean reply, tier honest, floor held); on a clean
    table VERDICT green.
  Standing laws apply every turn: TURN PLAN first (emit, then proceed),
  context scoped to the task, SPOT-CHECK the fix by default (neighbor-
  check only for shared high-fan-out code; full apparatus only for
  engine-math/golden changes), single-line floor every turn,
  declared-vs-actual confirmed in every RESULT.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none-open:turnE-awaiting-mini-spot-check
  EVIDENCE: f6ea787 (fix + artifacts). _live_turnE_PRE_20260815.txt (HEAD
    7473095, backend restarted on HEAD, Sumac clone, W3 t1+t2: RED 3/3 -
    reply carried 'monthly capacity -> 40' and '(I didn't end up using 40
    and 40 ...)'); _live_turnE_POST_20260815.txt (fixed tree, backend
    restarted, ONE :5050 listener pid 33804: GREEN - reply 'Recorded:
    capacity 40 a week (about 173.3 per operating period ...). Updated:
    weekly capacity -> 40; monthly capacity -> 173. Your Property contract
    side now models at about $886,912 a year.' - NO monthly->40, NO non-use
    tail, stored wk 40 / period 173.3333 unchanged); offline
    _redproof_turnE_PRE_20260815.txt (PREFIX via stash of the two files: E1
    behavioural red - receipt 'monthly capacity -> 40; monthly capacity ->
    173'; E2 structural red on the new kwarg + the undeclared call SHOWS the
    pre-fix tail) / _redproof_turnE_POST_20260815.txt GREEN 8/8;
    _prove_20260815_turnE_floor.txt R31+R32 GOLDEN (72dfcb81/24e38de4/
    1d50e46a/cbd76463 unchanged, 0 DRIFT). Harness: Test Files/
    _live_turnE_w3_reopen.py (asserts ABSENCE), Test Files/
    _redproof_turnE_receipt_saydo.py.
  SUMMARY: TURN E done at SPOT-CHECK, both fixes copy/branch-only. E1:
    capture_receipt._fmt applies the cadence label to units_per_period_
    capacity ONLY; units_per_week_capacity keeps its static 'weekly
    capacity' label (its CW-031-item-8 'capacity' fallback stays on the
    period cell). E2: _reconcile_driver_correction gains converted_stated
    (List[float]); the (d) figure-coverage backstop adds those to
    covered_vals - fires only when a caller passed a conversion. Two callers
    pass it: the xsec door (_xsec_cap_stated = the pre-conversion new_value,
    only when _xsec_cap_converted) and the main capacity reconciler
    (_cap_cad_stated = _stated_v_c, only when _cadr_c converted). The guard
    caller (_guard_underivable_ops_lever_writes) is untouched - it has no
    say-do tail. Not touched: legs.py, engine, workbook, mover routing.
    DECLARED-vs-ACTUAL: MATCHES - tier spot-check as declared; loaded
    exactly HANDOFF TASK, VS_NOTES laws mirror (already present, no edit),
    capture_receipt.py 200-300, intake_consult.py 7060-7150 / 7683-8010 /
    9801-9860 / 10096-10135 / 17688-17845 / 18470-18510, the W3 t2 artifact,
    the turn-5 live harness (reused by import); canary SKIPPED; legs run =
    R31,R32 only; backend restarted twice (pre-repro on HEAD, post-fix),
    one listener each time; no live Cowork draft touched (2d874abf was
    idle since 11:30, clones only, all clones deleted). One divergence,
    harness-side only: first PRE run crashed on cp1252 encoding of the
    arrow in MY harness print (fixed with stdout.reconfigure, stray clone
    deleted, rerun) - app untouched by that. Note for mini: post-fix the
    two receipt phrases differ so the CW-031 collision de-dup no longer
    prefixes 'Property contract:' - the product name appears once in the
    stream note; not a regression, the receipt names the row when phrases
    collide only. Watch-list (not built, Nick's triage): the say-do tail
    said '40 and 40' - _message_figures yields the stated 40 twice from a
    one-figure message; harmless now that the figure is covered.
TASK:
  TURN-TIMEOUT-MINUTES: 45
  TURN F (mini, SPOT-CHECK audit of turn E, f6ea787): (1) diff confined to
    capture_receipt._fmt (cadence branch narrowed to the period leaf) +
    intake_consult (converted_stated kwarg + covered_vals extension + the
    two caller pass-throughs + two locals) - nothing else; (2) the artifact
    _live_turnE_POST_20260815.txt shows the clean reply (assert ABSENCE of
    'monthly capacity -> 40' and 'didn't end up using 40', presence of
    'weekly capacity -> 40' and 'monthly capacity -> 173'), stored row wk
    40 / period 173.3333; (3) tier honest - spot-check: is _fmt or the (d)
    backstop shared high-fan-out code whose neighbors changed? (my call:
    no - _fmt's change is a leaf-name narrowing; the backstop's extension
    is inert unless converted_stated is passed); (4) floor held (re-run
    --only R31,R32 if you want your own digest read); (5) redproof PRE red
    for the RIGHT reason (E1 behavioural; E2 structural on the kwarg PLUS
    the undeclared call showing the tail = the pre-fix behaviour on
    record). On a clean table VERDICT green -> awaiting-Nick. Do not touch
    app code; the harness scripts are VS's.
  Standing laws apply: TURN PLAN first, context scoped to the task,
  spot-check the fix, single-line floor every turn, declared-vs-actual in
  the RESULT.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
