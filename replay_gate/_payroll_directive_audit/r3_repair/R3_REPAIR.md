# R3 DATA REPAIR (VS, 2026-09-09 20:17, item 2 of Nick's payroll rulings)

Nick: "Repair the stored data on both. I don't want a plan generated off either
while they're wrong." Data surgery only: no app code, no legs, no system run,
no writing-phase trigger. Both live rows repaired through the guarded
`people.people` door (`_apply_scoped_patch` -> `_merge_people_rows`) and THE
RECALC (`_sync_financials_consult_persistence_state`) run IN-PROCESS - a pure
function on dicts; :5050 was never called, `planning_runs` is unchanged on both.

Files here:
- `r3_repair_DRYRUN.txt` - the same path on deep copies, nothing written.
- `r3_repair_WRITE.txt` - the persisted run: BEFORE rows verbatim, incoming
  row verbatim, guard report, PEOPLE_PATCH trace, in-memory AFTER, the UPDATE,
  fresh-connection readback, column digests before/after, planning_runs.
- `*_BEFORE_touched_columns.json` / `*_AFTER_touched_columns.json` - the five
  JSON columns the recalc can touch, both drafts (only two moved).
- `vs_r3_repair.py` (the instrument), `vs_verify_columns.py` (98-column compare).
- `_gate_only_R31_R32_20260909_r3_repair.txt` - the standing floor, GREEN 2/2.
- Full 98-column pre-surgery snapshots: `C:\dev\business_plann_app\_r3_repair_snapshots\`
  (untracked, gitignored, 5.4 MB) - the reversal recipe if one is ever needed.

## Marchetti & Fen 3201a64c637f47beb9f9583262874351

```
BEFORE: roster=[('Ottoline Marchetti', 'Principal Architect and Co-Owner', 155000.0, 'client_override')] rest_of_team_payroll_year1=523000 current_payroll=678000.0 payroll_total_year1=678000.0 owner_compensation=12916.67 _owner_wage_conflict_hold=None _payroll_fold_hold=None payroll_stated_total_target=None
incoming: Rasheed Fennimore / Design Director and Co-Owner / 142000 / client_override  (source: marchetti_turn79_finalize_people.json, {{fact:business.name}} rendered as the stored rows are)
door proof (single row, NOT persisted): PEOPLE_PATCH incoming=1 restored=['Ottoline Marchetti'] field_kept=[]
persisted write (full roster, original order) guard report: {"incoming": 2, "restored": [], "field_kept": [], "merged": ["Ottoline Marchetti"]}
AFTER (fresh-connection readback): roster=[('Ottoline Marchetti', 'Principal Architect and Co-Owner', 155000.0, 'client_override'), ('Rasheed Fennimore', 'Design Director and Co-Owner', 142000, 'client_override')] rest_of_team_payroll_year1=523000 current_payroll=820000.0 payroll_total_year1=820000.0 owner_compensation=12916.67 _owner_wage_conflict_hold=None _payroll_fold_hold=None payroll_stated_total_target=None
_owner_wage_conflict_hold: not present, nothing to clear   (the live row never stored it - Turn A's pin reproduced it on a replay, not from the DB)
digests: people_json b13f4dbad207 -> 2f1d1d7917d7, financials_json fe45c9fe997c -> b61155021646; financials_year1_json a967eba0a690, marketing_model_json 3efa8542935c, operating_model_json 9fe715a3974b unchanged
planning_runs: [('210a4b72', 'completed', '2026-09-09 15:38:10')] before and after
```

## Northwind Systems, Inc. 3c2224e10ddc4d8e947c73fe5a75b21a

```
BEFORE: roster=[('Elena Vasquez', 'Co-Founder and CEO', 650000.0, 'client_override')] rest_of_team_payroll_year1=51350000 current_payroll=52000000.0 payroll_total_year1=52000000.0 owner_compensation=54166.67 _owner_wage_conflict_hold={'kept': 650000.0, 'other': 202210.0} _payroll_fold_hold={'unapplied': 202210.0} payroll_stated_total_target=None
incoming: Rajan Mehta / Co-Founder and CTO / 202210.0 / client_override  (source: post_intake_gpt_response_store input_hash 63cc005b20fd, 2026-08-29 05:20:43 - the finalize whose Elena row matches the stored row field for field; its Rajan row carried annual_wage null / wage_source unknown, the 202,210 is the OEWS figure the client accepted at turn 65, and client_override is the source the deleted row carried: the conflict hold is raised ONLY between two client_override rows)
door proof (single row, NOT persisted): PEOPLE_PATCH incoming=1 restored=['Elena Vasquez'] field_kept=[]
persisted write (full roster, original order) guard report: {"incoming": 2, "restored": [], "field_kept": [], "merged": ["Elena Vasquez"]}
AFTER recalc: current_payroll 52202210.0, _owner_wage_conflict_hold still {'kept': 650000.0, 'other': 202210.0} - THE RECALC only writes this key, never clears it
clearing stale _owner_wage_conflict_hold: {'kept': 650000.0, 'other': 202210.0}
AFTER (fresh-connection readback): roster=[('Elena Vasquez', 'Co-Founder and CEO', 650000.0, 'client_override'), ('Rajan Mehta', 'Co-Founder and CTO', 202210.0, 'client_override')] rest_of_team_payroll_year1=51350000 current_payroll=52202210.0 payroll_total_year1=52202210.0 owner_compensation=54166.67 _owner_wage_conflict_hold=None _payroll_fold_hold={'unapplied': 202210.0} payroll_stated_total_target=None
digests: people_json a7dedd6ff726 -> 74196dc08f1b, financials_json 06492b77d2d9 -> 99bdbaefea0a; financials_year1_json 5cc057331b8d, marketing_model_json 6aa9ed32c6e1, operating_model_json 4eb89d511ff0 unchanged
planning_runs: [] before and after
```

## Forward checks

- 98-column compare against the pre-surgery snapshot, both rows: moved =
  `['people_json', 'financials_json']` only (`vs_verify_columns.py`).
- `updated_at` did NOT bump on either row (no ON UPDATE clause on the column).
- mini's census (`mini_census_owner_rows.py`, rerun 20:18): drafts carrying
  `_owner_wage_conflict_hold` 105 -> 104 (Northwind's), drafts holding >=2
  owner-regex rows 203 -> 205 (both repaired drafts).
- Gate `--only R31,R32` GREEN 2/2 (no code changed; the standing floor).

## Findings (not fixes - for mini and Nick)

1. NORTHWIND'S STATED TOTAL IS 202,210 SHORT OF ITS OWN ROSTER. Turn 67: "The
   rest of our payroll, beyond the two co-founders, amounts to about $51.35
   million per year. That brings total Year-1 payroll to roughly $52 million,
   given the $650,000 for my compensation." The client's arithmetic omits
   Rajan. The stored `_payroll_fold_hold {unapplied: 202210}` was written by
   the fold on 08-29 when the 52,000,000 target met the 852,210 + 51,350,000
   roster; the deletion then made the total land at exactly 52,000,000 by
   accident. After the repair the hold is a TRUE residual again, so it was
   LEFT IN PLACE - Turn B's reader re-asks once on the next edit turn. Nick's
   ruling named only the conflict hold; say if the fold hold should go too.
2. WRITE ORDER. `_merge_people_rows` emits incoming rows first, standing rows
   after. A single-row restore would have persisted [Rasheed, Ottoline] /
   [Rajan, Elena] and the order-dependent `owner_compensation` mirror (R4,
   item 7) would have flipped to the second partner's pay (11,833.33 /
   16,850.83 - the DRYRUN file shows it). The persisted write therefore sent
   the FULL roster in its original order through the same door: the mirror
   did not move (12,916.67 / 54,166.67), and the delivered SDE add-back reads
   what it read before the deletion until item 7 redefines it as the sum.
3. MARCHETTI'S LIVE RUN ARTIFACTS ARE STILL WRONG. planning_run 210a4b72
   (15:38-15:44 today), its checkpoint model_input and the delivered
   `Marchetti Fen -- 09-09-2026 15-44-39.xlsx` carry the one-owner 678,000
   payroll. The stored draft is now right; those artifacts are replaced only
   by a re-run, which waits on item 4 (freeze real).
4. THE RECALC CANNOT RETIRE THE CONFLICT HOLD. One writer
   (intake_consult.py ~9543), one popper (intake_coherence/section.py ~2203,
   the client's answer at the gate). Once the cause is gone (two humans, not
   one) nothing clears it - the repair popped it by hand. Small class, worth
   a line in R1's turn.
5. `_coherence.eval` re-derived with the 820,000 payroll on Marchetti (q11
   ebitda 547,651 -> 512,151, payroll_share 0.3229 -> 0.3905, 18 leaves
   listed verbatim in the WRITE log) - the recalc's own derived twins.
