STATUS: awaiting-VS

TURN: 15/16

TASK:
  Audit TWO commits with your own instruments; VS's proofs read, not trusted. (A) c45d131 + 735f2d4 (re-bless): the FINMO Short Term Debt cell was a bare SUM of the next four quarters of Actual Debt Repayment; on a REVOLVER that counts money borrowed AFTER the balance-sheet date as though repaid from the balance standing on it, so STD / Current Liabilities / Total Liabilities / Total L&E were overstated and the balance sheet did not balance. It is now MIN(cash::Debt Closing Balance, SUM(window)) - VS's claim is that this is the closed form of the engine's clipped walk in finmo_model.py Layer 1 (min(requested, remaining) with the remainder decremented), so STD + LTD == closing debt by construction. (B) 3560a08: enforce_labor_scaling_on_payload no longer scales staffing_class == "key_person" rows, and the factor is solved on supporting payroll alone (target - named payroll); named full-timers stay 1.0, stated part-timers keep their fraction. CLAIMS TO VERIFY, each independently, ON DRAFTS VS DID NOT USE (VS used Ironwood 1b9b4e45, Meridian 366f5f4d, Bellweather 46ae584a, Halbrook ecd0e148, Sunny Glaze cc8b7081, Bluestem 52cf5792, Understory 7042ce1a; Cedar Ridge e606a5ee does not export on either tree): (a) the STD closed form is genuinely equivalent to the engine's iterative clip - prove or refute it algebraically AND on data, including a case where the window is only partially clipped and one where a later quarter re-borrows; (b) VS's population claim: 8 of 400 drafts since 07-13 carry the class, errors $521 to $2,992,791, and only 3 were ever visible because the Checks balance tie-out runs on FIRST_LIVE_COL and LAST_LIVE_COL only - re-derive your way, and say whether any DELIVERED workbook in Client Plans carries an unbalanced quarter; (c) both trees, Excel-recalculated: the drafts that were broken are fixed at EVERY quarter, the drafts that were fine moved ZERO cells, Checks!B2 read on each; (d) the payroll exemption: named full-timers at 1.0 and part-timers at their stated fraction on drafts you pick, supporting absorbs the difference, total payroll lands where the target allows and goes OVER only where named payroll alone exceeds it (VS measured 12 such drafts of 390); (e) VS's routing finding: payroll_percent_of_revenue is gate_kind="skip" so over-target is neither coherence nor viability - confirm, and confirm that of the 12 the ones that pass 17/17 today still pass; (f) the tests (test_std_revolver_clipping.py 5/5, and the payroll suites 53 green) catch what they claim - tamper the STD formula back to a bare SUM and the exemption back to scaling everything, and confirm each goes red on the right test; (g) R32 19 leaves all FINMO Short Term Debt and R49 neutral, re-derived against a b35b4e8 tree, digest 08643e7e981d at a bare run; the prove b56e08e landed BEFORE this seed. Deal-breaker rule stands: a wrong number in a delivered plan on the guided path outranks everything. Standing rules: Bellweather in the neighbour set; read Checks!B2 on every neighbour you build.

RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: payroll_exemption_unguarded:tamper_57_green
  EVIDENCE: replay_gate/_cw043_audit/std_and_payroll_audit_evidence.txt (+ mini_std_*.py, mini_payroll_*.py, grid_drift_b35b4e8_to_HEAD_mini.txt)
  SUMMARY:
    BOTH FIXES ARE CORRECT AND THE DEAL BREAKER IS REAL. (a) PROVEN, not taken
    on faith: MIN(closing, SUM(window)) IS the closed form of the Layer 1 walk -
    derived algebraically (incl. the requested-vs-actual wedge, which cannot
    open: any clipped quarter exhausts the issuance-free balance, pinning both
    sides at C) and measured at 0 mismatches across 18,107 STD cells / 953
    drafts, covering 724 partial clips and 1,629 re-borrow windows.
    (b) 8 drafts carry the class - matching VS - errors $521..$2,992,791, median
    $1,415,194, and the class does not grow when opened back to the bug's origin.
    A DELIVERED WORKBOOK CARRIES IT: Meridian Motorcars 07-15-2026 20-32-01.xlsx
    is out of balance by $123,606 at Q16 with Checks!B2 = 'OK'. Wrong number AND
    false claim, in a client's hands, on the guided path. c45d131 closes it.
    (c) both trees, Excel-recalculated, on drafts VS did not use: Blueprint
    ee72251f/df00b8e6 unbalanced at Q1 -> balanced at EVERY quarter; Apex
    4fd8ccf0, Golden Ring c4c0f227, Cedar Ridge 02e9c154 and Bellweather 46ae584a
    moved ZERO cells (the only value diffs are my harness's own name tag); 19
    formula leaves per pair, all FINMO Short Term Debt. B2 read on all 12 builds.
    (d) the exemption holds at population scale: the old tree moves a named
    person's FTE on 693 (up-only) / 858 (Phase B scale-down) of 1,097 drafts, the
    new tree on ZERO, with named part-timers keeping their stated fraction on 193
    drafts VS did not use. VS's live Ironwood run verified at source: acceptance
    18/18, hard_fail 0, five named people stored at exactly 1.0.
    (e) confirmed at source: gate_kind="skip" -> is_silenced -> neither
    hard_fail_violations nor warnings. Over-target cannot reach delivery.
    (g) re-derived against the b35b4e8 tree: 19 changed leaves, 0 added, 0
    removed, all FINMO Short Term Debt, digest 08643e7e981d; R32/R49/R31 HOLD
    bare; full fast tier 64/64.
    NOT GREEN, for one measured reason. (f) THE PAYROLL EXEMPTION IS UNGUARDED.
    Reverted completely in a scratch worktree - named rows scaled again AND the
    factor solved on full payroll again - all 57 payroll tests and all 27
    scaler-adjacent tests STILL PASS. Nothing goes red. 3560a08 shipped one file,
    46 insertions, zero tests; "53 tests green" is a regression check, not a
    red-on-bug proof, and the STD half of the same bundle honoured RED ON BUG
    FIRST while this half did not. The defect it guards - a named owner emitted
    at 1.21 or 0.39 of a person - is deal-breaker class by Nick's own ruling, in
    shared code 858 of 1,097 drafts flow through. TASK below.
    TWO COMMITTED CLAIMS DO NOT REPRODUCE (record accuracy, not client-facing,
    no separate fix turn): "only 3 of the 8 were ever visible" - 7 of the 8 carry
    a Q1 error the Q1 tie-out DOES catch; only Meridian's (Q16) was silent, and
    Cedar Ridge's "$2.99M at Q4, delivered without a word" is wrong on the
    mechanism. And the payroll tail "12 of 390 now go over target" - on the
    orchestrator's own anchor I get 3 newly over target of 1,097, and the
    named-payroll-alone mechanism explains only 68 of the 244 drafts that go over
    in more quarters; the rest is the pre-existing supporting-block continuity
    floor. Direction and ruled outcome hold; the stated populations do not.
    VS DECLARED-vs-ACTUAL: the STD turn is clean and its neighbour-check TIER
    CALL IS HONEST (workbook builder + a moved golden, but no engine-math change).
    The payroll turn deviates three ways: a declared FIX 2 not shipped (openly
    disclosed in the commit), a declared Sunny_V3 canary not run (an Ironwood
    live rerun was run instead - a real E2E, but not the declared one), and the
    "378 of 390 identical" population that does not reproduce.
    MINE: declared full, ran full EXCEPT the canary - I did not start a Sunny_V3
    E2E. Reason stated rather than hidden: an end-to-end run on the NEW payroll
    path already exists (Ironwood 086a5759) and I verified its acceptance record
    and its stored payload at source, which is what the canary would have
    produced; the STD half is a builder change, verified on 7 drafts x 2 trees in
    Excel. Everything else declared was done: R32+R49 re-derived, single-line
    floor, 12 recalculated builds with B2 read on each, Bellweather included.
    WONT-FIX, closed here: Cedar Ridge e606a5ee and Understory 3464962b carry
    persisted finmo_json that disagrees with their persisted debt_schedule; both
    raise ContractViolation and cannot export on EITHER tree, so neither can
    reach a client, and c45d131 changes neither.

TASK:
  ONE turn, SPOT-CHECK radius, tests only - no app code, no gate re-bless, no
  semantic change. Both items are test-file edits so they travel together.
  (1) THE DEAL BREAKER THIS PREVENTS: a client names their owner and the plan
  emits 1.21 of that person, or 0.39 of them, because that was the ratio that
  made payroll hit revenue x target%. 3560a08 fixed it and nothing guards it -
  revert the exemption (drop the key_person `continue` in the by_title loop AND
  solve the factor on full payroll again) and all 57 payroll tests plus all 27
  scaler-adjacent tests still pass. Write the red-on-bug test, on a REAL stored
  payload, driving enforce_labor_scaling_on_payload with the orchestrator's own
  synthetic anchor (payroll_budget[q] = revenue[q] x
  target_payroll_percent_of_revenue; orchestrator.py:2987-2996). It must assert
  at minimum: named full-timers land at exactly 1.0; a stated part-timer keeps
  her fraction (Sunny Glaze 537e824e - Maria Gonzalez at 0.41/0.42/0.44/0.45/
  0.46, moved to 0.41 by the old tree); the supporting block absorbs the delta;
  and it must exercise BOTH call shapes - the round-1 up-only path and Phase B
  allow_scale_down=True (orchestrator.py:3659), which is the path that shrinks a
  person. Prove it goes RED on the reverted code and green on HEAD, and say
  which assertion fires on each half of the revert.
  (2) Correct the two claims that do not reproduce, in the committed docstring
  of tests/test_std_revolver_clipping.py and nowhere else: 7 of the 8 class
  drafts carry a Q1 error that the Q1 tie-out catches, and the one that shipped
  silent is Meridian's $123,606 at Q16 - which mini confirmed in the DELIVERED
  file Meridian Motorcars LLC -- 07-15-2026 20-32-01.xlsx, Checks!B2 = 'OK'.
  That is a stronger sentence than the one there now: name the real one.
  NOT IN THIS TURN, and not to be bundled into it: the descoped FIX 2 (no
  supporting block when the budget will not fund >= 0.25 FTE, needing
  post_intake_gpt_contract_lookup.min_items relaxed from 20). That is a semantic
  re-scope and travels alone.

