# Item 7 / R4 TURN C - SDE add-back = SUM of every owner's pay (VS, 2026-09-10)

Nick: "Add back EVERY owner's pay. SDE is what a single owner-operator would
take out; mirroring whichever row is first is arbitrary and order-dependent,
which is worse than either answer. Nothing touching valuation should depend
on row order."

Deal breaker prevented: a two-owner client's Valuation sheet, docx SDE
(sde_y1..y5) and valuation prose added back ONE owner's pay - whichever row
the merge left first - so SDE, the exit-multiple terminal value, the equity
value and the implied multiple were wrong by the second owner's pay and
flipped with row order.

Commits: 5a64fdf (the fix + pins + evidence), then the R32 re-bless + HANDOFF.

## What changed (app)

| file | change |
|---|---|
| python/client_intake_and_finmo/owner_pay.py (NEW) | the ONE owner-title regex + owner_pay_total / owner_pay_quarterly / owner_compensation_mirror_monthly / owner_rows_annual_sum. A SUM over owner-titled rows with a numeric wage; legacy fallback to the stored monthly mirror x12 when no owner row carries a wage (source reported). |
| client_statements_output_excel/valuation_sheet.py | _owner_compensation reads the people rows through the helper (was financials.owner_compensation x3 = ONE owner). Note: "EBITDA + $X/qtr owner pay (N owners)" when N >= 2; one-owner note byte-identical. |
| python/writing_phase_v2/derived.py | sde_y{y} = owner_pay_total x 1.03^(y-1) + NI + interest + dep + taxes (was 12 x mirror). Same set, same source as the sheet. |
| python/writing_phase/facts/valuation.py | the sheet's Python twin: owner_comp_q from the helper (was mirror x3), so the valuation guard still compares like with like. |
| python/api_handlers/intake_consult.py | (1) `_OWNER_TITLE_RE` aliased from owner_pay (one pattern, no second copy); (2) `_sync_owner_pay_one_home`: mirror = sum of owner rows' annual pay / 12, rollup staleness compared on the owner rows' SUMS (basis vs people) - both order-free; the legacy no-owner-row branch unchanged; (3) `_apply_owner_pay_statement`: the mirror it derives after the statement lands is the same set function. The STATEMENT still lands on the first owner-titled row (see finding F3). |

Diffs: valuation_sheet_r7.diff, writing_phase_r7.diff, intake_consult_r7.diff.

## Pins (tests/test_sde_every_owner.py, 19)

Two-owner sum in both orders (sheet note "EBITDA + $74,250/qtr owner pay (2
owners)", formula +74250.0); one-owner unchanged byte-for-byte (Sumac
48,000 -> "EBITDA + $12,000/qtr owner pay"); legacy fallback (no owner row,
mirror 4,000 -> 12,000/qtr); SINGLE-ROW-PATCH REORDER (same SDE row, same
mirror 24,750.0, same sde_y1..y5 in both orders); derived + fact twin sums;
mirror both writers (sync 24,750 both orders, statement door 202,000/12
after "I pay myself 5,000" on a two-owner roster); one regex identity.

Red-proof (redproof_at_HEAD_ab5256d.txt, scratch worktree at ab5256d):
12 red / 7 green - the sheet quoted `'EBITDA + $35,500/qtr owner pay'`
(Rasheed first) and `'EBITDA + $38,750/qtr owner pay'` (Ottoline first)
against 74,250; the 7 green are the unchanged behaviors (one-owner, legacy
fallback, one-owner mirror both writers, legacy sync materialization).

Floors (floors_pins_after.txt): bare 17 + freeze 10 + people-guard 14 +
people-stage 22 + anchor 11 + new 19 = 93 passed. After the R32 re-bless:
bare 17 + new 19 = 36 passed (pins_bare_mode_after_rebless.txt).

## Neighbor check (vs_r7_neighbors.py + vs_r7_read_neighbors.py)

Workbooks built OFFLINE from the stored rows into the scratchpad (never
Cilient Plans), at HEAD ab5256d (worktree, provenance asserted) and after,
Excel COM full rebuild in a subprocess, read with openpyxl data_only.

| draft | Checks!B2 before / after | SDE note before -> after | SDE Total before -> after | Equity value before -> after |
|---|---|---|---|---|
| Bellweather 46ae584a (one owner 72,000) | FAIL / FAIL (see F1) | 18,000/qtr -> 18,000/qtr | 1,173,867.18 -> same | 561,187.75 -> same |
| Sunny_V3 280a55e1 (one owner 42,000) | OK / OK | 10,500/qtr -> 10,500/qtr | 367,630.32 -> same | 106,389.83 -> same |
| Marchetti 3201a64c LIVE (155,000 + 142,000) | OK / OK | 38,750/qtr -> 74,250/qtr (2 owners) | 8,625,856.56 -> 9,335,856.36 | 6,272,301.85 -> 6,339,727.85 (implied multiple 3.27x -> 3.08x) |

Fact twin (writing_phase.facts.valuation) on the same rows: Bellweather
owner_comp_q 18,000 / Sunny 10,500 unchanged; Marchetti 38,750.01 ->
74,250.0, equity 6,272,362.38 -> 6,339,788.41.

## R32 accounting and re-bless (mini's rule: a move owes the accounting + re-bless in the same push)

r32_grid_leafdiff_HEAD_vs_after.txt (python -m replay_gate._grid_dump
<HEAD worktree> .): 9,664 formula cells, EXACTLY 20 CHANGED, 0 added, 0
removed - the Valuation SDE row, one per quarter, `='FINMO'!D16+0.0` ->
`='FINMO'!D16+25055.0`. The frozen CareCompanions fixture (89e5a622) carries
one owner row (Mark Davis, Founder and CEO, 100,220 oews_median) and an
EMPTY mirror (financials.owner_compensation 0) - at HEAD its SDE added back
NOTHING; 100,220 / 4 = 25,055. R31 unmoved (model_input 39bf63043f72, finmo
bcd8fce31066). Block edit: R32 at 4f06f6d -> 5a64fdf, a7d2ebcd7f89 ->
d33750bcb640, plus the proof_note history line - the one sanctioned edit
(precedent bd83cce). gate_R31_R32_before_R32_rebless_RED.txt (R32 moved) ->
gate_R31_R32_after_R32_rebless.txt (GREEN 2/2).

## Every reader of financials.owner_compensation - disposition

| reader | disposition |
|---|---|
| intake_consult.py 2852 | comment only (the financials stage was removed) - unchanged |
| intake_consult.py 8886 | _apply_scoped_patch DROPS a patch write to the mirror (derived_dropped receipt) - unchanged |
| intake_consult.py 14480 | the people.owner_pay_monthly door -> _apply_owner_pay_statement; the statement's landing row unchanged (F3), the mirror it derives = set sum |
| intake_consult.py 17010 | a field-name tuple - unchanged |
| intake_consult.py 17180-17262 | THE mirror (_sync_owner_pay_one_home) - MOVED to the order-independent set function (sum / 12), staleness on sums |
| capture_receipt.py 44 | numeric-receipt label ("total owner pay", per month) - unchanged; NOT a client-statement echo (the echo is the door ack "Recorded: owner pay $X a month" at 10246, which reads the stated value and is unchanged). The label already said TOTAL; on a two-owner roster it now renders the total instead of one owner's pay |
| fact_templates.py 144/178 | field-name sets for extraction/sanitize - unchanged |
| field_basis.py 5/39 | comments + basis table (owner_pay_monthly MONTHLY) - unchanged |
| finmo_break_even.py 317 | the flag owner_compensation_in_payroll=True - unchanged |
| intake_coherence/evaluator.py 414 | owner_comp_annual = mirror x12, additive ONLY when no owner sits in the basis roles (0 otherwise); code unchanged, the note value now = total owner pay (its own name) |
| intake_coherence/section.py 53 | comment - unchanged |
| intake_submission.py 146 | submission field whitelist - unchanged |
| intent_router.py 1644 | comment in the people scope list - unchanged |
| post_intake_initial_grid/runner.py 1129 | cash-judgment stated fact "owner_compensation" (GPT input at system-run time) - code unchanged; on a two-owner draft it now receives the TOTAL owner draw (F6) |
| balance_sheet_driver_validation.py 365 | sample expense-base seed - code unchanged; the seed carries the total on two-owner drafts (a validation scale, not a delivered figure) |
| writing_phase/facts/valuation.py 124 | MOVED to the sum (the sheet's twin) |
| writing_phase/leaves.py 179 | leaf assignment of /owner_compensation to Staffing via the formatter - unchanged; no writing-phase formatter reads the key by name |
| writing_phase_v2/derived.py 113 | MOVED to the sum |
| client_statements_output_excel/valuation_sheet.py | MOVED to the sum (people rows), note carries the owner count |
| replay_gate/legs.py 510-528 | the one-door structural leg (owner_compensation must not be a stage) - mini's, unchanged |

## Findings (not fixes)

- F1 Bellweather 46ae584a Checks!B2 = FAIL at HEAD and after, byte-identical:
  the single FAIL row is "Workbook Completeness / Marketing Schedule could
  not be built" (198 status rows, 197 OK) - the 08-17 draft carries no
  marketing schedule payload, which the check text itself calls expected for
  drafts built before the schedule existed. Not this fix; not clean either.
- F2 fact twin vs recalculated sheet equity differ slightly and identically
  before/after: Marchetti 60.56, Bellweather 260.65, Sunny 16.28 - pre-
  existing, inside whatever the valuation guard tolerates; observation.
- F3 the owner-pay STATEMENT door ("I pay myself X") still lands on the
  FIRST owner-titled row; on a two-owner roster which human is speaking is a
  design question (the client's own name? the primary owner by an explicit
  rule?) - NOT built; needs Nick. The mirror it derives is now order-free.
- F4 one-owner businesses whose annual wage is not a multiple of 12 move by
  at most one cent per quarter (the mirror's cent rounding no longer round-
  trips: Marchetti's HEAD fact twin read 38,750.01). Sumac, Bellweather and
  Sunny are exact.
- F5 the CareCompanions class: an owner row present but an EMPTY mirror
  (0/None) added back NOTHING at HEAD. The R32 fixture is one; the live
  population of that class was not counted this turn (mini: census).
- F6 the post-intake readers that keep the mirror's name (cash judgment
  stated fact, balance-sheet seed, evaluator note) now see the TOTAL on
  two-owner drafts. No two-owner system run this turn (freeze FROZEN, no
  canary) - the forward proof is item 8's Cowork run.
- F7 two PRE-EXISTING copies of the owner pattern outside this turn's files:
  intake_coherence/controller.py 326 (_OWNER_TITLE_RE_CTL) and
  evaluator.py 417 (inline). Not written by this turn; a one-line alias each
  when a turn touches those files.

## Process

- Backend: :5050 restarted via scripts/start_persona_backend.ps1 at
  00:17:39 (stale 24564 killed, launcher 1304, ONE listener PID 37228, log
  _logs_persona_20260910_001739.txt). Freeze readback FROZEN exit 3
  (freeze_status.txt). No system run, no writing-phase trigger, nothing
  written to any live row (the neighbor rows were SELECTed only).
- In-process Excel COM after the MySQL connector + openpyxl build died with
  an access violation (bash and PowerShell alike; the standalone recipe
  runs, both Dispatch and gencache); the recalc moved to a subprocess.
- One scratch worktree at ab5256d created for the red-proof and the
  before-build, removed at the end of the turn.
