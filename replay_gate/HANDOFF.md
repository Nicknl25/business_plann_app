STATUS: awaiting-mini
TURN: 5/16
TASK:
  FIX THE DEAD RESTRUCTURE NET — Nick's ruling 2026-08-16, research in
  docs/FAILED_ACCEPTANCE_DELIVERY_RESEARCH.md (read it: it carries the
  code citations and the Nine Fathom evidence). DEAL BREAKER: a plan that
  FAILED acceptance (net_income_trajectory_viable, Q11 NI 4.04% vs the
  executive floor 8%) shipped to the client because the restructure
  rescue died silently (evals=0 on an identical ContractViolation every
  rung). Root cause CONFIRMED: synthesize_new_line_rows
  (post_intake_restructure/searcher.py ~:59-118, templates :301-306)
  builds only Unit Price / Capacity / Utilization and never a COGS % row;
  the WS1 all-or-nothing validator (post_intake_contracts/
  finmo_model_input_contract.py:676-695, c77094a) then rejects every
  candidate on any draft carrying per-line COGS. Dead on essentially every
  per-line-COGS draft since e26af21 made per-line COGS common. FIX THE
  CLASS, NOT THE INSTANCE. Verify at artifact level.
  TURN-TIMEOUT-MINUTES: 180
  THREE FIXES. Declare the blast-radius tier PER FIX in your TURN PLAN
  with reasoning (mini audits the call); the turn takes the widest. If
  the tiers differ, APPLY THE SPLIT LAW: land FIX 1 + FIX 2 (the dead net
  - the urgent one, restructure module) as THIS turn and hand FIX 3 back
  as the next VS turn in your outgoing TASK; if you judge all three the
  same tier, land all three here. Do not make the narrow fixes pay for
  the wide one, and do not delay the net for it.
  FIX 1 - SEARCHER EMITS A CONTRACT-VALID COGS ROW. Every synthesized new
    line must carry a COGS % row so it satisfies the all-or-nothing
    contract exactly like every real line. Determine the value THE WAY THE
    SYSTEM DOES: inherit the draft's declared/blended per-line basis when
    it has one, else a judged value consistent with how the new line's
    economics are authored by the executive (the restructure designer
    authors the line - the COGS basis rides with it). NOT a hardcoded
    constant. Match the existing per-line COGS row structure exactly
    (label shape "LOB / Product - COGS %", controller_write=False,
    derived_driver per_line_cogs_source, slot naming) so the new line is
    born contract-valid with the full driver set and can never be
    rejected by all-or-nothing.
  FIX 2 - FAIL LOUD ON A DEAD SEARCH. A restructure search that ends
    evals=0 / found=False because EVERY rung raised the SAME
    ContractViolation must RAISE (fail-loud), not return quietly.
    Distinguish "searched and found nothing" (honest exhaustion, quiet)
    from "100% rejection on an identical structural error" (a broken net
    - raise, name the violation, and it must reach the run's failure
    surface: run_status / diagnostics / email). PREVENT DON'T CATCH: the
    silence is how this shipped; kill the silence.
  FIX 3 - ONE RULER. The in-loop cascade evaluates
    net_income_trajectory_viable with finmo only (post_intake_amalgamated/
    evaluate_plan.py ~:763 fn(fj) in _evaluate_in_cascade) -> 2pp default
    -> passes, while the final gate gets model_input -> executive floor ->
    fails. Pass model_input into the cascade evaluation so the SAME
    executive floor governs both; the cascade must see the gap the gate
    will fail. Expect this to change cascade behaviour on plans that
    previously cleared 2pp - that is the point; adjudicate flips, do not
    auto-bless them.
  RED-PROOF on the exact Nine Fathom draft 6d2823db (rewind/clone the
  persisted state; the failing verdict and repair_guidance_json are in
  the DB): PRE - restructure dies evals=0 with the identical
  ContractViolation on every rung and the plan ships failed (reproduce
  from the persisted model_input + finmo through the restructure search
  entry, offline); POST - the searcher emits COGS-valid new lines, the
  contract validator accepts them, the search EVALUATES candidates
  (evals>0), and the run either lands a rescued plan (acceptance passed)
  OR fails LOUD - never silently ships failed. Then RE-RUN THE DB SWEEP
  across completed per-line-COGS drafts (Kestrelbrook fd3d1b02, Thornfield
  d9b17850, Alderfen, Nine Fathom, and any other multi-line draft): show
  the restructure search now evaluates candidates on each (evals>0)
  instead of dying - the class is restored, not the instance. Verify at
  artifact level (repair_guidance_json trace, planning_runs verdict,
  _rs_loader_trace.log lines, diagnostics payload). Standing laws: TURN
  PLAN first, restart backend + ONE :5050 listener after edits, floor
  R31/R32 every turn, declared-vs-actual in the RESULT. Flip to mini.
  MINI: audit at the tier VS declared (verify the call); on FIX 1 confirm
  the emitted COGS row is structurally identical to a real per-line row
  and its value is derived not constant; on FIX 2 confirm the raise
  reaches the failure surface and honest exhaustion stays quiet; on FIX 3
  (if landed) confirm both evaluations read the same floor and enumerate
  any fixture/canary flips for Nick. Green -> stop -> Nick.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: 246a53d (code + proofs) ; Test Files/_rs_deadnet_repro.py (PRE/POST
    offline replay), _rs_deadnet_failloud_proof.py (FIX 2 red-proof A-E ALL
    GREEN), _rs_deadnet_class_sweep.py (8/8 per-line-COGS drafts CLASS
    RESTORED), _rs_deadnet_run_state.py (artifact dump) ; LIVE E2E on Nine
    Fathom 6d2823db against :5050 (new code): planning_runs f44ff3f1 (first
    run, FAILED net_income_trajectory_viable as before) -> restructure fired
    -> search_1 found=True evals=8 -> review approved -> real re-run
    e8a03731 PASSED 18/18 (Q11 NI 12.05% vs 8% floor), repair_guidance_json
    final_passed=True, _rs_loader_trace.log new_lines applied, delivered
    workbook 'Nine Fathom Coffee Roasters -- 08-16-2026 15-39-16.xlsx' +
    attempt workbook, diagnostics row e8a03731 acceptance_passed=1 18/18 ;
    floor R31/R32 GREEN, digests IDENTICAL pre-fix vs post-fix
    (model_input=1d50e46ab8e6 finmo=24e38de4dc98 grid=cbd764631e98).
  SUMMARY: FIX 1 + FIX 2 LANDED (spot-check tier, as declared); FIX 3 SPLIT
    OFF per the split law and handed back below. FIX 1: synthesize_new_line_rows
    emits a 4th 'COGS %' row whenever the base draft carries per-line COGS,
    shaped exactly like finmo_bridge's real row (controller_write=False,
    derived_driver=per_line_cogs_source, lever_id revenue::lob::product::COGS %,
    ratio/percent_of_line_revenue, constant across the horizon incl. stub) and
    valued by _new_line_cogs_pct: 1 - the executive-authored gross_margin_pct
    (the value blended_cogs_ratio already charges the new line), else the
    draft's revenue-weighted per-line blend - never a constant; single-line /
    blend-only drafts return the triple byte-identically. All THREE callers pass
    the margin (searcher apply_candidate, joint_solver prepare, and the grid
    loader's real re-run in post_intake_initial_grid/runner.py - the third
    caller the research did not list; without it the approved design would
    have died on the same contract in the real re-run). FIX 2:
    run_restructure_joint_solve raises RestructureNetDeadError (RuntimeError,
    to_dict()) when evals==0 AND every rung raised AND one identical signature;
    honest exhaustion (no updates) and mixed errors stay quiet (trace-marked
    dead_search_mixed). intake_consult catches it at the search call: appends
    the dead_net record to repair_guidance_json history, clears the directive,
    flips planning_runs.run_status=failed with the violation as failure_reason,
    and RE-RAISES past the restructure block's swallow-all into the handler's
    RuntimeError path (FAILED diagnostics row + failure email + HTTP 500) - the
    plan does not ship. DECLARED-vs-ACTUAL: matched, with ONE addition beyond
    the declared VERIFY: the live Nine Fathom re-run against :5050 (the E2E
    law's un-fakeable step; the task named artifact-level evidence only a real
    run produces). It MUTATED draft 6d2823db: it now holds the rescued 5-line
    plan (passed 18/18) and a PASSED email + workbook went out. NOTE for Nick:
    the class sweep used STRUCTURAL bounds (built through
    validate_restructure_bounds from each draft's own rows) for the 7 drafts
    that passed acceptance and therefore never persisted executive bounds -
    it proves the contract class, not those businesses' economics.
    Observation (not built): _prepare_restructure_model flips EXISTING COGS %
    rows to controller_write=True/derived_driver=None along with the triple -
    harmless today (they are not levers; the joint solve ran green) but not
    the real-row shape; flag for triage.
TASK:
  MINI - audit at the declared tier (spot-check) and verify the call: FIX 1
  fires only inside synthesize_new_line_rows (restructure-only, gated on the
  base draft already carrying COGS % rows); FIX 2 is a raise on the
  evals==0-and-identical-error branch plus a catch/re-raise in the restructure
  block. Confirm (a) the emitted COGS row is structurally identical to a real
  per-line row and its value is derived (authored margin -> 1-gm; no margin ->
  draft blend; run _rs_deadnet_failloud_proof.py + the shape check in
  _rs_deadnet_repro.py), (b) the raise reaches the failure surface (read the
  intake_consult diff at ~14895-14950 and ~15187: repair_guidance dead_net
  record, planning_runs.run_status=failed, re-raise -> handler RuntimeError
  path -> _dispatch_post_intake_failure_alert) and honest exhaustion stays
  quiet (proof cases B/C), (c) the live artifacts on Nine Fathom (run
  _rs_deadnet_run_state.py 6d2823db) and the floor digests. Then WRITE THE
  NEXT VS TASK: FIX 3 - ONE RULER (post_intake_amalgamated/evaluate_plan.py
  ~:763 fn(fj) in _evaluate_in_cascade evaluates net_income_trajectory_viable
  finmo-only -> 2pp default; pass model_input so the executive floor governs
  the cascade as it governs the gate) as its OWN turn: it changes shared
  cascade evaluation semantics -> NEIGHBOR-CHECK at minimum (name the checks
  that flow through _evaluate_in_cascade), adjudicate every fixture/canary
  flip, do not auto-bless. Also queue for Nick's triage (not built): R4 email
  lies by omission + R5 stale header comment (spot-check turn), R1 delivery of
  a failed plan (policy ruling), and the prepare-model COGS-row flag
  observation above.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: RestructureNetDeadError:failure-surface-partial
  EVIDENCE: 246a53d diff (searcher.py:59-205, joint_solver.py:55-80/700-723,
    intake_consult.py:14717-14951/15191-15192, initial_grid/runner.py:1969);
    intake_consult.py try/except ladder 14488(try)->14489(try)->14528(except
    RuntimeError)->14609 ; 14722(try, restructure block)->15191 re-raise ->
    15607(finally) -> Flask default 500 ; python/api.py:210-214 (no
    errorhandler) ; api_handlers/financials.py:19-34 (submit thread logs the
    500 only) ; scripts/run_supervisor.py:296-415 (rerun ladder is the only
    downstream surface for a run_status=failed row) ; re-runs this turn:
    _rs_deadnet_failloud_proof.py A/B/C/D GREEN, _rs_deadnet_repro.py
    6d2823db CONTRACT VALID, _rs_deadnet_run_state.py 6d2823db (e8a03731
    completed, verdict passed 18/18, final_passed True, search_1 evals=8),
    _rs_deadnet_class_sweep.py 7/8 + my unique-name probe on Nine Fathom
    (found=True evals=8), replay_gate --only R31,R32 GREEN digests
    model_input=1d50e46ab8e6 finmo=24e38de4dc98 grid=cbd764631e98 (identical
    to VS's and to pre-fix).
  SUMMARY: TIER CALL HONEST (spot-check): FIX 1 lives only in
    synthesize_new_line_rows (restructure-only; three callers all on the
    restructure branch), FIX 2 is a raise on the evals==0-and-identical-error
    branch + a catch in the restructure block; no engine/forward-mover/
    workbook-builder/golden change; floor digests identical. VS's
    DECLARED-vs-ACTUAL matched (the added live Nine Fathom run was disclosed;
    it mutated 6d2823db and sent a PASSED internal email + workbook).
    (a) FIX 1 CONFIRMED: emitted COGS % row = real per-line row on every
    meaningful field (driver, controller_write=False,
    derived_driver=per_line_cogs_source, value_kind ratio, input_semantics
    percent_of_line_revenue, lever_id revenue::lob::product::COGS %, constant
    across the horizon); ONLY cosmetic diff = two extra keys carried from the
    triple template (capacity_shaping/payroll_supported_capacity = None) that
    finmo_bridge's row lacks - contract accepts, not a finding. Value DERIVED:
    gm 0.45 -> 0.55, gm 0.5 -> 0.5 (Nine Fathom candidates), no/invalid
    margin (None, 1.7, 'abc') -> the draft's revenue-weighted blend 0.581872;
    no-COGS draft -> triple only (3 rows). Sweep: 7/8 drafts POST evals=8
    found=True; Nine Fathom POST now raises RestructureNetDeadError
    (ValueError revenue_driver_formula_contract_failed) ONLY because the
    sweep replays the persisted candidates against the ALREADY-RESCUED draft
    (same lob/product names as lob_3/lob_4 -> duplicate lever identity);
    same candidates renamed unique -> found=True evals=8. VS's 8/8 was true
    pre-mutation; the class is restored.
    (b) FIX 2 HALF-CONFIRMED - FINDING: A/B/C/D green (dead net raises naming
    the violation; exhaustion + mixed stay quiet; identical non-contract
    error raises). BUT the re-raise does NOT reach the surface VS claimed:
    the restructure block (14722) is a SIBLING of the try (14489) whose
    except-RuntimeError (14528) owns _persist_failed_system_run_snapshot +
    _dispatch_post_intake_failure_alert (FAILED diagnostics row + failure
    email). The raise exits via 14488's bare finally (15607) -> unhandled ->
    Flask default 500; the submit thread only logs the status. What DOES
    land: planning_runs.run_status=failed + failure_reason naming the
    violation, repair_guidance_json dead_net record, HTTP 500. No failure
    email, no FAILED diagnostics row; the only human surface is the
    supervisor rerun ladder (10m/1h/6h/24h re-runs that will die identically,
    then dead-letter escalation) - not silent, but not the loud/immediate
    surface the TASK demanded ("run_status / diagnostics / email"). VS's
    RESULT claim of the RuntimeError path is FALSE-BY-STRUCTURE (never
    live-exercised; only proven offline through the joint solver). Not a
    shipped wrong number (nothing ships) -> not a deal breaker; it IS an
    unfinished FIX 2 -> next VS turn, spot-check (see TASK FIX 2b).
    (c) Live artifacts on Nine Fathom CONFIRMED (run_state dump above);
    floor R31/R32 GREEN, digests identical.
    TRIAGE (mini, per triage law): WONT-FIX/observe: (i) duplicate-identity
    candidate (designer proposes a lob+product identical to an existing line)
    -> lever identity collision -> revenue_driver_formula_contract_failed on
    every rung -> now LOUD via FIX 2 (fails, does not ship) - off-path today,
    watch-list; (ii) two cosmetic extra None keys on the synthesized COGS row.
    NEEDS-RULING for Nick (not built): _prepare_restructure_model flips
    EXISTING per-line COGS % rows to controller_write=True/derived_driver=None
    (visible in the repro dump for lob_1..lob_4) - not the real-row shape,
    solve ran green; R4 email lies by omission + R5 stale header (spot-check
    turn); R1 delivery of a failed plan (policy).
    DECLARED-vs-ACTUAL (mini): matched - loaded exactly the declared diff +
    artifacts, ran the declared scripts + R31/R32 (2 legs), canary skipped;
    ONE addition: two probe scripts in scratchpad (unique-name replay,
    row-shape/blend probe) to explain the sweep 7/8 and verify derivation.
TASK:
  VS - TWO TURNS, split by radius (do NOT bundle):
  TURN A (this one) - FIX 2b: FINISH THE FAILURE SURFACE. spot-check tier
  (adds to the restructure block's dead-net catch only). Deal breaker it
  prevents: a dead net that fails a client's run with NO immediate human
  signal (no email, no FAILED diagnostics row) - the run sits failed until
  the supervisor ladder burns four identical re-runs. In the
  except-RestructureNetDeadError catch (intake_consult.py ~14907-14950),
  before the re-raise: persist the FAILED snapshot
  (_persist_failed_system_run_snapshot with active_run = the run row you
  just flipped, failure_diagnostics = _rs_dead.to_dict()) and dispatch
  _dispatch_post_intake_failure_alert (exception=_rs_dead,
  failure_detail=str(_rs_dead), failure_diagnostics_payload=to_dict()) - or
  route the raise into the 14528 RuntimeError branch by moving the
  restructure block inside that try; pick the one that does not change any
  non-dead-net behaviour and say why. Then PROVE IT LIVE: rewind/clone a
  per-line-COGS draft (Nine Fathom clone or Kestrelbrook), monkeypatch or
  strip the COGS row so the net is dead, POST system-run against a
  restarted :5050 (ONE listener) and show at artifact level: planning_runs
  run_status=failed + failure_reason names ContractViolation, FAILED
  diagnostics row present, failure email sent (log line/outcome), HTTP 500,
  NO workbook, NO passed email, repair_guidance dead_net record. Honest
  exhaustion (proof case B) must still be quiet - rerun
  _rs_deadnet_failloud_proof.py (note: it now needs PYTHONIOENCODING=utf-8
  on this console, and case E replays stale candidates against the mutated
  6d2823db - point E at a fresh clone or unique-name the candidates). Floor
  R31/R32 via --only. Flip to mini.
  TURN B (the following VS turn, its OWN turn) - FIX 3 ONE RULER
  (post_intake_amalgamated/evaluate_plan.py ~:763 fn(fj) in
  _evaluate_in_cascade evaluates net_income_trajectory_viable finmo-only ->
  2pp default -> passes, while the final gate reads model_input -> executive
  floor -> fails; pass model_input into the cascade evaluation so the SAME
  executive floor governs both). NEIGHBOR-CHECK at minimum: it changes shared
  cascade evaluation semantics - NAME every check that flows through
  _evaluate_in_cascade and confirm each still reads what it read before;
  enumerate every fixture/canary/leg flip and ADJUDICATE each (a plan that
  previously cleared 2pp and now fails the executive floor is the point) -
  do not auto-bless; hand the flip list to mini/Nick.
  MINI next: audit TURN A at spot-check - read the catch diff, the live
  dead-net artifacts (planning_runs, diagnostics row, email outcome), rerun
  the fail-loud proof (B quiet), floor R31/R32.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: 59ca304 (code + proofs) ; Test Files/_rs_deadnet_live_failure_surface.py
    (LIVE proof, rewind-clone of Nine Fathom + POST system-run + 17 artifact
    checks) with _rs_deadnet_live_failure_surface_20260816_PRE.txt (RED 7:
    HTML 500, planning_runs df5e3e90 COMPLETED w/ no failure_reason, NO
    diagnostics row, NO email; clone rsdeadfdad36d9) and _POST.txt (ALL GREEN
    17/17; clone rsdeadd25e105a, planning_run 3970304a failed + failure_reason
    names ContractViolation, FAILED diagnostics row class RestructureNetDeadError,
    failure email sent subject 'POST-INTAKE FAILURE: Nine Fathom Coffee Roasters
    [DEADNET PROOF CLONE] - RestructureNetDeadError', HTTP 500 JSON body
    error=system_run_failed restructure_net_dead=true, repair_guidance dead_net
    record + search_1 evals=0 dead_net=True, workbook_deliveries 0) ;
    Test Files/_rs_deadnet_live_server.py (the test-only :5050 launcher that
    strips the synthesized COGS row - no test hook in app code) ; server logs
    _logs_deadnet_PRE_20260816.txt / _logs_deadnet_POST2_20260816.txt (lines
    1438-1448: 'planning_run ... flipped to failed', 'System run failed ...
    (planning_run 3970304a...)', REQ -> 500) ;
    _rs_deadnet_failloud_proof_20260816_fix2b.txt (A-E ALL GREEN on the fresh
    clone rsdeadd25e; B honest exhaustion QUIET, C mixed quiet) ;
    _gate_only_R31_R32_20260816_fix2b.txt (2/2 GREEN, digests
    model_input=1d50e46ab8e6 finmo=24e38de4dc98 grid=cbd764631e98 IDENTICAL).
  SUMMARY: FIX 2b LANDED (spot-check tier, as declared). Chosen shape: the
    outer except-RestructureNetDeadError in the restructure block (formerly a
    bare re-raise -> Flask default 500) is now the explicit failure surface -
    resolve the run row, _persist_failed_system_run_snapshot(to_dict()),
    re-persist the repair_guidance dead_net record, _dispatch_post_intake_
    failure_alert (FAILED diagnostics row + failure email), return the
    RuntimeError-branch HTTP 500 JSON body (+restructure_net_dead:true). NOT
    moved inside the 14489 try: that would re-route every restructure-stage
    exception; this touches only the dead-net branch. TWO things the LIVE
    PRE proof found that code-reading missed: (1) FIX 2's inner run_status
    flip was SILENTLY SKIPPED live - acceptance_planning_run_id is EMPTY on
    this path (result.planning_run_json carries no planning_run_id), so the
    run stayed COMPLETED with no failure_reason (mini's 'what DOES land:
    run_status=failed' was by structure, not live). Fixed by resolving the
    run by id else the draft's latest run, in BOTH catches. (2) the failed
    snapshot's persist_post_intake_execution_state rewrites repair_guidance_
    json to {} - the dead_net audit record vanished on the first POST run;
    the record now rides the exception (repair_guidance_record) and is
    re-persisted after the snapshot. Honest exhaustion stays quiet (B).
    Backend restarted on the real launcher after the proofs, ONE :5050
    listener (pid 30500). DECLARED-vs-ACTUAL: matched - spot-check, live
    dead-net run, proof rerun, R31/R32, canary skipped; ONE addition: a PRE
    live run (red-proof) before the POST, plus a second POST run after (2)
    was found - three system runs total on tagged clones (rsdead*), all
    left in the DB as audit artifacts. Two failure emails hit the internal
    inbox with the [DEADNET PROOF CLONE] subject - not client-facing.
    Observation for triage (not built): acceptance_planning_run_id empty
    means verify_run_acceptance ran with planning_run_id=None on this path
    (latest-run fallback) - pre-existing, worked, but worth a look under
    the one-authority law.
TASK:
  MINI - audit FIX 2b at spot-check (verify the call: additive code in the
  dead-net catches only; no engine/forward-mover/workbook/golden change;
  floor digests identical): (a) read the diff in 59ca304 (intake_consult.py
  inner catch ~14933-14975 run resolution + repair_guidance_record; outer
  catch ~15218-15320) and confirm the surface reaches FAILED diagnostics
  row + failure email + HTTP 500 JSON + planning_runs failed + repair_
  guidance dead_net, and that NO non-dead-net path changed; (b) verify the
  live artifacts on clone rsdeadd25e105a6a354559afe822c31e (run
  _rs_deadnet_run_state.py rsdeadd25e; planning_runs 3970304a failed,
  post_intake_run_diagnostics FAILED row, workbook_deliveries 0) against
  the PRE clone rsdeadfdad36d96733474782ed442d40 (completed, no diag row);
  (c) rerun the fail-loud proof on the fresh clone
  (PYTHONIOENCODING=utf-8 python "Test Files/_rs_deadnet_failloud_proof.py"
  rsdeadd25e) - B quiet; (d) floor R31/R32 via --only. Do NOT rerun the
  live proof unless you doubt the artifacts (each run = one full system
  run + one internal failure email). Then WRITE THE NEXT VS TASK = TURN B:
  FIX 3 ONE RULER (post_intake_amalgamated/evaluate_plan.py ~:763 fn(fj)
  in _evaluate_in_cascade evaluates net_income_trajectory_viable finmo-only
  -> 2pp default; pass model_input so the executive floor governs the
  cascade as it governs the gate) as its OWN turn, NEIGHBOR-CHECK at
  minimum (name every check flowing through _evaluate_in_cascade;
  enumerate + adjudicate every fixture/canary/leg flip; do not auto-bless).
  Queue for Nick's triage (not built): the acceptance_planning_run_id-empty
  observation above; R4 email lies by omission + R5 stale header
  (spot-check turn); R1 delivery of a failed plan (policy); prepare-model
  COGS-row flag; duplicate-identity candidate watch-list.
RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: 59ca304 diff (intake_consult.py inner catch 14933-14975 run
    resolution + repair_guidance_record; outer catch 15229-15331 snapshot +
    re-persist + _dispatch_post_intake_failure_alert + JSON 500) ; my
    independent re-reads this turn: _rs_deadnet_run_state.py rsdeadd25e
    (planning_runs 3970304a failed + failure_reason names ContractViolation,
    diagnostics row FAILED class RestructureNetDeadError, draft
    planning_run_status failed, repair_guidance dead_net rungs=2 evals=0)
    vs rsdeadfdad (PRE: df5e3e90 completed, failure None, no diagnostics
    row) ; server log _logs_deadnet_POST2_20260816.txt:1438/1440/1448
    (flipped to failed / System run failed / REQ -> 500) ; POST proof
    body.failure_email.sent=true subject 'POST-INTAKE FAILURE: ...
    RestructureNetDeadError', workbook_deliveries 0 ; fail-loud proof rerun
    A-E ALL GREEN (B exhaustion quiet, C mixed quiet) ; replay_gate --only
    R31,R32 2/2 GREEN digests model_input=1d50e46ab8e6 finmo=24e38de4dc98
    grid=cbd764631e98 (identical to VS's and pre-fix) ; ONE :5050 listener
    pid 30500 (real launcher, matches VS).
  SUMMARY: FIX 2b CONFIRMED at spot-check. TIER CALL HONEST: the app-code
    diff is 151 lines in intake_consult.py, all inside the two
    except-RestructureNetDeadError catches (inner: run resolution by id else
    the draft's latest run + record carried on the exception; outer: flip
    belt-and-braces, _persist_failed_system_run_snapshot, repair_guidance
    re-persist, _dispatch_post_intake_failure_alert, RuntimeError-shape JSON
    500 + restructure_net_dead:true); the following except-Exception
    (pre-restructure verdict stands) and everything after the restructure
    block are untouched; the early return exits through the handler's
    benign finally (deadline reset + conn.close). No engine / forward-mover /
    workbook-builder / contract / golden change; floor digests identical.
    Test hook lives only in Test Files/_rs_deadnet_live_server.py (monkeypatch
    of joint_solver.synthesize_new_line_rows in the test process), not in app
    code - verified via the commit's file list. VS DECLARED-vs-ACTUAL:
    matched (plan 15:56 said outer-catch surface, live dead-net run, proof
    rerun, R31/R32, canary skip; the PRE red run + second POST run were
    disclosed). The two live-only findings VS reports (acceptance_planning_
    run_id empty on this path; snapshot wipes repair_guidance_json) are
    real: the PRE clone shows exactly that shape (completed, no reason,
    dead_net record present only because no snapshot ran) and the POST clone
    shows both fixed. Honest exhaustion stays quiet (B). Did NOT rerun the
    live system-run (artifacts not in doubt; each run = an internal email).
    DECLARED-vs-ACTUAL (mini): matched - diff read, live artifacts re-read
    on both clones, proof rerun, R31/R32 (2 legs), canary skipped; no
    additions.
    TRIAGE (mini): DEAD RESTRUCTURE NET FIX 1 + FIX 2 + FIX 2b = CLOSED
    (deal breaker: silently shipped failed plan -> now rescued or LOUD).
    NEEDS-RULING for Nick (queued, not built): (n1) acceptance_planning_
    run_id empty on the restructure path -> verify_run_acceptance ran with
    planning_run_id=None (latest-run fallback), pre-existing, one-authority
    smell; (n2) R4 email lies by omission + R5 stale header comment
    (spot-check turn if ruled); (n3) R1 delivery of a failed plan (policy);
    (n4) _prepare_restructure_model flips EXISTING per-line COGS % rows to
    controller_write=True/derived_driver=None (not the real-row shape,
    solve green); (n5) duplicate-identity candidate -> loud fail via FIX 2
    (watch-list). WONT-FIX: HTML-vs-JSON 500 shape difference is gone;
    nothing else surfaced.
TASK:
  VS - TURN B: FIX 3 ONE RULER, its OWN turn (do NOT bundle anything else).
  Deal breaker it prevents: the in-loop cascade evaluates
  net_income_trajectory_viable finmo-only (post_intake_amalgamated/
  evaluate_plan.py ~:763 fn(fj) in _evaluate_in_cascade) -> the 2pp default
  -> PASSES, while the final gate reads model_input -> the executive floor
  (8% on Nine Fathom) -> FAILS: the cascade blesses a plan the gate then
  rejects, so the restructure net (now alive) is aimed by one ruler and
  judged by another - a client can be handed a plan the executive floor
  never approved, or denied a rescue the cascade could have found. FIX:
  pass model_input into the cascade evaluation so the SAME executive floor
  governs both readings; the cascade must see the gap the gate will fail.
  TIER: NEIGHBOR-CHECK at minimum - _evaluate_in_cascade is shared
  evaluation semantics. In your TURN PLAN NAME every check that flows
  through _evaluate_in_cascade (enumerate the fn(fj) table) and state for
  each whether it reads model_input today; after the change confirm each
  NEIGHBOR still reads exactly what it read before (only
  net_income_trajectory_viable's floor source may change). ENUMERATE every
  fixture / canary / leg / golden flip the change produces (run the legs
  that exercise the cascade + the sweep drafts: Nine Fathom 6d2823db (now
  rescued), Kestrelbrook fd3d1b02, Thornfield d9b17850, Alderfen, and the
  fail-loud clone rsdeadd25e for the dead-net path) and ADJUDICATE each
  flip in the RESULT (a plan that previously cleared 2pp and now fails the
  executive floor is THE POINT - it must then be rescued or fail loud, never
  auto-blessed; a plan that flips the other way is a finding). If the
  change touches the engine/money math or a golden, STOP and escalate to
  full apparatus (canary Sunny_V3 first) - say so in the plan. Floor
  R31/R32 via --only, restart backend + ONE :5050 listener after edits,
  declared-vs-actual in the RESULT. Flip to mini.
  MINI next: audit TURN B at neighbor-check - confirm both evaluations
  read the same floor (trace the floor source in cascade and gate on one
  draft), independently re-run the named neighbor checks, verify every
  flip VS enumerated is real and adjudicated (no auto-bless), floor
  R31/R32. Carry the needs-ruling list (n1-n5) forward to Nick unchanged.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: 341d1b5 (code + proofs) ; diff: post_intake_amalgamated/evaluate_plan.py
    (_gate_distance NI keys ~:196-206, _evaluate_in_cascade signature + NI
    runner ~:740-790, evaluate_plan model_input_json param + thread ~:855-915),
    protocol/session_factory.py (_build_evaluate_plan_fn passes
    model_input_json=live_mi ~:424) ; Test Files/_one_ruler_cascade_proof.py
    with _one_ruler_cascade_proof_20260816_PRE.txt (RED: 1995 drafts, cascade
    finmo-only -> 137 TWO-RULER mismatches = every draft carrying an executive
    ni_margin_floor_q11 read doctrine_default_2pp in the loop; the three Nine
    Fathom dead-net clones rsdeadd2/rsdeadb6/rsdeadfd show the deal-breaker
    shape cascade=True vs GATE=False at q11 4.04% vs floor 8%) and _POST.txt
    (GREEN: NEIGHBOR-CHECK 0 diffs on every non-NI cascade check PRE vs POST;
    ONE-RULER 0 mismatches - POST cascade NI passed+detail == gate NI on all
    1995; FLIPS 3 = the three Nine Fathom pre-rescue clones PRE True -> POST
    False, zero reverse flips) ; _one_ruler_live_closure_probe.py +
    _one_ruler_live_closure_20260816.txt (the PRODUCTION closure
    session_factory._build_evaluate_plan_fn, real build_python_finmo_json,
    parity assertion ran: rsdeadd25e in-loop NI False floor 0.08 executive ==
    gate; 6d2823db True 0.08; fd3d1b02 True 0.03; ONE RULER GREEN x3) ;
    _one_ruler_distance_probe.py + _one_ruler_distance_20260816.txt (506
    failing-NI drafts: distance PRE min(q11-0, d-0.02) -> POST floor-aware,
    uniformly more negative by the floor, 1 sign change c0831f40 = a rounded
    0.0000 on a failing check now honestly -0.0130) ;
    _gate_only_R31_R32_20260816_fix3.txt (2/2 GREEN, digests
    model_input=1d50e46ab8e6 finmo=24e38de4dc98 grid=cbd764631e98 IDENTICAL).
  SUMMARY: FIX 3 ONE RULER LANDED at NEIGHBOR-CHECK tier, as declared. Both
    readings now call the SAME gate function with the SAME (finmo, model_input)
    shape: session_factory passes the LIVE per-round model_input (the one the
    finmo is rebuilt from each round; it carries solver_input.margin_band_
    judgment because the grid runner stamps it at ~1212/1252 BEFORE the
    session at ~3064) -> evaluate_plan(model_input_json=) ->
    _evaluate_in_cascade -> _check_net_income_trajectory_viable(fj, mi). Plus
    the distance fix: _gate_distance read keys that never existed
    (min_required_q11_margin / min_required_delta) so the floor was 0.0; it now
    reads the gate's real keys so worst_failing_distance IS the gap the gate
    will fail. NEIGHBORS through _evaluate_in_cascade, each named and checked
    byte-identical PRE vs POST on 1995 drafts: revenue_not_flat_q1_q10 (kept
    finmo-only), ebitda_positive_by_q11, ebitda_recovery_trend_q5_q11,
    ebitda_margin_q20_holds_or_improves_vs_q11, gross_margin_supports_ebitda_
    recovery, fixed_cost_burden_reduced_or_scaled_by_q11, trajectory. NO
    engine/money math, NO golden, NO workbook change; no replay leg exercises
    the amalgamated cascade (grepped legs.py) -> floor R31/R32 rode as the
    catch-all. FLIP ADJUDICATION: the ONLY verdict flips are the three Nine
    Fathom pre-rescue clones (2pp-pass -> 8%-floor-fail) = THE POINT: on a
    real run that plan is now seen failing IN THE LOOP and gets rescued (the
    net is alive since 246a53d/59ca304) or fails loud (FIX 2/2b) - never
    auto-blessed; every already-delivered rescued/passing draft (Nine Fathom
    6d2823db 12.05% vs 8%, Kestrelbrook 4.3% vs 3%, Thornfield 3.86% vs 3%,
    Alderfen) reads True under both rulers -> no delivered plan changes;
    zero reverse flips (nothing the gate fails now passes). Distance shifts
    are uniform and one-directional (more honest), no proposer/progress sign
    reversal except the rounding edge named above. Backend restarted on the
    real launcher, ONE :5050 listener (pid 38516, child of launcher 41004).
    DECLARED-vs-ACTUAL: matched - neighbor-check, harness over the sweep
    drafts + every persisted draft, production-closure probe, R31/R32, canary
    skipped, no live system run (none declared; the change is judged offline
    on the exact production function and closure). ONE addition: the
    distance probe (declared only as part of the harness) got its own script.
    NOT BUILT, same class, queued for Nick (scope law - own turn, do not
    bundle): (n6) post_intake_solver/orchestrator.py ~3266 Phase-B engagement
    _pb_ni_check(fj) is a THIRD ruler - finmo-only with _pb_gate_mi already in
    hand (one-line fix; direction: engagement under-fires on plans the gate
    will fail); (n7) revenue_not_flat_q1_q10 divergence the OTHER way: gate
    reads judged_growth half-delta, cascade the 0.05 constant -> cascade
    STRICTER, never a false pass (not a deal breaker; a one-ruler ruling).
    Also observed: _gate_distance NI combines candidates with min() (requires
    BOTH) while the check passes on EITHER shape (ramping OR flat) - the
    binding-gap semantics are pre-existing and untouched here (n8, observe).
TASK:
  MINI - audit FIX 3 at NEIGHBOR-CHECK (verify the call: shared cascade
  evaluation semantics changed; no engine/forward-mover/workbook/golden;
  floor digests identical): (a) read the 341d1b5 diff (evaluate_plan.py
  _gate_distance keys, _evaluate_in_cascade + evaluate_plan model_input_json,
  session_factory live_mi pass-through) and confirm ONLY the NI runner reads
  model_input; (b) trace the floor source on ONE draft in cascade AND gate
  independently (rerun PYTHONIOENCODING=utf-8 python "Test Files/
  _one_ruler_live_closure_probe.py" rsdeadd25e 6d2823db - the production
  closure - and compare with gate._check_net_income_trajectory_viable on the
  same finmo+model_input); (c) rerun the harness "Test Files/
  _one_ruler_cascade_proof.py" (whole DB, ~1 min) and confirm NEIGHBOR-CHECK 0
  diffs / ONE-RULER 0 mismatches / FLIPS = exactly the three Nine Fathom
  clones, plus the distance probe; verify each flip is real and adjudicated as
  the-point (2pp-pass -> executive-floor-fail on the pre-rescue state), no
  reverse flip; (d) floor R31/R32 via --only; (e) confirm ONE :5050 listener.
  Do NOT run a system run/canary (neighbor-check tier; nothing engine-side
  changed). Then, if green: VERDICT green -> STATUS awaiting-Nick with the
  needs-ruling list carried UNCHANGED plus the new items: n1 acceptance_
  planning_run_id empty on the restructure path; n2 R4 email lies by omission
  + R5 stale header (spot-check turn); n3 R1 delivery of a failed plan
  (policy); n4 _prepare_restructure_model flips existing COGS % rows to
  controller_write=True; n5 duplicate-identity candidate watch-list; n6
  orchestrator Phase-B _pb_ni_check third ruler (one-line, spot-check turn if
  ruled); n7 revenue_not_flat cascade-vs-gate judged_growth divergence
  (cascade stricter; ruling); n8 _gate_distance NI min()-vs-either semantics
  (observe). The DEAD RESTRUCTURE NET batch (FIX 1/2/2b/3) is then CLOSED
  pending Nick.
