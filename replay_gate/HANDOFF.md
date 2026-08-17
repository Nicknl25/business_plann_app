STATUS: stopped-fault
TURN: 0/16
TASK:
  FIX A-122 — SUBMIT VALIDATOR IS THE LAST FLAT-FIRST READER. Nick's
  ruling 2026-08-17. Research w/ citations: docs/SUBMIT_VALIDATOR_BLOCKER_
  RESEARCH.md (read it first). DEAL BREAKER: every SINGLE-LINE business
  since 539fb17 (Aug 12, "flat driver cells RETIRED") is stranded at
  SUBMIT on a correct model - the validator (python/client_intake_and_
  finmo/intake_submit_service.py ~:317-364) checks FLAT top-level
  unit_name / unit_description / unit_price / units_per_week_capacity
  when is_multi_lob is False, but the ops canonical pass (_derive_ops_
  cells, intake_consult.py ~:16131-16160) deletes those flat keys whenever
  product rows exist; every other reader was converted row-first
  (_ops_driver_value ~:16041) - submit was missed. Multi-line drafts skip
  the flat checks (that's why Nine Fathom / Corvid submitted); single-line
  drafts fail 0/2 (Tanager 87f0fbba, Sumac clone mn33t5g9). This is
  COMPLETING the Aug-12 conversion for the one reader it missed - not a
  new direction. EMAIL / DELIVERY PATH OFF-LIMITS (fence).
  TURN-TIMEOUT-MINUTES: 120
  TURN 1 (VS): make the submit validator ROW-FIRST like the rest of the
  engine. Resolve unit_name, unit_description, unit_price,
  units_per_week_capacity (and any other flat-validated driver in that
  function) as the first non-None across lob_models[*].products[*] -
  mirror _ops_driver_value's row-first semantics - and FEED THE RESOLVED
  ROW VALUES into insert_intake_submission (the intake_submissions
  columns must carry the real values, e.g. 720 / 28 / "print job", not
  just pass the gate). Keep the FLAT FALLBACK ONLY for genuinely rowless
  legacy drafts (no lob_models rows -> validate the old flat way). Do NOT
  revert 539fb17. Do NOT flip is_multi_lob for single rows (that would
  skip validation instead of validating real values). Delete nothing that
  legacy still needs; delete any now-dead flat-only branch that nothing
  reaches (remove-don't-route-around).
   DECLARE THE TIER in your TURN PLAN (expect spot-check: one reader
   function + its insert; VS states why). VERIFY FORWARD (the new law's
   first application - one line in the plan): this change affects
   WHETHER PLANS SUBMIT AND BUILD, so the verification IS end-to-end
   submit + build, not "the validator returns true":
    (a) Tanager 87f0fbba and the Sumac clone mn33t5g9 (both known-
        stranded single-line drafts): SUBMIT through the real door (POST
        /api/financials on a restarted backend, ONE :5050 listener) ->
        reference code issued, mark_submitted runs, system run starts ->
        BUILD completes (planning run terminal, workbook produced) - the
        end-to-end path, not the function.
    (b) Multi-line control: a Nine-Fathom-shape draft (6d2823db or a
        rewound clone) STILL submits and builds - the working path is
        not broken.
    (c) Rowless-legacy control: a draft with NO lob_models rows (e.g.
        Fetch & Fluff 50658fff shape, or a synthetic rowless payload)
        still validates via the flat fallback and rejects a genuinely
        empty legacy payload with the SAME error text as before.
    (d) Negative: a single-row draft whose row genuinely lacks
        unit_price is still REJECTED with the right message (the fix
        validates real values, it does not skip validation).
    Red-proof PRE (Tanager 400 with the three messages) -> POST (200,
    submission id, run started). intake_submissions row for Tanager
    carries the resolved values. Floor R31/R32 via --only. Canary skip.
    Flip to mini.
  TURN 2 (mini, audit at the tier VS declared): diff confined to the
  submit service (+ its insert); row-first semantics mirror
  _ops_driver_value; flat fallback only when no rows; VERIFY-FORWARD
  audit duty - confirm the end-to-end submit + build actually RAN on
  Tanager AND the Sumac clone (planning runs terminal, workbooks
  produced), the multi-line and rowless controls ran, the negative case
  rejects; zero email/delivery lines touched; floor. Green -> stop ->
  Nick.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
