# Payroll-directive audit, mini turn 1 (2026-09-09)

Scope: commits 9c06f7a (people write guard + false-receipt class) and 13b0f9d
(rest-of-team anchor), audited with my own instruments (every script in this
directory is runnable from the repo root with .venv python; all read-only).

## Verdict: progress. Two deal-breakers are still live after the fixes.

### F1 - the Marchetti deletion door is NOT the door VS guarded
- Evidence: replay_people_doors.txt (mini_replay_people_doors.py), marchetti_messages.txt,
  marchetti_turn79_finalize_people.json, census_owner_rows.txt.
- Timeline from the DB (run_vitals_turns + post_intake_gpt_response_store):
  turn 79 finalize (hash 945be2e191b7) returns BOTH partners - Ottoline
  "Principal Architect and Co-Owner" $155,000 and Rasheed "Design Director and
  Co-Owner" $142,000. Turn 81 router (f1cfc0d83cea): confirm_proceed, patch [].
  Turn 83 router (76d4d4c8c51c): patch = people.rest_of_team_payroll_year1 only.
  NO people.people key ever reached the scoped door. By turn 85 Rasheed is gone.
- The door: THE RECALC (_sync_financials_consult_persistence_state) OWNER-ROW
  UNIQUENESS pass, intake_consult.py ~9469-9515, CW-026 ruling #1.
  _OWNER_TITLE_RE = owner|principal|founder|managing|partner. Both partners
  match; the pass keeps the most complete row and DELETES the other, leaving
  _owner_wage_conflict_hold {kept 155000, other 142000} - which is exactly the
  "two different figures for your pay" the app asked Ottoline at turn 124.
- Replay A: turn-79 roster -> after the pass: Ottoline only, current_payroll
  678,000. Replay A2: Rasheed titled plainly "Design Director" (what the client
  SAID at turn 77) -> both survive, current_payroll 820,000. The finalize model
  appended "and Co-Owner"; the pass then deleted him.
- Replay B/B2: VS's guarded door works on its own terms (Rasheed restored,
  PEOPLE_PATCH fires; remove_role still removes). Replay B3: the guard's output
  meets THE RECALC on the same handler turn -> Rasheed deleted again.
- Class: since 08-26 no draft that reached financials holds two named
  owner-titled rows. Second live instance: Northwind 3c2224e1 (08-29) - Rajan
  Mehta, Co-Founder and CTO, $202,210, deleted; hold {650000, 202210}.
- VS's commit-message causal claim ("deleted by exactly this replace-versus-merge
  shape") is unsupported by the artifacts.

### F2 - the stated-total door confirms a total that did not land (false receipt, post-fix)
- Evidence: canary_door_smoke_state.txt, canary_482b870f_messages.txt, server log
  17:04:52 TURN_INTENT patch={'people.total_team_payroll': 300000}.
- Turn 5 on 482b870f: reply "Got it, your total team payroll is $300,000 a year";
  stored current_payroll 282,042.50; _payroll_fold_hold {unapplied: 17,957.50}.
- _payroll_fold_hold has ONE writer (intake_consult.py:9557) and ZERO readers.
  Sub-ruling (ii) says the remainder is "flagged for the conversation to ask
  HOW" - that half was never built. The hold is silent; the reply confirms.
- VS's commit calls this "receipted and folded with the honest hold".

### Verified (VS's claims that hold)
- Guard door: restores an absent named person, PEOPLE_PATCH trace, remove_role removes.
- Derived-field door: owner_compensation drops WITH a receipt; payroll-total
  redirects to payroll_stated_total_target; receipt_summary never renders the
  transport key (receipt_probes.txt). numeric_receipt on a mixed patch reports
  dropped=[] for the derived twin - the handler's _unsat_derived addition is
  what closes that; read in the diff, not runnable offline.
- Transients: 8,982 drafts - 0 with _derived_patch_receipt, 0 with payroll_stated_total_target.
- Anchor arithmetic (anchor_arith.txt): Marchetti 189,741 -> 522,541 (f 2.7564,
  FTE 2.32 -> 6.39); Ardenwald 745,350 -> 985,946 (f 1.3229, 16.45 -> 21.76);
  four Sunny controls no-move; start+hires=end and forward continuity 0
  violations; named rows untouched by construction (the function receives
  supporting rows only; key_people_rows assembled separately).
- Population (population_sweep.txt): 1,198 stored payloads; 59 movers, every one
  with rot>0 and an "applied" stamp; 1,139 no-pool drafts never move; 0 violations.
- Sunny post-anchor canary 1b7eeb63 payroll payload byte-equal to pre-anchor
  bb793dbb and 176d4279. 482b870f state confirmed from the DB.
- 20 pinned tests pass.

### Notes for Nick (not fix tasks)
- N1 The anchor scales DOWN too: 6 of 59 movers have factor < 1 (Bridgeburn
  0.8663, Ironwood 0.837). Consistent with "the stated pool anchors", but VS's
  plan said capacity physics "never replaces" the base - a down-scale below the
  capacity-authored floor may trip payroll_revenue_feasibility. Ruling.
- N2 enforce_labor_scaling_on_payload runs AFTER the builder (set_payroll_schedule
  ~610) and is up-only on the supporting block: the anchored Q1 pool is a FLOOR,
  not a fixed point. Marchetti's Q1 target (0.19 x revenue) sits below authored,
  so no double-scale there; Ardenwald not verifiable (no trace persisted).
- N3 Other wholesale writers of people_json["people"] (third-path answer): the
  people-stage collection extractor (intake_consult.py:21132, model output
  replaces the list; the prompt promises to keep the baseline) and
  people_capability_finalize (21545 review / 21971 finalize / 17943). No
  deletion observed there in the six runs. Whether the merge discipline extends
  to model wholesale writes is a ruling, not a fix.
- N4 Process: VS's 09-09 turn plan was one line - no BLAST-RADIUS / LOADING /
  VERIFY, no tier declared, while fix 3 changes the shared payroll builder.
  Commit 9c06f7a also carries unrelated files (replay_gate/_cw043_audit/*.json,
  HANDOFF_PAUSE removal).
