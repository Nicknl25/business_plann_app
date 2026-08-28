STATUS: awaiting-mini

TURN: 16/16

TASK:
  Audit VS's turn 15 with your own instruments. Two test-file items, no app
  code, no gate code, no re-bless. (1) THE MISSING GUARD: 3560a08 shipped the
  key_person payroll exemption with zero tests - you proved a full revert left
  all 57 payroll and all 27 scaler-adjacent tests green. VS wrote
  tests/test_payroll_named_person_exemption.py against a new committed fixture
  tests/fixtures/payroll_named_person_payloads.json.gz holding two payloads
  captured verbatim from intake_consult_drafts: Sunny Glaze Donuts 537e824e
  (Jordan Lee stated 1.0 x 20; Maria Gonzalez stated 0.41/0.42/0.44/0.45/0.46;
  supporting already at its 0.1 FTE floor; named payroll alone exceeds target -
  the over-budget case) and Anderson and Blake Legal Associates 09d10c39 (two
  named full-timers at 1.0, paralegals 2.0 FTE -> 22.99 - the absorbing case).
  The anchor is rebuilt in-test by the orchestrator's own formula
  (orchestrator.py:2987-2996) and every assertion runs in BOTH call shapes,
  round-1 up-only and Phase B allow_scale_down=True (orchestrator.py:3659).
  CLAIMS TO VERIFY, each independently: (a) the revert VS red-proofed against
  is FAITHFUL - VS claims the both-halves revert reproduces 3560a08^'s
  enforce_labor_scaling_on_payload line for line (106 code lines, CODE
  IDENTICAL); check it, and check that reverting only half A and only half B
  are each the real half and not a strawman; (b) the red-proof: 11 passed / 22
  subtests on HEAD, and on the revert 18 failed (A), 2 failed (B), 16 failed
  (AB), with the CONTROL (same worktree, nothing reverted) green - rerun it
  your way; (c) the DISCRIMINATION claim, which is the point of the turn: the
  four identity assertions are the ONLY ones that fire on a half-A-only revert
  and the single supporting-lands-on-target-minus-named assertion is the ONLY
  one that fires on a half-B-only revert - confirm, and say whether either
  half can be reverted in a way that leaves the file green (VS notes the
  half-B assertion passes under a FULL revert and argues the sixteen half-A
  failures cover that case; test that argument); (d) whether the assertions are
  real or mirrors - the half-B guard compares supporting payroll at the first
  scaled quarter against (target - named) with a 1% tolerance justified as the
  2-dp FTE grid, and VS measured the full-payroll solve missing by 63%; check
  the tolerance cannot swallow a wrong factor, and check the first-scaled-
  quarter choice is not hiding a case; (e) the population VS re-derived: the
  pre-fix tree moves a named person on 501 of 1,097 drafts in EACH call shape,
  HEAD on zero, and - correcting 3560a08's own commit message - NO named
  full-timer is driven below 1.0 by today's code (0 of 1,097, the Q1 starting-
  FTE floor holds them), so the "0.39 of a person" is not reproducible and the
  live defect is inflation for a full-timer (worst: Sunny Glaze 4a47ec91,
  Jordan Lee at 11.22) and flattening for a part-timer. Re-derive; if the 0.39
  IS reachable on some path VS did not drive, that is a finding.
  (2) THE CORRECTED CLAIMS in tests/test_std_revolver_clipping.py - docstrings
  only, module docstring plus the one method docstring that repeated it, no
  code touched, 5/5 still green. VS re-derived your correction independently
  before committing it: 7 of the 8 class drafts carry a Q1 error the Q1 tie-out
  catches, only Meridian 366f5f4d is silent (Q16 alone, $123,606), and VS
  opened the delivered Meridian Motorcars LLC -- 07-15-2026 20-32-01.xlsx on a
  COPY, CalculateFullRebuild, and read Checks!B2 = OK with Q16 out by -123,606,
  STD 2,339,600 / LTD 0. Verify the sentence now committed is true and that
  nothing else in that file moved.
  VERIFY VS'S TIER CALL: VS declared and ran SPOT-CHECK on the grounds that
  test files are not on any production path. Say whether that is honest.
  NOT IN THIS TURN, and not to be bundled: the descoped FIX 2 (no supporting
  block when the budget will not fund >= 0.25 FTE, needing
  post_intake_gpt_contract_lookup.min_items relaxed from 20). Semantic
  re-scope, travels alone, still owed to Nick.

RESULT:
  AGENT: VS
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: replay_gate/_cw043_audit/vs_payroll_named_person_guard_evidence.txt
    (+ vs_t15_*.py reproduction scripts, vs_t15_redproof_raw.txt)
  SUMMARY:
    BOTH ITEMS DONE, TESTS ONLY, EXACTLY THE DECLARED SCOPE.
    (1) The exemption is now guarded. tests/test_payroll_named_person_exemption.py
    drives the real enforce_labor_scaling_on_payload on two real stored payloads
    with the orchestrator's own synthetic anchor, in BOTH call shapes: 11 tests
    / 22 subtests green on HEAD. The revert was proven faithful before it was
    used as a red-proof - both halves reverted reproduces 3560a08^'s function
    line for line, 106 code lines, CODE IDENTICAL. It goes red on every
    variant: 18 failed on half A alone, 2 on half B alone, 16 on the full
    revert, with the un-reverted control in the same worktree green.
    WHICH ASSERTION FIRES ON WHICH HALF, the answer asked for: half A (the
    key_person continue) is caught by four identity assertions - a named
    full-timer off exactly 1.0, Maria Gonzalez off her own stated fraction, a
    named row rewritten at all, and the delta escaping the supporting block;
    they fire on both drafts and both call shapes and nothing else fires on a
    half-A-only revert. Half B (the factor solved on supporting alone) is
    caught by exactly one assertion and it is the only thing that fires on a
    half-B-only revert: at the first scaled quarter supporting must land on
    (target - named), 451,132 on Anderson and Blake; the full-payroll solve
    lands it at 166,842, a 63% miss that no tolerance can swallow.
    (2) The two non-reproducing claims are corrected in the STD docstring and
    nowhere else; the file still passes 5/5. I did not take the correction on
    faith - I re-derived the quarter sets for all 8 class drafts myself (7 of 8
    carry a Q1 error, Meridian alone silent at Q16) and opened the delivered
    Meridian workbook on a copy: Checks!B2 = OK, Q16 out by -123,606, STD
    2,339,600 against LTD 0. The docstring now names that file.
    ONE CORRECTION TO THE RECORD, measured not assumed: 3560a08's commit
    message says a named owner came out at "0.39 of one". Driving the pre-fix
    tree over all 1,097 stored payrolls in both call shapes, NO named
    full-timer is driven below 1.0 - 0 of 1,097 - because the Q1 starting-FTE
    floor holds them. The live defect is inflation (worst 11.22 of one person)
    and, for a part-timer, flattening to her Q1 fraction. The test docstring
    states this rather than repeating the commit message. The deal breaker is
    unchanged and still real: a client names their owner and the plan emits
    1.21 - or 11.22 - of that person.
    DECLARED-vs-ACTUAL: no divergence. Declared spot-check, ran spot-check -
    test files only, nothing in python/ or client_statements_output_excel/
    reads them, so no live behaviour flows through the change; forward-
    reasoning says the one thing downstream is test collection, so I ran the
    two whole suites that collect alongside it: 98 passed on -k payroll and 55
    on the scaler-adjacent selection. Declared canary SKIP, skipped it - there
    is no app-code change to canary. Declared the single-line floor, ran it:
    R31/R32/R49 3/3 clear, GREEN, workbook_formulas=08643e7e981d.
    Declared LOADING held: the scaler, the two orchestrator call sites, the STD
    test, one payroll test for idiom, the two payloads. I did not load the
    engine, the builder or the gate.
