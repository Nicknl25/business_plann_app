# Item 8 FINAL ACCEPTANCE - run 1 (VS turn 16, 2026-09-10 07:07-07:35)

VERDICT: blocked. The run FAILED at the INTAKE->POST_INTAKE boundary. No plan
was delivered, the writing-phase trigger was never reached, the freeze is back
OFF (FROZEN).

## The run

- Client: the dual-agent runner (Test Files/run_dual_agent_intake.py, GPT
  client persona, model gpt-4.1-mini) posting to /api/intake-consult and
  /api/intake-consult/system-run - the same backend path the browser uses.
  A browser-driven Claude Cowork client cannot be launched from a headless
  turn; Cowork's experience-issue filing was NOT exercised (owed).
- Seed: seed_two_owner.txt (two named co-owners, client-stated wages
  118,000 / 104,000, four staff, straight-shooter persona).
- Backend: :5050 pid 14528 (started 07:07:11 by the morning interactive
  session via context/run_api_5050_single.py, HEAD code f60007b - no app code
  changed since 5a64fdf; log = _api5050_server.err.log). ONE listener before
  and after.
- Freeze: ON 07:14:00 by VS (readback: "writing-phase trigger: ON (set
  2026-09-10 07:14:00 by VS - item 8 final acceptance run ...)"), back OFF
  07:29:18 (readback: "writing-phase trigger: FROZEN (off since 2026-09-10
  07:29:18 by VS - item 8 run a9db48dd FAILED ...)").
- Draft a9db48ddf7374d53a806ea2fb8c5d36e, client DBRMUWF51253561910,
  business "Bramblewood Physical Therapy", created 07:15:45; runner pid 30896
  from 07:15:35; 51 consult turns, 101 messages, intake 07:15:50 -> 07:26:06;
  coherence converged; ops/market/people/financials all confirmed.
- Planning run 6d97f2ad102645379460bdc456c595a3 started 07:26:06.30, FAILED at
  post_intake_initialize_validation_completed; runner got HTTP 500 at 07:26:09
  and exited (transcript: OneDrive Apps\Test Runs\09-10-2026 -- a9db48dd....txt).
- RUN VITALS (run_vitals_runs id 274): turns=51 turn_ms=479384 gpt_calls=105
  gpt_ms=417509 tokens=842202/21528 replays=0 holds=0 errors=0 stalls=0.
- ISSUE CHECK (watcher finalize): evaluated=173 recurred=0 exercised_clean=0
  not_exercised=173. Resolution events written today: 0.
- Artifacts: no Bramblewood workbook under C:\dev\Cilient Plans or the OneDrive
  Financial Models folder, nothing under Client Written Plans or _v2_runs, no
  "Writing phase" line in the backend log (the trigger sits after acceptance
  and acceptance was never evaluated). The POST-INTAKE FAILURE email was sent
  (working system, untouched).
- Floor: gate --only R31,R32 GREEN 2/2 before (gate_only_R31_R32_before.txt)
  and after (gate_only_R31_R32_after.txt).

## The failure, verbatim

planning_runs.failure_reason:

    INTAKE->POST_INTAKE: field 'people_json.people.4.full_name' expected
    Field required (and 55 more error(s)), got {'name': 'Dr. Ingrid Solvang',
    'title': 'Clinical Director and Co-owner', 'years_experience': 15,
    'education_credentials': 'Doctor of Physical Therapy (DPT) with all
    required licenses and ...

pydantic: 56 validation errors for IntakeDraftContract = rows 4..11 x the seven
required fields (full_name, role_title, primary_responsibilities,
relevant_background, experience_years, why_strengthens_business, paragraph).

## The stored roster (people_json_a9db48dd.json)

    0 full_name Dr. Ingrid Solvang   role_title Clinical Director and Co-owner  annual_wage 118000 wage_source client_override
    1 full_name Dr. Marcus Abernathy role_title Managing Partner and Co-owner   annual_wage 104000 wage_source client_override
    2 full_name Staff Physical Therapists (2)  annual_wage 78000 client_override
    3 full_name Front-Desk Staff (2)           annual_wage 38000 client_override
    4..11 = FOUR copies each of {name: Dr. Ingrid Solvang | Dr. Marcus Abernathy,
            title: ..., years_experience, education_credentials,
            annual_pay: 118000 | 104000, wage_source: client_provided, annual_wage: null}

Row keys `name`, `title`, `annual_pay`, `years_experience`,
`education_credentials` are the ROUTER's invented shape. `annual_pay` has no
reader anywhere in python/ (grep). financials: current_payroll =
payroll_total_year1 = 338,000; owner_compensation = 18,500 =
(118,000 + 104,000) / 12 (the item-7 mirror, sum of both owners, on a live
intake); payroll_basis_people_roles carries the four canonical rows plus eight
nameless zero-wage rows (the raw rows read as people with no wage).

## The mechanism (backend_people_stage_slice.txt, verbatim lines)

    07:20:56 TURN_INTENT turn=45 action=edit_patch patch={'people.people': [{'name': 'Dr. Ingrid Solvang', 'title': ..., 'annual_pay': 118000, 'wage_source': 'client_provided'}, {'name': 'Dr. Marcus Abern...
    07:21:15 TURN_INTENT turn=47 action=edit_patch patch={'people.people': [{'name': 'Dr. Ingrid Solvang', ... 'annual_wage': None}, {'nam...
    07:21:15 PEOPLE_PATCH incoming=3 restored=['?', '?'] field_kept=[]
    07:21:44 PEOPLE_PATCH site=people_finalize_done_adding incoming=4 restored=['?', '?', 'Owner', '?', '?'] field_kept=[]
    07:21:59 OWNER_ROW_UNIQUENESS merged=1 groups=2 named_owners_kept=['Dr. Ingrid Solvang', 'Dr. Marcus Abernathy']
    07:22:11 TURN_INTENT turn=51 action=edit_patch patch={'people.people': [{'full_name': 'Dr. Ingrid Solvang', 'role_title': ...   (8 rows: 4 canonical + the 4 raw rows echoed back)
    07:22:11 PEOPLE_PATCH incoming=8 restored=['?', '?', '?', '?'] field_kept=[]
    07:26:06 ERROR api: System run failed for draft a9db48dd...

1. The intent router's edit_patch carries `value_json` as a JSON STRING
   (intent_router.py ~879-911: patch = [{field, value_json}]). The people row
   schema at intent_router.py ~536-575 (full_name, role_title, ...,
   additionalProperties false) is prompt documentation, not enforced by
   structured outputs. The router emitted rows in its own shape twice (turns
   45 and 47) and once in the canonical shape with the raw rows echoed (51).
2. The people.people door (intake_consult.py ~14499) accepts any list of
   dicts. `_person_row_identity` (~14158) returns None for a row with neither
   full_name nor role_title, so `_merge_people_rows` can never match a raw row:
   incoming raw rows APPEND, standing raw rows are RESTORED (label '?'). Every
   pass through the door grows the junk: 2 -> 5 -> 9 (after finalize) -> 12.
3. The finalize doors (`_merge_model_roster`, 19f69ef item 5 R1) restored the
   raw rows and the bare Owner row beside the model's four canonical rows.
4. The boundary contract (IntakeDraftContract) rejected the eight raw rows.

LATENT vs NEW: before 2026-09-09 the people.people door and the finalize doors
REPLACED the roster wholesale (the Rasheed Fennimore deletion door), so raw
router rows never survived to the boundary - they were deleted along with real
people. 9c06f7a (people.people merge) and 19f69ef (four model-output doors
merge) made the guard RESTORE them. Both fixes were verified by replaying THE
RECALC on stored drafts whose rows were all canonical; no live intake ran
through the router to SUBMIT. This is the VERIFY FORWARD hard case (2026-08-17
precedent: the submit validator rejecting the new path's model) a second time.

## Second consequence of the same root (READ-caught, stated-wage class)

The finalize narrative the client was asked to review (runner turn 26) showed:

    Dr. Ingrid Solvang ... Estimated annual wage: $104,060/year.   (client said 118,000)
    Dr. Marcus Abernathy ... Estimated annual wage: $104,060/year. (client said 104,000)
    Two full-time Staff Physical Therapists ... $94,860/year.       (client said 78,000 each)
    Two Front-Desk ... $38,390/year.                                 (client said 38,000 each)

OEWS medians: the client-stated wages lived in the unmatched raw rows
(`annual_pay`) and the bare Owner row, so the model's canonical rows inherited
nothing. This client corrected ("There are inaccuracies in the wages ...") and
the correction landed as client_override; a less attentive client would have
shipped OEWS wages against stated ones - a wrong number in a delivered plan.

## Third finding, independent of the raw rows (WRONG NUMBER class, for triage)

The app asked for key people one at a time ("pick one person"); the client
answered with the two groups (2 PTs at 78,000 each, 2 front-desk at 38,000
each). The finalize made grouped rows "Staff Physical Therapists (2)" 78,000 and
"Front-Desk Staff (2)" 38,000, each counted ONCE in payroll_basis_people_roles;
the rest-of-team question then said "Only count people we haven't listed yet"
so rest_of_team_payroll_year1 = 0. Stored payroll 338,000 vs the client's true
454,000 (118 + 104 + 2 x 78 + 2 x 38): understated by 116,000 (25%). A plan
built from this draft carries the wrong payroll. Not this turn's fix.

## Item 7 forward proof, as far as the run got

- Door ack + numeric receipt at the first owner answer (runner turn 24,
  verbatim): "Thanks for that, I've updated your plan so first-year now uses 12
  months, your annual wage and first-year payroll are set to $118,000 per year,
  and total owner pay shows as $9,833 per month (plus the three related
  details). (One note: I haven't recorded owner pay monthly yet - we'll get to
  that in a moment.)" - 9,833 = 118,000 / 12 with one owner landed (true at
  that moment); no receipt echoed 18,500 back to the client as their own pay.
  The trailing state note claims the field is unrecorded in the turn that
  recorded it = open issue 139 class (observation).
- Mirror after both owners: owner_compensation 18,500 = the SUM (item 7).
- SDE sheet / derived facts / valuation prose: NOT reached (no build).

## Other observations (not filed by Cowork - no Cowork; recorded for triage)

- Financials: client said "No, we haven't made any larger one-time purchases
  recently" -> app: "I wasn't able to apply that change yet. What current
  capital spending amount should I record?" (explicit-none answer not mapped
  to 0; issue 287 neighbourhood). Client answered zero and it landed.
- Issue 571: probe_json = {"note": "Start consultation on a fresh draft, ..."}
  carries no retest condition, so `_run_exercised` returns "probe states no
  retest condition (metadata/notes only)" - NO run can ever auto-record its
  resolution. The consultation-start path was exercised clean here (51 turns,
  no NameError) but nothing was recorded: the run is not clean and the task
  tied the event to the clean run. Row unchanged: status open,
  clean_exercise_count 0, runs_since_last_seen 0.

## Files

- runner_stdout.txt / runner_stderr.txt - the runner's console (full transcript)
- seed_two_owner.txt - the persona seed (reusable for the rerun)
- people_json_a9db48dd.json, financials_json_a9db48dd.json - stored payloads
- backend_people_stage_slice.txt - the people-stage backend log lines
- gate_only_R31_R32_before.txt / _after.txt - the floor, GREEN 2/2 both
