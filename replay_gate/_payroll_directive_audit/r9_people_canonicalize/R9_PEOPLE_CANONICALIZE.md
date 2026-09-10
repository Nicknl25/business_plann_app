# Turn 18 - the people-row CANONICALIZATION fix (VS, 2026-09-10)

Deal breakers it prevents (guided path, both seen on item-8 run 1, draft
a9db48dd Bramblewood Physical Therapy): a two-owner client dead-ended with
NO PLAN at the INTAKE->POST_INTAKE boundary (IntakeDraftContract, 56 errors,
eight people rows in the intent router's own shape), and OEWS medians shown
as the client's stated wages when the stated rows sit unmatched.

## The fix (python/api_handlers/intake_consult.py, one file; diff in intake_consult_r9.diff)

Inside the ONE helper every people write funnels through - `_merge_people_rows`,
shared by the people.people door and the four model-output doors
(`_merge_model_roster` sites collection_extractor, people_finalize_done_adding,
people_finalize_review, people_finalize_ready):

1. `_canonicalize_person_row(row) -> (row, aliased)` - the router's aliases
   mapped onto the contract keys, ONLY when the canonical key is absent or
   empty: name->full_name, title->role_title, annual_pay->annual_wage (float),
   years_experience->experience_years (str, the contract types it str),
   education_credentials->relevant_background; alias keys removed after
   mapping; wage_source client_provided->client_override; a client-stated
   annual_pay with no wage_source at all is stamped client_override (the
   extractor door's own rule). `aliased` is True when the row carried ANY
   raw-shape key. A canonical row passes through untouched (aliased False).
2. `_merge_people_rows` canonicalizes every INCOMING row and every STANDING
   row before matching.
   - A row with no identity after aliasing (neither full_name nor role_title)
     is DROPPED and named in report["dropped"] (its key list) - incoming or
     standing - never stored for the boundary to reject.
   - A HEALED row (aliased=True) whose NAME identity is already on the
     roster - standing, or produced earlier in the same patch - is the same
     statement echoed and folds FILL-ONLY into that row (report["healed"] /
     report["deduped"]): a key the base row states keeps its value, a key it
     lacks is taken from the echo. This is what makes the verbatim turn-51
     correction (four canonical rows + the four raw copies) end at four rows,
     and what heals the eight raw rows already stored on a9db48dd on its next
     people write (12 -> 4, contract passes).
   - Rows that were canonical to begin with follow today's path byte for byte
     (no fold, no drop) - pinned, and proven on every stored roster (census).
   - Matching, restore, null-keeps-standing and remove_role are unchanged.
3. Trace: the PEOPLE_PATCH line (both the door and `_merge_model_roster`)
   gains ` aliased=[...] healed=[...] deduped=[...] dropped=[...]` tokens,
   appended ONLY when non-empty - a line for canonical rows is byte-identical
   to the item-5 shape (pinned).
4. Receipt, never a silent drop: the people.people door appends
   `{"field": "people.people", "disposition": "people_row_dropped", "value": [keys]}`
   to `_derived_patch_receipt` (the same rail the derived-field drop rides);
   the edit path turns it into the say-do accounting (leaf "people"), and
   `_unapplied_fields_note` speaks `_PEOPLE_ROW_DROPPED_NOTE` for that leaf
   instead of the false "we'll get to that"; `_apply_stage_people_door_keys`
   (the stage people door, which composes its own ack and consumes the rail)
   reads the drop before the pop and appends the same note to its ack. The
   market-summary re-show path (18981) pops the rail as before - the
   PEOPLE_PATCH dropped= trace still records it there.

Not changed: the router (inner-shape enforcement is Nick's item 4), grouped
rows counted once (item 1), issue 571 (item 3), email/delivery, legs, any
re-bless.

## Pins (tests/test_people_row_canonicalize.py, 27) - pins_after.txt

- VerbatimReplay (4): the three verbatim TURN_INTENT patches
  (verbatim_turn_intent_rows.json, extracted unchanged from
  _api5050_server.err.log lines 103 / 107 / 117) replayed IN ORDER through the
  REAL doors - `_apply_scoped_patch` for turns 45 (people.people + the same
  turn's owner_pay_monthly, the log's key order), 47 and 51; `_merge_model_roster`
  site=people_finalize_done_adding for the finalize (the model's four canonical
  rows with null wages); THE RECALC (`_sync_financials_consult_persistence_state`,
  OWNER_ROW_UNIQUENESS) between them. Ends with FOUR rows
  (2 -> 2 -> 3 -> 5 -> 4 -> 4), PeopleJsonContract on the stored a9db48dd
  envelope passes (0 errors) and every row passes PersonContract; Ingrid
  118,000 / Marcus 104,000 client_override, experience_years "15" / "12",
  staff 78,000 / 38,000, owner_compensation 18,500 (the item-7 mirror, sum of
  both owners); no raw key survives; no '?' label and no dropped= in the log;
  the four PEOPLE_PATCH lines quoted (turn 45 aliased both, turn 47 merged
  both + the verbatim bare Owner row appends, finalize restored=['Owner']
  field_kept both annual_wage, turn 51 deduped the four echoes).
- Canonicalizer (6): the raw router row maps onto the contract keys; a legacy
  row carrying name beside full_name keeps full_name (and title beside
  role_title, annual_pay beside annual_wage); an empty canonical value takes
  the alias; null alias values map nothing; a canonical row passes through
  untouched; the bare Owner row is canonical and unnamed (identity
  ('title','owner')).
- MergeDiscipline (6): identity-less row dropped and reported; the bare Owner
  row appends when incoming and restores when standing (never dropped); the
  stored 12-row a9db48dd roster heals on the next write (8 healed, 4 rows,
  contract passes, fill-only keeps the finalize's richer background); canonical
  duplicates are NOT folded (today's path); a healed echo of a standing person
  merges, never appends; the trace line for canonical rows is the item-5 shape.
- ModelOutputDoors (5): one raw-row case per site through `_merge_model_roster`
  (the raw Ottoline echo merges into her row, Rasheed restored, trace names the
  site and aliased=['Ottoline Marchetti']); an identity-less model row is
  dropped with the trace.
- OewsAfterFinalizeMerge (1, triage item 2): the replay's roster through
  `apply_oews_wages_to_people` (OEWS fetch mocked to []) leaves every
  client_override wage untouched - 118,000 / 104,000 / 78,000 / 38,000.
- DropReceipt (5): the door leaves the receipt (and none for named rows); the
  note speaks the dropped person and drops the false promise; the stage
  people door's ack carries the note (and is silent without a drop).
- The item-5 file (test_people_stage_merge_and_hold_retire.py, 23) re-run
  green: the four model-output doors' existing pins plus the structural pins.

RED-PROOF (redproof_at_HEAD.txt): the same pins against HEAD 5435f438's
intake_consult.py (file swap, restored byte-equal): 25 failed / 2 passed -
`roster ended with 12 rows, steps=[... 3, 5, 9, 8, 12]`,
`PeopleJsonContract errors=56 on 12 rows`, the helper and the note missing
(AttributeError). The two that pass at HEAD are the two "today's behavior"
pins (canonical duplicates not folded; bare Owner row appends/restores) - by
design, they pin what must NOT change.

## Neighbors (neighbor-check tier; canary skip)

- Recalc NO-MOVE on the nine directive drafts (vs_r5_nomove.py --label
  r9_before / r9_after; nomove_r9_before.txt / nomove_r9_after.txt):
  9/9 financials + people digests identical before and after the edit.
  Hold census 102 carriers / 0 would-retire, unchanged.
- ALL STORED ROSTERS (vs_r9_census.py, census_all_rosters.txt, read-only,
  the real helper on (stored_rows, []) per draft = the shape of the next
  people write): 8,984 drafts, 8,193 with people, 17,858 rows.
  would_drop = 0. healed = 8 (all on a9db48dd, the only draft whose row
  count changes: 12 -> 4). 185 drafts carry a nameless owner-titled row
  (the Sumac / Halbrook F5 class) - every one survives the merge (asserted
  per draft). Every draft the canonicalizer does not touch merges byte-equal
  to its stored rows (asserted per draft).
  aliased = 1,025 rows on 510 drafts, three shapes: (a) 1,015 rows on
  April-2026 drafts in an OLD schema {name, role, summary} (e.g. 00050e6d
  ForgeBite: {"name": "Owner", "role": "Owner", "summary": ...}) - not router
  rows, no live path; today they have NO identity (restored as '?'); after
  the fix their next people write maps name->full_name and nothing else
  (role is not an alias) - no drop, no fold, same row count; (b) the 8 raw
  rows on a9db48dd (the fix's target); (c) 2 rows on 523fd1b5 NexaCloud
  (2026-04-15, in_progress) in a {name, title, years_experience, credentials,
  notes} shape - an earlier router-shape sighting; they would alias to
  full_name / role_title on their next write, no drop, no fold.
- The five doors are covered by the ONE edit; the item-5 structural pins
  still prove each site calls `_merge_model_roster` before its persist.

## Floors

- gate --only R31,R32: GREEN 2/2 before (gate_only_R31_R32_before.txt) and
  after (gate_only_R31_R32_after.txt).
- people pin files (4): 73 passed (floors_pins_after.txt).
- :5050 restarted after the edit via scripts/start_persona_backend.ps1 at
  08:20:22 - stale 14528 killed, ONE listener pid 28352 (launcher 19336),
  log _logs_persona_20260910_082022.txt.

## VERIFY FORWARD - the live two-owner intake (see the RUN section below)

## THE RUN - live two-owner dual-agent intake on the new code (VERIFY FORWARD, hard case)

- Client: Test Files/run_dual_agent_intake.py (GPT client persona, gpt-4.1-mini)
  with seed_two_owner.txt verbatim (reused from r8), launched detached via
  python Popen at 08:21:17 (runner pid 37436, runner_pid.txt), stdout/stderr in
  runner_stdout.txt / runner_stderr.txt (stderr empty). A headless turn cannot
  launch Cowork's browser session - Cowork's experience-issue filing stays owed
  to a run Nick launches.
- Backend: :5050 restarted on the patched code BEFORE the run
  (start_persona_backend.ps1 08:20:22; stale 14528 killed; ONE listener pid
  28352 before and after; log _logs_persona_20260910_082022.txt).
- Freeze: FROZEN before (freeze_status_before_run.txt: off since 07:29:18) and
  after (freeze_status_after_run.txt, unchanged) - never touched this turn.
- Draft d8cdfd1ed3af4dd584194da39354c025, client GLFLTIK71547690758,
  "Bramblewood Physical Therapy", created 08:21:25; 48 consult turns, intake
  08:21:31 -> 08:32:54; ops / market / people / financials all confirmed,
  coherence converged.
- THE BOUNDARY: planning run 26ecbea2454548a993468d04d1965dd1 started
  08:32:54.67, post_intake_initialize_validation_completed, ... ,
  post_intake_finalize_validation_completed COMPLETED 08:38:21.84 (327 s);
  POST /api/intake-consult/system-run -> 200 (log line 1412). Run 1 died at
  exactly this boundary with 56 errors.
- RUN VITALS (run_vitals_runs id 276/277): turns=48 turn_ms=561493
  gpt_calls=119 gpt_ms=610707 tokens=862313/31224 replays=0 holds=0 errors=0
  stalls=0 run_s=327.
- THE STORED ROSTER (readback_d8cdfd1e.txt, fresh connection): TWO rows, both
  canonical, no raw key:
    [0] Dr. Ingrid Solvang / Clinical Director and Co-owner / 118000.0 / client_override / experience_years '15'
    [1] Dr. Marcus Abernathy / Managing Partner and Co-owner / 104000.0 / client_override / experience_years '12'
  rest_of_team_payroll_year1 = 232000; current_payroll = payroll_total_year1 =
  454000.0 (the client's true total - run 1 stored 338,000); owner_compensation
  = 18500.0 (the item-7 mirror, sum of both owners / 12); no stated-total
  target, no hold, no receipt residue; payroll_basis_people_roles = the two
  owners + "Rest of team (client-stated total)" 232000 (run 1 carried eight
  nameless zero-wage rows). PeopleJsonContract on the live people_json: PASSED.
- PEOPLE-STAGE LINES (backend_people_stage_slice.txt): the router emitted
  CANONICAL rows this run - TURN_INTENT 08:28:29 people.people carries
  full_name / role_title / relevant_background / experience_years '15' /
  annual_wage 118000 / wage_source client_override for both owners - so NO
  PEOPLE_PATCH line fired at all (nothing restored, aliased, deduped or
  dropped; the trace speaks only when the guard did something), no '?' label,
  no dropped=, no OWNER_ROW_UNIQUENESS fold. The RAW SHAPE WAS NOT EXERCISED
  LIVE on this run (the router emits it non-deterministically: raw twice on
  run 1, canonical here); the verbatim-row pins stand as the red-proof of the
  raw path and this run proves the live path end to end on the new code.
  REST_OF_TEAM_ANCHOR applied factor=1.9956 stated_pool=232000 (up-scale, so
  no DOWNSCALE line - correct per item 6).
- THE TRIGGER: log line 1411, 08:38:35.910 WARNING api: Writing phase FROZEN
  for draft d8cdfd1e... (run 26ecbea2..., business Bramblewood Physical
  Therapy): trigger switch is OFF (set 2026-09-10 07:29:18 by VS ...). No
  Bramblewood artifact under Client Written Plans or _v2_runs (asserted). The
  system run delivered its workbook as designed under the freeze.
- THE WORKBOOK (both places, same digest of content):
  C:\dev\Cilient Plans\Bramblewood Physical Therapy -- 09-10-2026 08-38-26.xlsx
  and the OneDrive Financial Models copy. Checks!B2 = OK, zero FAIL rows.
  Valuation: SDE row note "EBITDA + $55,500/qtr owner pay (2 owners)"
  (= (118,000 + 104,000) / 4 - the item-7 SUM chain on a live intake, first
  time reached), SDE y1..y5 176,396 / 178,659 / 180,587 / 193,827 / 209,154 /
  223,035 (six columns incl. the base), Equity value 2,500,273, implied
  multiple of year-5 SDE 2.357 against the 2.7x exit multiple.
- FINALIZE NARRATIVE (runner_stdout.txt 212 / 214): "Estimated annual wage:
  $118,000/year." and "$104,000/year." - the client's stated wages, not OEWS
  medians (run 1 showed $104,060 x2). The second deal breaker is absent here.
- ISSUE CHECK (watcher): evaluated=173 recurred=1 exercised_clean=0
  not_exercised=123. One issue filed - investigated below.

## Findings from this run (report, not built - scope law)

F-A. ISSUE 138 REOPENED - FALSE REOPEN, a probe defect, not a plan defect.
  flow:financials:two_line_business_gets_one_blended_cogs_and_the_question_goes_unanswered
  (occurrence 717, resolution event 1437 event_type=reopened, previous basis
  artifact_verified / confirmed -> status recurring, reopened_count 7).
  observed: "ops_per_line_cogs: not_applicable - 1 product row(s) <
  min_lines=2; workbook_cogs_rows: fail - Model Inputs carries 0 per-line COGS
  driver row(s), expected >= 2". Bramblewood is a ONE-line business (one
  service line, physical therapy visits) - the probe's ops half correctly says
  not_applicable, but its workbook half (kind workbook_cogs_rows, sheet FINMO,
  min_rows 2) has no applicability gate and fails on every one-line business,
  contradicting a confirmed resolution. Verdict: NOT a defect in this plan;
  the artifact gate's workbook_cogs_rows check needs the same min_lines
  applicability as ops_per_line_cogs (or the probe needs it) - the issue store
  / artifact gate is not this turn's scope; handed to mini (CW-031 artifact
  gate, replay_gate) / Nick.
F-B. FALSE-RECEIPT CLASS on the guided path, delivered numbers RIGHT. The
  employee-count question ("How many people are on payroll right now?") was
  answered with the six people AND their wages; the figure-landing rule sent a
  per-person wage to people.total_team_payroll as a STATED TOTAL: turn 274
  "Recorded: total team payroll $78,000." (log 08:30:33 STATED_TOTAL_HOLD_RECEIPT
  stated=78000 landed=222000 unapplied=-144000) and, after the client's
  correction restating $454,000, turn 290 "Recorded: total team payroll
  $38,000." (08:30:55 stated=38000 landed=222000 unapplied=-184000); the
  hold reader then asked twice "I still have $454,000 landed and $144,000
  [then $184,000] that hasn't found a home" - a NEGATIVE unapplied (a stated
  total BELOW the named-people sum) rendered as money without a home, and the
  reply's "$454,000 landed" disagrees with the log's landed=222,000. The stored
  state ended RIGHT (current_payroll 454,000, no target, no hold - the fold
  never moved a number), so no wrong number reached the workbook; but two
  "Recorded:" claims for totals that never landed and two confusing holds are
  the false-receipt class (third appearance). Triage for Nick: (i) a stated
  total below the landed named-people sum is not a total - the receipt must
  not say Recorded and the hold must not speak a negative gap; (ii) an answer
  to the headcount question carrying several per-person wages must not land
  one of them as total_team_payroll. Separate spot-check turn; not built here.
F-C. The grouped-row class (run 1: "Staff Physical Therapists (2)" counted
  once) did not arise: the finalize kept the four staff in rest-of-team
  (232,000) and the roster carries the two owners only, so payroll = 454,000.
  Nick's triage item 1 stands as filed; this run neither confirms nor clears
  it.
