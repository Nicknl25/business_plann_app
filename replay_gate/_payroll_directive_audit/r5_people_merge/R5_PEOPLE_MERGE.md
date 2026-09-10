# Item 5 - R1 people-stage merge discipline + owner-wage-hold retire rider (VS, 2026-09-09)

Nick: "the ops door taught us a guard on one write path doesn't cover the
other. Do it before it costs a client." Two guard-class fixes, one spot-check
turn. Code: python/api_handlers/intake_consult.py only (diff in
intake_consult_r5.diff, 145 lines, all additions). Pins:
tests/test_people_stage_merge_and_hold_retire.py (17). Nothing written to the
DB. Freeze stays FROZEN. No system run, no writing-phase trigger, no email or
delivery code touched, no legs touched.

## R1 - every model-output roster write goes through the people write guard

Enumerated from the CURRENT source (not the task's pre-shift line numbers,
which had drifted by ~340-380 lines, not ~59). A "model-output roster write"
is a `people_json` persist whose `people` list was produced by a model call
(the collection extractor or people_capability_finalize) rather than read from
the stored row. There are FOUR, not three - the fourth (S4, the finalize_ready
close-out) surfaced when the structural pin found two `final_obj =
people_capability_finalize(` anchors.

| site | model call | post-edit lines | wholesale write it fed | disposition |
|---|---|---|---|---|
| S1 `collection_extractor` | `extract_people_collection_progress` (handler body, "People: persist raw structured person facts incrementally") | 21572-21587 | `next_people_json["people"] = extracted_people_list` -> `people_json = next_people_json` -> persisted by every later `append_messages(... people_json=people_json ...)` on the turn (L22065 people-focus branch, L22562, L21101, L17706 completion) | GUARDED: `_merge_model_roster(people_json, extracted_people_list, site="collection_extractor")` before the assignment |
| S2 `people_finalize_done_adding` | `people_capability_finalize` inside the done-adding detector branch | 18348-18370 | `_build_people_review_payload(final_obj)` -> `people_json = dict(final_obj)` -> `append_messages(people_json=people_json)` L18370 | GUARDED: merge on `final_obj["people"]` BEFORE the review payload is built, so the persisted roster and the spoken review carry the same people |
| S3 `people_finalize_review` | `people_capability_finalize` on `review_ready` | 21998-22012 | OEWS enrichment -> `append_messages(people_json=review_people if review_ready ...)` L22065 | GUARDED: merge on `review_people["people"]` after sanitize, before enrichment |
| S4 `people_finalize_ready` | `people_capability_finalize(intake_context=intake_context, conversation_messages=final_messages)` on the finalize_ready close-out (`elif focus == "people"`) | 22379-22389 | OEWS enrichment -> `people_json = final_obj` L22436 -> `append_messages(people_json=people_json)` L22531 / completion L17706 | GUARDED: merge on `final_obj["people"]` after sanitize, before enrichment |

The helper `_merge_model_roster(existing_people_json, incoming_rows, *, site)`
(L14219) is `_merge_people_rows` + the site-named `PEOPLE_PATCH site=<site>
incoming=N restored=[...] field_kept=[...]` trace (same logger, same wording
as the people.people door, plus `site=`). A model output with NO people list
merges as an empty list, so the standing roster rides forward whole instead
of vanishing with it. Explicit remove_role remains the only deletion door;
`_merge_people_rows` and the people.people door are untouched.

Every OTHER `people_json=` persist kwarg in the file (18 persist sites total,
people_json_write_census.txt) carries the IN-MEMORY roster - the stored row,
the recalc's mutation of it, the guarded `_apply_scoped_patch` output, or the
S1-S4 output already merged at its source:

| persist line | where | what it carries | disposition |
|---|---|---|---|
| L11421 | `_run_financials_turn_and_sync_inner` completed-state fold persist | `_ppl_work` = shared people after THE RECALC | not a model write (recalc mutation) |
| L17348 | `_coherence_blocked_response` | handler's in-memory people_json | not a model write |
| L17557 | handler preamble (recalc changed people) | recalc mutation of the stored row | not a model write |
| L17706 | `_persist_intake_completion` closure | `people_value` = in-memory people_json at completion | carries S1/S4 output when same turn - already merged at source |
| L17856, L18370, L19085, L19673, L19746, L19875, L19940, L20902, L20950, L21101, L21344, L22531, L22562 | handler body branches (done-focus, S2 persist, patch path, client-override edits, leaf patch, next-focus, ops-driver, number-set) | in-memory people_json; L19085/L20902 are the `_apply_scoped_patch` output (people.people door, already merged) | not a model write / already-merged |
| L22065 | review persist | `review_people` (S3, merged) or in-memory people_json (S1, merged) | already-merged at source |

Outside intake_consult.py (listed, NOT changed this turn - flag for triage):
- python/api_handlers/people_capability.py L313, L398-404, L565-570 write
  `people_json` into the consult draft via `append_consult_messages` from a
  people_capability_finalize output (L538 `final_obj["people"] = enriched_people`).
  This is the LEGACY `/api/people-capability` route family (api.py 265-289).
  The frontend has NO caller (grep frontend/src: only reads
  `shared_context.people_capability`), so it is off the guided path. It is a
  wholesale model door by shape; if any client can still reach it, it needs the
  same helper - one call per site, same pin shape. Nick/mini to say.
- post_intake_headcount/schedule.py L1289/L1326 and writing_phase/facts/assembler.py
  L96 assign `people["people"]` on derived/system-run copies, never to the draft
  row - not roster writes.

No site changes what reaches finalize / submit / build (the merged roster is
the stored roster plus the model's additions; the unchanged case merges to the
model roster field for field) - no model-flow split needed.

### Verify-forward (what the merge touches one step downstream)
- The review TEXT at S2/S3/S4 is composed from the merged list (merge runs
  before `_build_people_review_payload` / OEWS enrichment), so a restored
  person appears in the review the client reads, not just in the row.
- OEWS enrichment runs on the merged list: `apply_oews_wages_to_people` leaves
  `client_override` rows untouchable (people_roles.py 551-560, 656-660), so a
  restored client-stated wage survives enrichment.
- Order: `_merge_people_rows` emits incoming rows first, restored rows after.
  A finalize that carries everyone keeps the model's order; a finalize that
  DROPS the first owner and keeps the second would put the second first and
  flip the order-dependent owner_compensation mirror - the R4/item-7 class,
  already carried to item 7 (single-row reorder pin). Not new to this turn.

### Finding for triage (NOT built - new behavior, Nick's call)
A model output can carry a DIFFERENT non-null wage for a client-stated
person (`wage_source` null, `annual_wage` 130,000 against a stored
client_override 142,000). The merge takes the non-null incoming wage and
keeps the stored `wage_source` (null against a standing value), so the row
would read client_override with the model's number. The wholesale write did
this too (it replaced the row outright), so the merge makes nothing worse;
but "a client-stated wage is untouchable by a model output" is the OEWS
module's own invariant and could be one more check in the helper. Feature
decision, flagged, not auto-built.

## Rider - THE RECALC retires a STALE owner-wage hold

Pre-shift ~9531-9545 -> now 9480-9588. `_hold_raised_this_pass` is set where
the owner-row pass raises the hold (L9547); after the pass, a stored
`_owner_wage_conflict_hold` retires (pop, `OWNER_WAGE_HOLD_RETIRED` log line)
when this pass raised no hold AND the roster carries two or more DISTINCT
NAMED owner-titled humans. section.py's popper and wording untouched.

### DIVERGENCE from the task wording, measured, disclosed
The task said "retires the hold when no same-human owner group remains (the
hold's own raise condition)" and called the 104 carriers stale. Measured on
deep copies of every carrier (vs_r5_nomove.py, census block):

- carriers today: 102 (mini's 104 minus the two R3 repaired)
- carriers with two named owner humans: 0
- every one of the 102 is a Sumac Ridge Grounds replay clone with hold
  {kept 48,000 / other 33,999.96} and ONE owner on the roster (Delia Rennick,
  "Owner / Crew Lead") - the CW-026 timing-collision shape: two figures for
  the SAME human, i.e. GENUINE, not stale.

The literal rule would retire all 102 genuine holds, and by construction
EVERY future hold one pass after its raise: the raise deletes the duplicate
row in the same pass, so "no same-human group remains" is true on the very
next recalc, and the gate would never ask - a silent pick, the thing CW-026
ruling #1 forbids. The deal breaker as named ("two figures that were never
two figures for one person") is exactly the two-human case, so the rider
retires on that condition: two or more distinct named owner humans present.
Both task pins hold as written (stale hold + two-human roster -> gone and
nothing else moves; genuine same-human conflict -> kept). WOULD-RETIRE count
today: 0 (both real stale carriers were repaired by hand in R3; nothing live
retires). If Nick wants the literal rule instead, say so - it is a one-line
condition, but the pins above will show what it silences.

## Instruments and results (all in this directory)
- vs_r5_nomove.py -> nomove_before.txt/json (22:58:44, pre-edit) and
  nomove_after.txt/json (23:02:50, post-edit); nomove_compare.txt: ALL 9
  DRAFTS IDENTICAL (176d4279, 1b7eeb63, 482b870f, 65e3c466, b4929a89,
  bb793dbb, c8a6b6b5 - the payload_*.json set of AUDIT_SUMMARY.md - plus live
  Marchetti 3201a64c 820,000 and Northwind 3c2224e1 52,202,210), financials /
  people / year1 digests equal, no hold raised or retired. Census before =
  after: 102 carriers, 0 would retire, 102 kept, 0 errors.
- tests/test_people_stage_merge_and_hold_retire.py: 17 passed on the edited
  tree. Red-proof redproof_at_HEAD_0fcb703.txt: the SAME file in a scratch git
  worktree at HEAD 0fcb703 (.env copied in for the import, worktree removed
  after) -> 14 failed / 3 passed: 7 behavior pins "the R1 model-roster merge
  helper is missing", 4 structural pins "'_merge_model_roster(' not found"
  after each site anchor, the count pin, the door pin (helper def absent), and
  the stale-hold retire pin ("'_owner_wage_conflict_hold' unexpectedly found"
  with both partners on the roster and payroll 820,000). The 3 that pass at
  HEAD are the unchanged behaviors (genuine hold kept on one owner, same-human
  conflict raises and keeps, no hold -> no retire line) - expected.
- Floors: tests/test_golden_master_bare_mode.py 17 + test_writing_phase_freeze_switch.py 10
  + test_people_write_guard_and_derived_receipt.py 14 = 41 passed;
  gate --only R31,R32 GREEN 2/2 (_gate_only_R31_R32_20260909_r5.txt).
- Backend: :5050 restarted via scripts/start_persona_backend.ps1 at 23:06:26
  (stale 33576 killed), ONE listener (PID 34240), log _logs_persona_20260909_230626.txt.
- Freeze readback unchanged: FROZEN (off since 22:12:45), exit 3.
