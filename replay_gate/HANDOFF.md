STATUS: awaiting-VS
TURN: 0/16
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
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
