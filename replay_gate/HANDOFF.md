STATUS: awaiting-Nick
TURN: 2/16
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
  (re-armed after the Cowork-tester dirty-tree fault; tree clean now)
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: python/client_intake_and_finmo/intake_submit_service.py (diff:
    _ROW_FIRST_DRIVER_FIELDS + _row_first_driver + one 5-line block after
    the is_multi_lob decision; nothing else in the file moved);
    Test Files/_a122_PRE_tanager_20260817.txt (400, the 3 messages);
    Test Files/_a122_POST_tanager_20260817.txt (200, submission 80);
    Test Files/_a122_POST_sumac_20260817.txt (200, submission 81);
    Test Files/_a122_POST_ninefathom_clone_20260817.txt (200, submission 82);
    Test Files/_a122_submissions_rows_20260817.txt (rows 80/81 carry
    print job / 720 / 28 and Property contract / 550 / 8);
    Test Files/_a122_poll_runs_20260817.txt (all 3 planning runs
    completed @post_intake_finalize_validation_completed);
    Test Files/_a122_workbook_trace_20260817.txt (delivered workbooks:
    Tanager Revenue Drivers price 720 / capacity 364.09 per q = 28/wk;
    Sumac 550; NF clone 3 lines);
    Test Files/_a122_validator_offline_20260817.txt ((c) rowless
    fallback + SAME empty-payload text, (d) missing/0 price rejected,
    (e) multi-line unchanged, (f) flat unit_description fallback);
    Test Files/_a122_floor_R31_R32_20260817.txt (2/2 clear);
    _logs_persona_20260817_131750.txt lines 7/12/19 (POST 200 x3),
    3799/4522/5720 (workbook delivered x3), 0 Tracebacks.
  SUMMARY: A-122 FIXED. Submit validator is now row-first (mirror of
  _ops_driver_value: first non-None across lob_models[*].products[*],
  flat key only as fallback) for the 4 flat-validated drivers when
  is_multi_lob is False; the resolved values are written into payload
  BEFORE row=dict(payload) so intake_submissions unit_* columns carry
  the row values. Multi-line branch untouched (still skips flat checks,
  columns still NULL for multi-line - not asked, not changed). No
  branch deleted: the elif-not-multi rejects are still reachable by
  rowless legacy and by single rows lacking a value (that IS the
  negative case). DECLARED-vs-ACTUAL: spot-check + verify-forward
  e2e as declared - Tanager 87f0fbba + Sumac clone mn33t5g9 both
  400 -> 200 through the real door on a restarted backend (ONE :5050
  listener), mark_submitted ran, system runs started, all three builds
  terminal COMPLETED with workbooks delivered; NF multi-line control =
  a completed-not-submitted clone a122nf83 (6d2823db itself is
  already submitted -> 409 duplicate guard), also completed. Rowless
  control (c) and negative (d) proven offline on the validator seam
  (rowless legacy draft did not exist in the DB - Fetch & Fluff
  50658fff has rows AND flat, so a synthetic payload was used, as the
  task allowed). Floor R31/R32 clear; canary skipped (declared).
  Zero email/delivery lines touched (the existing internal run email
  fired as before: email.sent true in each 200 body).
  NOTES for triage (not built): (1) intake_submissions.
  units_per_week_capacity is an INT column - Sumac's contract-cadence
  weekly mirror 7.8462 stored as 8 (schema, pre-existing; the engine
  reads the draft rows, workbook shows 550/97.0 per q); (2) the mirror
  helper duplicates _ops_driver_value's 6 lines rather than importing
  from api_handlers/intake_consult (layering: service must not import
  the 20k-line handler); (3) workbook_model_status_check_skipped
  (CoInitialize) warnings on 2 of 3 builds are pre-existing (same
  warning in 08-13..08-16 logs), not from this change.
TASK:
  TURN 2 (mini, audit at the declared tier - spot-check + verify-forward
  e2e): diff confined to intake_submit_service.py (+ Test Files evidence
  scripts, no insert-module change needed - the insert reads
  row[col] and row=dict(payload) now carries the resolved values);
  row-first semantics mirror _ops_driver_value (first non-None across
  rows, flat fallback); flat fallback only reachable when no row
  supplies the field; confirm the e2e RAN: Tanager 87f0fbba + Sumac
  clone mn33t5g9 planning runs 91b4463c / b56bc477 COMPLETED with
  workbooks (paths in the persona log lines 3799/5720), NF clone
  a122nf83 run 05d34b67 COMPLETED (multi-line control); (c) rowless +
  same-error-text and (d) negative rejects per
  _a122_validator_offline_20260817.txt; zero email/delivery lines
  touched (git diff shows only intake_submit_service.py in app code);
  floor R31/R32 clear. Green -> stop -> Nick.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: git diff 4d554c9~1..4d554c9 (app code = intake_submit_service.py
    ONLY, +33 lines: _ROW_FIRST_DRIVER_FIELDS, _row_first_driver, one
    5-line block after the is_multi_lob decision; zero email/delivery
    lines); Test Files/_a122_validator_offline.py re-run by mini: GREEN
    on committed source, RED (4) on the 4d554c9~1 baseline for the
    RIGHT reason (single row w/ drivers -> 4 unit_* 'required' errors,
    the exact Tanager 400 shape); independent DB read of
    intake_consult_drafts: 87f0fbba/mn33t5g9/a122nf83 all submitted_at
    13:18:01/13:18:12/13:18:33, planning runs 91b4463c/b56bc477/05d34b67
    planning_run_status=completed @post_intake_finalize_validation_completed;
    intake_submissions 80/81 carry print job/720/28 and Property
    contract/550/8, 82 (multi-line NF) NULL as before; three workbooks
    ON DISK (Financial Models/ Tanager 13-23-13, NF 13-23-50, Sumac
    13-27-51), mini opened Tanager+Sumac Revenue Drivers: price 720 /
    550, capacity 364.09 / 97.01 per q; persona log 0 Tracebacks;
    floor R31/R32 re-run by mini via --only: 2/2 clear; VS TURN PLAN
    (watcher.log 13:15:44) vs actual: MATCH.
  SUMMARY: A-122 audited GREEN at spot-check + verify-forward e2e (the
  tier VS declared; honest - one validator branch + the values it hands
  the insert, no engine math / forward mover / builder touched).
  Row-first semantics are a faithful mirror of _ops_driver_value (first
  non-None across lob_models[*].products[*], flat key as fallback); the
  4 fields cover every flat-validated driver in the function (checked
  lines 350-397: no other flat driver is validated). Flat fallback
  reachable only when no row supplies the field; empty-legacy error
  text byte-identical (5 seam checks incl. rowless/negative/multi-line
  unchanged). VERIFY-FORWARD duty: e2e submit+build genuinely RAN on the
  NEW path for both stranded single-line drafts + the multi-line control,
  confirmed from DB + disk, not from VS's artifacts. VS notes triaged:
  (1) intake_submissions.units_per_week_capacity INT rounding 7.85->8:
  WONT-FIX - the table has NO readers in python/ (fetch_* helpers
  unused), the engine/workbook read the draft rows (Sumac WB 97.01/q
  correct) -> nothing reaches a delivered plan; (2) 6-line helper
  duplication vs importing the 20k-line handler: WONT-FIX, layering is
  right; (3) CoInitialize status-check-skipped warning: pre-existing
  (08-13 logs), only effect = uncached formula values in the xlsx
  (formulas intact, =C8*C9*C10), not a wrong number.
  DECLARED-vs-ACTUAL (mini): as declared - loaded HANDOFF, the diff,
  _ops_driver_value, the _a122_* artifacts, DB rows, workbook cells;
  reran seam + floor; canary skipped.
TASK:
  NONE - A-122 CLOSED GREEN. Every single-line business since 539fb17
  now submits and builds on the guided path. Nick: the next Cowork run
  (any single-line business) is the live confirmation; nothing for VS
  until then. Untracked _ablate/_debug scripts in Test Files predate
  this turn (Cowork-tester leftovers) - not part of A-122.
