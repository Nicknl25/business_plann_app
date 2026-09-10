# R3b CLEANUP - item 3 of Nick's payroll rulings (VS, 2026-09-09 ~21:10)

Nick: "Delete the artifacts." Destructive, Nick-ruled, ships alone. No code, no legs,
no system run, no writing-phase trigger, email path untouched. Instrument:
`vs_r3b_cleanup.py` (dry run = snapshot + guards; `--delete` = the surgery + fresh-connection
readback). Logs: `r3b_cleanup_DRYRUN.txt`, `r3b_cleanup_DELETE.txt`, `deleted_paths_and_rows.txt`.
Gate floor: `_gate_only_R31_R32_20260909_r3b_cleanup.txt` GREEN 2/2.

## The doctrine (what "its run rows" means)
Every table in `biz_plan_revert` that carries a `draft_id` or `planning_run_id` column is
swept for rows keyed to the scratch ids (26 tables: intake_consult_drafts,
intake_financials_drafts, intake_people_capability_drafts, intake_sim_runs,
intake_target_market_drafts, issue_occurrences, issue_resolution_events,
planning_run_checkpoints, planning_runs, planning_stage_events, post_intake_cohort_bands,
post_intake_fitted_bands, post_intake_handler_traces, post_intake_restructuring_log,
post_intake_run_diagnostics, run_vitals_events, run_vitals_gpt_calls, run_vitals_runs,
run_vitals_turns, supervisor_actions, workbook_deliveries, writing_phase_brief_log,
writing_phase_bundle, writing_phase_fact_misses, writing_phase_leaf_orphans,
writing_phase_section_corpus). Prior scratch cleanups (the CW-031/033 clone runners) deleted
only the intake_consult_drafts row because their clones never ran; a draft that RAN leaves rows
in the run tables, so the sweep is the same doctrine carried to every table that keys on the
draft or the run. `post_intake_gpt_response_store` is keyed by `input_hash` only (no draft/run
column, 0 rows mention either id) and `supervisor_actions` had 0 rows for the scratch pair -
nothing to delete in either.

Sweep lesson: 18 of the 19 scratch `run_vitals_gpt_calls` rows carried `planning_run_id = ''`
(calls logged before the run id was stamped); keying the sweep on the run id alone would have
left 18 orphans. Sweep on BOTH keys.

## Deleted - DB rows (88 scratch + 25 zero-turn = 113)
Scratch draft `b9b1be210ae641c3aaa50302a26ac7c7` (client_id vs0f49e2fe673343c99f, created
14:41:02, msgs=125) + run `7457d04b7f844b0fae61a7d8dc1f87d1` (17:48:49 -> 17:55:52):
planning_run_checkpoints 7 (c63ec93e, 56da15ad, 4e59ef41, bcf6343e, 5ceb5e92, 7b4426e9,
158c4962), planning_stage_events 8, post_intake_cohort_bands 12, post_intake_fitted_bands 1,
post_intake_handler_traces 4 (ids 2215-2218), post_intake_restructuring_log 32,
post_intake_run_diagnostics 1, run_vitals_gpt_calls 19, workbook_deliveries 1 (row 64, the
17-55-55.xlsx delivery record), writing_phase_bundle 1 (the scratch bundle v1+v2),
planning_runs 1, intake_consult_drafts 1.

Zero-turn scratch drafts (21), by attributed creator:
- `replay_gate/surface.py` fresh_draft (client_id rgate+hex8; Turn A gate legs 17:56 / 18:12):
  962ec5eb5407452eb8e999ba208a78f4, 5252fbad66264b4da743e1a78a7132f4,
  26ec0bd274434efb824e0aeed444d1aa, 0b8e7f54df1043f083ea4692338f1654
  + the persona watcher's attach-to-latest noise on two of them: run_vitals_runs 2 (ids 257 +
  the 5252fbad row) and run_vitals_events 2 (ids 451, 457, watch_end_max_wait) - their
  transcript_path pointed at OTHER drafts' transcripts (b9b1be21's, f2ed3d01's).
- `Test Files/_redproof_cw026_forward_move.py` create_draft (client_id rp26+hex8; Turn B pins
  18:53): 50b5fcf4, 67ab7110, 7cf4e87b, 859ecdda, b83f0fa9, c14c65ea, c3ce1423, 080aafe4,
  395b5498, 983fc784, cc61cebe, f3988bbf, 9ba4f504, 60594c10 (full ids in
  deleted_paths_and_rows.txt).
- `Test Files/run_intake_bypass.py` `_check_api` - a readiness probe that POSTs
  /api/intake-consult/session and discards the answer, so every bypass canary launch mints one
  throwaway draft one second before the canary draft: 0972f98d134341128a1bbfb39471085c
  (13:03:20 -> bb793dbb 13:03:21), d06a9f3e18054188afe023d6ebbebc12 (16:48:00 -> 482b870f
  16:48:01), efac5b2559894b719d62db59c0f24808 (17:05:29 -> 1b7eeb63 17:05:30).

## Deleted - files (25) + 1 emptied directory
- C:\dev\Cilient Plans\Marchetti Fen -- 09-09-2026 17-55-55.xlsx (283,000 B, sha 9f21714d52f7eaae)
- C:\Users\IgnatiusHenry\OneDrive - Tithe Financial Wealth Management\Apps\Business Plan Generator Sources\Client Plans\Financial Models\Marchetti Fen -- 09-09-2026 17-55-55.xlsx (same bytes)
- C:\dev\Client Written Plans\_v2_runs\marchetti_fen\Marchetti & Fen -- FAILED DRAFT (CLAUDE v2).docx (711,854 B)
- ...\Marchetti & Fen -- FAILED DRAFT (CLAUDE v2).docx.render_report.json
- ...\marchetti_fen_bundle_v1.json, marchetti_fen_bundle_v2.json, marchetti_fen_qa_report.json,
  marchetti_fen_render_data.json (17:56:10), marchetti_fen_claude_plan.json,
  marchetti_fen_claude_raw.json (18:01:58), marchetti_fen_claude_plan_edited.json,
  marchetti_fen_claude_raw_edited.json (18:06:12), marchetti_fen_claude_plan_final.json (18:06:16)
- ...\charts_claude\ (12 files, all 18:06: capacity_vs_plan_y1, cash_and_debt_quarterly,
  competitor_size_bands, cvp_year1, headcount_payroll, industry_establishments_history,
  marketing_customers, revenue_by_line, revenue_ebitda_net_income, wage_positioning .png +
  figures_report.json, sizes.json) - the directory, created by the live run at 15:54:30 and
  holding only scratch output, removed once empty.
- auto_run.log TRIMMED, not deleted: 44 lines -> 22 (the live block, auto-trigger 3201a64c run
  210a4b72, 15:4x-15:54, kept verbatim; the scratch block from line 24 dropped). Full copy in
  the snapshot.

Failure-email record: NONE exists. `_report_outcome` in scripts/writing_phase_v2_run.py shells
to scripts/notify_push_email.py, which is fire-and-forget SMTP - no table, no file. The only
traces were auto_run.log lines 27/43 (the dropped scratch block) and the email in Nick's inbox
(off-limits, untouched). Nothing in workbook_email.py / delivery changed.

## Snapshot (untracked, like R3's _r3_repair_snapshots)
`C:\dev\business_plann_app\_r3b_cleanup_snapshots\` - 43 files, 12 MB: `db\` 17 JSON dumps
(one per table per class, full rows) + `files\` the 25 deleted files in their original folder
layout + `auto_run.log.FULL`.

## Kept - and proven unmoved (20 digests equal before/after, fresh connection)
Live draft 3201a64c row, run 210a4b72 + its checkpoints, workbook_deliveries row 61, the live
writing_phase_bundle row (run 210a4b72, 15:44:59), Northwind 3c2224e1, both live workbooks
`Marchetti Fen -- 09-09-2026 15-44-39.xlsx` (Cilient Plans + OneDrive, sha 91156c5c4a6879ff),
the live delivered docx `Marchetti & Fen -- Business Plan (CLAUDE v2, edited).docx` (15:54:31,
691,456 B, sha 1a77921fe12b5959) + its render_report, issue 571's occurrence rows, and every
STAY draft below.

## STAY - not deleted, listed for Nick
- fc61585db30f4d7c8ea1fdb9ed4f7929 (14:27:35, 3 turns all HTTP 500), 8da24f3818e948c1b203ceecccab28d8
  (14:30:17, 1 turn HTTP 500), 583c6fa511734edd9c3515846702c886 (14:36:44, msgs=1, HTTP 200):
  NOT the 5252fbad shape - these are the Cowork persona's Start-consultation attempts before the
  live Marchetti conversation (14:41), and fc61585d carries issue_occurrences 710/711 for
  issue 571 `raw_python_nameerror_surfaced_to_client_on_consultation_start` (blocker, hard_break,
  status OPEN, 2 occurrences 14:28-14:30, no resolution event). Deleting them would delete a
  filed blocker's evidence. Left in place.
- Canary drafts bb793dbb / 176d4279 / 482b870f / 1b7eeb63 + their runs; Turn B live smoke
  aa3ee853 / f2ed3d01 (client_id bp+hex, `_mint_draft_offline` shape) - not zero-turn, not named.
- OneDrive `Apps\Test Runs\09-09-2026 -- b9b1be210ae641c3aaa50302a26ac7c7.txt` (43,610 B, the
  persona watcher's backfilled transcript for the scratch draft; same byte size as the live
  3201a64c transcript) - not named in the ruling; listed, left.

## Recoverability of the LIVE run's overwritten intermediates (report, nothing rebuilt)
- On disk: LOST. Client Written Plans is not a git repo; no OneDrive copy of any Marchetti
  docx exists (only the two Financial Models xlsx). The scratch run overwrote every
  `_v2_runs\marchetti_fen` intermediate at 17:56-18:06; those scratch versions are now in the
  snapshot, the live 15:44-15:54 versions never were anywhere else.
- DB holds the live bundle: `writing_phase_bundle` row (planning_run_id 210a4b72, draft
  3201a64c, bundle_version 2, `bundle_json` + `v1_json`, created 15:44:59) - bundle v1 and v2
  are recoverable verbatim. The live QA findings survive as the two `QA:` lines in the kept
  auto_run.log block (payroll_gap 420,588 vs stated 678,000; Year-1 EBITDA margin 65.4% outside
  18-32%); render_data (marketing periods) is derivable from the draft's marketing_model_json.
- DB does NOT hold the live Claude writer/editor judgments (claude_plan / raw / edited / final):
  the v2 runner writes only `writing_phase_bundle` (REPLACE INTO, line 57); the
  `post_intake_gpt_response_store` holds the SYSTEM run's GPT calls (rows 15:38:37-15:44:55)
  and nothing from 15:45-15:55; `writing_phase_brief_log` has 0 rows for either draft. The
  edited prose survives only inside the delivered docx (text, not the JSON plan). Charts are
  re-renderable from the DB bundle via render_charts.py - not done.

## The :5050 spender (one line, no action)
The scheduled \BusinessPlanApp-Supervisor rerun ladder (scripts/run_supervisor.py) - attempt 3 on
Sunny c8a6b6b5, completed 19:59, its two 19:59 Sunny workbooks are the ladder's normal output and
STAY; one :5050 listener now, untouched this turn (no app code, no restart owed).

## Observations (not fixes)
1. `_check_api` mints a real draft on every bypass canary launch - a permanent one-shadow-per-
   canary leak. Not a deal breaker (no client number, no delivered plan); a GET health probe
   would do. Nick's triage.
2. Issue 571 (blocker, OPEN, 14:28-14:30) - the very next Start at 14:36 (583c6fa5) returned
   200 and the live Marchetti intake began at 14:41; something changed between 14:30 and 14:36
   (a backend restart from the 14:23 interactive session is the likely candidate). Not this
   turn's scope; flagged for the standing auto-investigate law.
3. The persona watcher attaches to the latest draft and files run_vitals rows against pin-made
   scratch drafts with transcript paths belonging to other drafts (the two deleted rows).
