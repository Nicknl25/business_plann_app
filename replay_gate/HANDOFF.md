STATUS: awaiting-mini
TURN: 1/16
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
