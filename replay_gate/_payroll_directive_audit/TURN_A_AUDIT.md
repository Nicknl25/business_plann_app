# mini audit of payroll-directive Turn A (f7ae3d3) - 2026-09-09

Tier audited: spot-check (declared = actual). Every instrument below was rerun by
mini in a fresh session; outputs are in this folder.

## Confirmed on my own instruments
- replay_people_doors_turnA.txt: door A (THE RECALC on the turn-79 roster) -> both
  partners survive, current_payroll 820,000, hold None. Door B3 (guarded people.people
  door -> THE RECALC on the same turn) -> both survive, 820,000. A2 (plain "Design
  Director") unchanged at 820,000.
- Test Files/_redproof_payroll_owner_uniqueness_per_human.py: 6/6.
- Test Files/_redproof_cw026_rulings.py: 9/9 (Sumac unnamed shape Q5/Q6 still merges;
  Q7 same-person two-override hold still raised).
- replay_gate prove --only I12,I08: both RED on ff1da19, GREEN now, PROVEN.
- census_owner_rows_turnA.txt + addendum: since 08-26 exactly ONE draft holds two named
  owner-titled rows - the scratch b9b1be21 (Rasheed 142,000 + Ottoline 155,000). Before
  the fix the count was zero (census_owner_rows.txt).
- Workbook C:\dev\Cilient Plans\Marchetti Fen -- 09-09-2026 17-55-55.xlsx read with
  openpyxl: Checks!B2 = OK (formula =IF(COUNTIF(I7:I236,"FAIL")=0,"OK","FAIL")). Payroll
  Schedule rows 27-38 Design Director and Co-Owner (142,000 Q1-Q4, 146,260 Q5..), rows
  40-46 Principal Architect and Co-Owner (155,000 Q1-Q4, 159,650 Q5..), rows 94-95 the two
  Named person rows, both present in all 20 quarters.
- Checkpoint 158c4962 model_input_json -> derived_driver_runtime["expenses::Payroll"]
  .payroll_headcount: 100 rows, Q1 = 2 key_person + 3 supporting; named Q1 pool 297,000,
  supporting Q1 pool 523,320.3; rest_of_team_anchor applied (factor 1.5082, stated
  523,000, before 346,775). Both partners key_person in 20/20 quarters.
- planning_runs 7457d04b: completed, post_intake_finalize_validation_completed,
  trigger system_run, plan_confidence high_no_adaptation. One :5050 listener, pid 33824.
- Live 3201a64c untouched: one owner row, 678,000, updated_at 15:44 (before the fix).

## Tier call: honest
The changed code is the body of an existing `if len(_owner_rows) > 1` branch inside
THE RECALC. Shapes that flow through it: same-name duplicates (P3), unnamed+named
(Sumac, P4/Q5/Q6/Q7), unnamed-only, two named people (P1/P2/P6), two named + unnamed
(P5). No shared builder/engine change. Spot-check stands.

## Forward consequence VS did NOT check (the finding)
VS's plan named three downstream readers (anchor, payroll builder key_people_rows, the
conflict-hold gate question). It did not name `_sync_owner_pay_one_home`, which runs
in the SAME function two statements later and takes the FIRST owner-regex row as "the
owner", mirroring its wage into financials.owner_compensation. With one owner that was
by construction; with two surviving owners it is roster-order:

    Ottoline first (turn-79 order): owner_compensation 12,916.67/mo -> SDE add-back 38,750/qtr
    Rasheed first (scratch order after the guarded door): 11,833.33/mo -> 35,500/qtr
    true owner pay for the two co-owners: 74,250/qtr

Readers that put that figure in the DELIVERED plan:
- client_statements_output_excel/valuation_sheet.py:_owner_compensation -> Valuation
  sheet row 27 "Seller's discretionary earnings (SDE) = EBITDA + $35,500/qtr owner pay"
  in the scratch workbook (the live single-owner workbook says $38,750/qtr). Terminal
  value, PV and the sensitivity grid all flow from it.
- python/writing_phase_v2/derived.py:113 sde_y = 12 * owner_compensation + ...
- intake_coherence/evaluator.py:414 (non-additive when an owner is in roles - fine).
Pre-existing for pre-08-26 two-owner drafts (Anderson & Blake, 200 drafts); hidden
since 08-26 because the pass deleted the second owner. Turn A makes it the guided path
again for every co-owner business. Triage: a delivered number that depends on list
order and names one of two owners as "owner pay" = wrong/mislabelled figure in a real
client's plan -> deal-breaker class, but the CORRECT definition (all co-owners' pay
added back, or one operator's pay with the rest at market) is a valuation ruling, not
mine - needs-ruling R4 before a Turn C.

## Footprint of the forward proof (for Nick's cleanup ruling R3b)
- scratch draft b9b1be21 (client_id vs0f49e2fe673343c99f, "Marchetti & Fen", status
  in_progress) in intake_consult_drafts; run 7457d04b + checkpoint 158c4962.
- workbook delivered to BOTH C:\dev\Cilient Plans\ and the OneDrive Client Plans\
  Financial Models\ folder (17-55-55.xlsx beside the live 15-44-39.xlsx).
- the system run auto-triggered writing-phase v2 (Claude, writer 347 s + editor 254 s,
  FINAL: FAIL on one vocabulary finding, FAILED DRAFT docx rendered, outcome email
  sent) and it wrote into the SAME slug folder as the live run
  (C:\dev\Client Written Plans\_v2_runs\marchetti_fen\): the live 15:44 run's bundle
  and plan JSONs were overwritten by the scratch run's. The 15:54 edited docx in
  Client Written Plans\ survives. The persona watcher backfilled a transcript for it.
- Writing-phase QA note on the scratch run: "payroll_gap model Year-1 payroll 1,000,788
  vs stated total wages 820,000" - that is 820,000 x 1.22 (taxes & benefits), a QA
  label comparing loaded cost to wages; writing phase is frozen, noted only.

## VS declared-vs-actual
Plan (watcher.log 44401-44404) vs actual: scope, tier, pins, prove legs, scratch
system run, backend restart all match. Two mechanics divergences: (1) VS's RESULT says
the concurrent session's stash "is left in place" - `git stash list` is empty (the
stash is gone; the committed diff is what I audited, so no scope impact); (2) the plan
did not declare that a system run auto-triggers writing-phase v2 and delivers into the
client folders - the proof spent a Claude writing run and overwrote the live slug
folder. Neither changes the fix.
