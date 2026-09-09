# Payroll directive, Turn A: owner-row uniqueness is per human (VS, 2026-09-09)

Fix: `python/api_handlers/intake_consult.py`, THE RECALC
(`_sync_financials_consult_persistence_state`), the CW-026 ruling #1
owner-row uniqueness pass. It now groups owner-titled rows by normalized
full name; an unnamed owner-titled row merges into the (most complete)
named owner row; two DIFFERENT named people whose titles both match the
owner regex are two people - both kept, both in the rollup, no
`_owner_wage_conflict_hold`. Deal breaker prevented: a named partner
(Rasheed Fennimore, Rajan Mehta) deleted from the plan and their wage
dropped from the delivered payroll.

## 1. Red on base, green on the fix (Test Files/_redproof_payroll_owner_uniqueness_per_human.py)

Base = the committed tree at 533310c (fix stashed by the prior VS session):

```
     P1 roster after: ['Ottoline Marchetti'] current_payroll=678,000.00 hold={'kept': 155000.0, 'other': 142000.0}
FAIL P1 Marchetti turn-79 roster: both partners survive, 820,000, no hold
     P2 roster after: ['Elena Vasquez'] current_payroll=650,000.00
FAIL P2 Northwind two co-founders: both survive, 852,210, no hold
PASS P3 same human under two owner titles (name normalized) -> one row at the override
PASS P4 Sumac unnamed owner row vs one named owner -> merges (CW-026 #1 intact)
     P5 roster after: ['Ottoline Marchetti'] current_payroll=155,000.00 hold={'kept': 155000.0, 'other': 142000.0}
FAIL P5 unnamed owner row vs TWO named owners -> merges into one, neither named person deleted
FAIL P6 two different partners with different override wages -> no conflict hold
2/6 passed
```

Fix applied:

```
     P1 roster after: ['Ottoline Marchetti', 'Rasheed Fennimore'] current_payroll=820,000.00 hold=None
PASS P1 Marchetti turn-79 roster: both partners survive, 820,000, no hold
     P2 roster after: ['Elena Vasquez', 'Rajan Mehta'] current_payroll=852,210.00
PASS P2 Northwind two co-founders: both survive, 852,210, no hold
PASS P3 same human under two owner titles (name normalized) -> one row at the override
PASS P4 Sumac unnamed owner row vs one named owner -> merges (CW-026 #1 intact)
     P5 roster after: ['Ottoline Marchetti', 'Rasheed Fennimore'] current_payroll=297,000.00 hold=None
PASS P5 unnamed owner row vs TWO named owners -> merges into one, neither named person deleted
PASS P6 two different partners with different override wages -> no conflict hold
6/6 passed
```

Existing pins: `Test Files/_redproof_cw026_rulings.py` 9/9 (Q5/Q6/Q7 = the
Sumac unnamed-duplicate shapes still collapse to one row; Q7 still holds
on two different override wages for the SAME person).

## 2. Golden floor (replay_gate\gate.bat --prove --only I12,I08)

```
leg   bug                              baseline  on base     on now   proof
I08   owner-appears-once               ff1da19   RED         GREEN    PROVEN
I12   owner-row-uniqueness             ff1da19   RED         GREEN    PROVEN
COUNT   2 proven BEHAVIOURALLY
GREEN - every known issue is clear.
```

## 3. Forward proof: scratch copy of Marchetti 3201a64c through the real system run

Backend restarted after the edit (start_persona_backend.ps1, pid 33824,
ONE :5050 listener). Script: the session scratchpad
`marchetti_forward_proof.py` - copies the live row to a NEW draft_id (the
live draft is untouched), restores Rasheed through the guarded
`people.people` door from
`replay_gate/_payroll_directive_audit/marchetti_turn79_finalize_people.json`,
runs THE RECALC, persists, POSTs `/api/intake-consult/system-run`.

```
1. scratch draft: b9b1be210ae641c3aaa50302a26ac7c7 copied from 3201a64c637f47beb9f9583262874351
   stored roster BEFORE: [('Ottoline Marchetti', 'Principal Architect and Co-Owner', 155000.0)] current_payroll: 678000.0 rest: 523000 hold: None
2. after guarded door (people.people=[Rasheed]): [('Rasheed Fennimore', 'Design Director and Co-Owner', 142000), ('Ottoline Marchetti', 'Principal Architect and Co-Owner', 155000.0)]
3. after THE RECALC: [('Rasheed Fennimore', ...142000), ('Ottoline Marchetti', ...155000.0)] current_payroll: 820000.0 hold: None
4. persisted roster: both, current_payroll: 820000.0 hold: None
5. POST system-run ... http 200 in 433 s  "System run complete."
   workbook: C:\dev\Cilient Plans\Marchetti Fen -- 09-09-2026 17-55-55.xlsx
```

(The script's own step-6 read said NO CHECKPOINT PAYLOAD: its MySQL
connection had opened a REPEATABLE-READ transaction before the run, the
same trap as the pollers-need-autocommit finding. A fresh connection reads
the run.)

Fresh read of the DB after the run:

```
planning_runs: 7457d04b run_status=completed stage=post_intake_finalize_validation_completed
checkpoint 158c4962 (model_input_json present)
draft.model_input_json payroll_headcount: rows 100 named 40 supporting 60
   named Q1 rows: [('Computer and Information Systems Managers', 1.0, 142000), ('', 1.0, 155000)]
   named Q1 pool: 297000   supporting Q1 pool: 523320
   anchor stamp: {'stated_rest_of_team_payroll_year1': 523000.0, 'q1_supporting_pool_before': 346775.0,
                  'applied': True, 'anchor_disposition': 'applied', 'factor': 1.5082, 'q1_supporting_pool_after': 523320.3}
```

Delivered workbook, Payroll Schedule sheet (openpyxl, data_only):

```
Checks!B2 = OK
  27: Design Director and Co-Owner | Named person
  34: Annual Wage | Q1..Q4 142000, Q5.. 146260
  40: Principal Architect and Co-Owner | Named person
  46: Annual Wage | Q1..Q4 155000, Q5.. 159650
  94: 1 | Named person | Design Director and Co-Owner | 1 FTE | 142000
  95: 1 | Named person | Principal Architect and Co-Owner | 1 FTE | 155000
  96: 1 | Staffed role | Architects, Except Landscape | 3.02 FTE | 76760
  97: 1 | Staffed role | Architectural and Civil Drafters | 2.26 FTE | 61990
  ... both named rows present in every quarter 1..20
```

Named Q1 pool 297,000 = 142,000 + 155,000. The anchor applied to the
supporting rows only (523,320 against the stated 523,000). The payroll
payload and the delivered workbook carry both named people.

## Not done (by design)

- The LIVE Marchetti draft 3201a64c still stores one owner row and
  current_payroll 678,000. Repairing stored data is Nick's ruling (R3).
- The scratch draft b9b1be21 (business "Marchetti & Fen", client_id
  vs0f49e2fe67...) and its workbook remain; nothing else references them.
- Observation, not a fix: the Rasheed named row was OEWS-matched to
  "Computer and Information Systems Managers" for a Design Director
  (payload `oews_occ_title`); the wage is the client's 142,000 either way.
