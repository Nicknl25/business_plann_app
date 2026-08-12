# VS → Cowork-mini

## U04 DIAGNOSIS (42-leg prove: 41/42, U04 green-on-base)

U04's capacity-echo fixture is vacuous on 909f66f: the SMALL-FIG
RESTATEMENT SKIP (which predates the mover) already suppressed
capacity echoes before any receipt could fire - so old code is
correctly silent there and the leg can't red. The LIVE Fernhill no-op
receipts came from the PEOPLE DOOR and REVENUE DOOR echoes ([86]
"Recorded: total team payroll $621,000", [88] "Recorded: current
revenue $1,497,000"). Fix shape: U04's fixture = a people-door echo -
recorded router patch {people.total_team_payroll: 621000} with
current_payroll already 621,000 - old receipts (RED), new silent
(GREEN). VS's P5 got the same fixture update AND the door receipt now
obeys the no-op rule (rider #4 extended - the door previously
receipted echoes even on current code; that gap is closed in the same
commit). Baseline for the door-echo red: any commit before the
extension lands (13fae7c works).

## R23 FIXTURE UPDATE NEEDED (universal-engine phase 4, held for Nick)

Phase 4 (flat retirement) turns R23 red - NOT an app regression, a
transitional fixture: R23's ops stores week=185 beside period=2 and
asserts the mover re-lands the spoken "one hundred and eighty-five."
Under the engine that fixture shape is UNREPRESENTABLE (weekly cadence
derives period:=week at every pass), and with the stamp's deeper
placed-check a restatement of an already-true row value correctly
lands nothing. The leg's real target (the word-number parse + genuine
correction attribution) survives: fix = store week/period = 100 in the
fixture so 185 is a GENUINE correction; the parse assert (185 present,
85 absent) is unchanged. VS's X7 got the same fixture update
(_redproof_cw028.py). Do not land this until Nick clears the phase-4
stop-and-surface.

## UNIVERSAL ENGINE legs (phases land as they ship; baseline `909f66f`
## unless noted). Reference suites: `Test Files/_redproof_phase1_capacity.py`
## (P1-P8, 0/8 on 909f66f -> 8/8)

- **U01 capacity-derivation-invariant** (P1+P2+P8): canonical-per-
  cadence via `_derive_capacity_cells` - weekly per:=week; non-weekly
  week derives per*periods/52; adopt-once for mirror-only legacy rows;
  ALL products. RED on 909f66f (function absent / weekly-only rule).
- **U02 fernhill-round-trip** (P3 - the PERSISTENCE property leg):
  completed-state, contract cadence per=45/week=80, "Capacity, 80."
  patchless-router turn, then **the caller-reference persist**
  (`append_messages(operating_model_json=<the ops object the harness
  passed in>)`) - THE live clobber mechanism; without that second
  persist the leg is vacuously green on old code. Assert SQL read-back
  period==80 and the gate's conflict no longer fires. RED on 909f66f
  with the exact evidence "period = 45.0 - the landing did not
  survive".
- **U03 product-pattern-total** (P4): "4 x 20 = 80... that is the
  capacity number" lands 80 never 20. RED on 909f66f ("capacity 20").
- **U04 no-op-never-receipts** (P5): an echo write (already 80) ships
  no "Recorded:". RED on 909f66f.
- **U05 pin-escalation** (P6): three same-sig holds -> three DISTINCT
  messages, the third offering the direct set. RED on 909f66f (operand
  message repeats verbatim).


## YES on the second freeze leg (Nick approved)

Pin BOTH stages of the freeze class, not just the dead-end wording:

- **R01 (existing)**: the dead-end wording stage — baseline `5b5ffbb`
  (the turn ROUTES but bounces the attribution back to the client),
  fixed by `ff1da19`. Keep as-is.
- **R15 (add)**: the no-router-replay stage — baseline `c3d83a9`
  (the completed-financials early return: a correction turn made ZERO
  router calls and the gate replayed the wall verbatim), fixed by
  `7bcf307`. Leg shape: same completed-state fixture, a correction
  message with a RecordedRouter door patch
  (`{"people.total_team_payroll": 120000}`), assert BOTH:
  (a) the router double was CALLED at least once
      (`len(spy.calls) >= 1` — on c3d83a9 the early return means zero
      calls), and
  (b) the stored `current_payroll` moved to 120,000.
  On `c3d83a9` both fail (no routing, no landing) → RED; on `7bcf307`
  and later → GREEN. Suggested registry row:
  `Leg("R15", "REGRESSION", "completed-financials-no-routing",
       "a correction turn cannot return before the router runs",
       "7bcf307", "c3d83a9", _r_freeze_norouting, issue="CW-025 rank-1")`

One caveat from the fix history: on `c3d83a9` the *stage-flow* people
door already existed — the bug was ONLY at the completed state (no
active stage). The leg must assert the completed state
(`_next_financials_stage(fin) is None`) before running, which your
surface assertion already enforces.

## Proof-table run #1 (2026-08-11, current build ff1da19)

```
leg   bug                              baseline  on base     on now   proof
R01   completed-financials-freeze      5b5ffbb   RED         GREEN    PROVEN
R02   payroll-correction-lands         5b5ffbb   RED         GREEN    PROVEN
R03   sumac-revert                     5b5ffbb   RED         GREEN    PROVEN
R04   crew-double-count                7b9f481   RED         GREEN    PROVEN
R05   capex-zero                       7b9f481   RED         GREEN    PROVEN
R06   price-ratchet                    7b9f481   RED         GREEN    PROVEN
R07   ask-then-ignore                  7b9f481   RED         RED      QUARANTINE
R08   cogs-basis-ratio-stamp           eb7529b   RED         GREEN    PROVEN
R09   owner-comp-one-door              66cc26b   RED         GREEN    PROVEN
R10   role-wage-rollup-recompute       000edda   RED         GREEN    PROVEN
R11   cedar-double-correction          582cef7   RED         GREEN    PROVEN
R12   rest-inclusion-tripwire          7bcf307   RED         GREEN    PROVEN
I01   forward-move:price               5b5ffbb   RED         GREEN    PROVEN
I02   forward-move:payroll             5b5ffbb   RED         GREEN    PROVEN
I03   forward-move:cogs                5b5ffbb   RED         GREEN    PROVEN
I04   forward-move:volume              5b5ffbb   RED         GREEN    PROVEN
I05   forward-move:marketing           5b5ffbb   RED         GREEN    PROVEN
I06   forward-move:AMBIGUOUS/garbage   5b5ffbb   RED         GREEN    PROVEN
I07   ack-matches-stored               7bcf307   RED         GREEN    PROVEN
I08   owner-appears-once               66cc26b   RED         GREEN    PROVEN
I09   no-double-counted-people         7b9f481   RED         RED      QUARANTINE
I11   price-ceiling-no-ratchet         7b9f481   RED         GREEN    PROVEN
20/22 proven   (live tier not proved in this pass: R13, R14, I10)
```

## VS verdicts on the two quarantines — BOTH ARE LEG BUGS, no
## regression in ff1da19. Fix shapes:

**R07 (ask-then-ignore)**: the leg's "mismatch" fixture is the wrong
shape. `_acceptance_mismatch_hold` is the CW-024 #117 guard for an
acceptance whose own words CONTRADICT the proposal ("I don't spend
anything like that today, but fine, use it" -> returns the hold; VS
verified live on the current build). The leg's "Yes let's do that, the
$40,000 one." is a figure-quoting acceptance - a different concern this
guard never covered, on any commit (on 7b9f481 the function didn't
exist, so the leg was red-on-base for the wrong reason). Fix: use the
contradiction phrasing, e.g.
  mismatch: "I don't spend anything like that today, but fine, use it."
  clean:    "Yes, that works."
Also pass a real stage_name ("cogs" or "marketing") - the topic line
comes from it.

**I09 (no-double-counted-people)**: the ASSERTION is broken by an
in-place mutation. `_sync_financials_consult_persistence_state` MUTATES
the passed people dict (that's the dedupe working: the group row is
removed from `people` itself). The leg computes `named`/`ceiling` from
that same dict AFTER the sync, so on a CORRECT build the ceiling
collapses to exactly the rollup (evidence: rollup 196,000 == "naive"
196,000 - that 196,000 IS the deduped 60k + 136k) and
`rollup < ceiling - 1` can never pass. Fix: snapshot the fixture BEFORE
the sync and compute the naive ceiling from the snapshot:
  before = copy.deepcopy(CEDAR_PEOPLE_PHANTOM)
  ... run sync on `people` ...
  named = sum(wages in before["people"]); rest = before[...rest...]
  ceiling = named + rest        # 332,000 for this fixture
  ok = rollup < ceiling - 1.0   # 196,000 < 331,999 -> GREEN on fix
On 7b9f481 (no dedupe) rollup = 332,000 -> RED. Also delete the dead
first `ok = ...` line (line 145) that the second assignment overwrites.

After both fixes, VS will re-prove R07 + I09 and update this table.

## Four new legs to register (Nick-approved rulings, shipped after
## ff1da19 — baseline for all four is `ff1da19`, fix commit is the
## rulings commit that follows it)

Reference red-proofs (copy the fixture + assertion shapes from):
`Test Files/_redproof_cw026_rulings.py` (Q1-Q9; 2/9 on ff1da19 — Q2/Q4
are the named invariants — 9/9 on the fix).

- **R16 inclusion-resolver-references**: `_rest_inclusion_resolve` with
  the ACTUAL Sumac frame {stated 99000, named_sum 37000, remainder
  62000} and the verbatim confirmation ("Yes, Rosalie's $37,000 is
  inside that $99,000. So $62,000 for the other two is right.") →
  62,000. On ff1da19: figs[0] returns 37,000 → RED. (Q1)
- **R17 cogs-echo-guard**: `_normalize_financials_router_patch` with a
  ratio-stamped fin, patch `{financials.current_cogs: 26250}`, the
  anchor ONLY in last_assistant, acceptance prose as user_message →
  cogs_basis stays "ratio". On ff1da19 → "dollars" → RED. Pair with the
  invariant leg: client-stated "$30,000 a year" still tags dollars. (Q3/Q4)
- **I12 owner-row-uniqueness**: the ACTUAL Sumac duplicate (Delia
  34,000 client_override + bare "Owner" 33,999.96) through
  `_sync_financials_consult_persistence_state` → exactly ONE owner row,
  rollup 108,000 (was 141,999.96). On ff1da19 → two rows → RED. Also
  the conflict shape: two DIFFERENT override wages → one row +
  `_owner_wage_conflict_hold` stamped. (Q5/Q6/Q7)
## CW-027 legs (one-shot fixes, baseline `18f5ca5`)

Reference red-proofs: `Test Files/_redproof_cw027.py` (W1-W4; 1/4 on
18f5ca5 - W2 is the named invariant - 4/4 on the fix).

- **R18 rejected-figure-reference**: the verbatim Wren [67] line
  ("...Nowhere near $28,000.") at the marketing stage with the real
  proposal as last_assistant and a recorded router landing
  marketing_total_year1=4800 → marketing lands 4,800, current_cogs
  STAYS 99,840, reply contains no "$28,000" capture. On 18f5ca5 the
  forward-move infers current_cogs=28,000 → RED. (W1; pair the W2
  invariant: a bundled STATEMENT figure still moves.)
- **R19 retention-consumed**: a live retention_pending frame
  {retained_used: 1.0} + the verbatim Wren [97] answer through
  `_parse_retention_answer` + `section.apply_retention_answer` →
  utilization 0.78→0.702, revenue scales, frame CLEARED. On 18f5ca5
  neither function exists (the frame sat unconsumed into the build) →
  RED. (W3; pair W4: bare figures are not retention answers.)

## HARDENING (VS, 2026-08-11 late): baseline integrity check needed

The first full pass after R20-R24 reported 37/37 - but the af791ec
worktree was PARTIAL (the 18:17 index.lock crash interrupted its
`checkout -f -- python`; `realism_memo.py` was missing), so the five
new legs' baseline reds were IMPORT CRASHES, not behavior - rc=1
either way, invisible to the exit-code check. `ensure_baseline`'s
marker test (intake_consult.py exists) passes a partial tree.

Fix for prove.py: after materializing a baseline, run a completeness
probe in a clean subprocess - `python -c "import api_handlers.
intake_consult"` with the root's python first on sys.path - and treat
failure as `baseline unavailable` (quarantine), never as RED. VS
re-materialized af791ec and re-proved R20-R24: 5/5, all behavioral
(R22's red names every moved sibling field).

## SEVEN NEVER-RED LEGS (first trustworthy pass, 2026-08-11 night)

With all baselines rebuilt LOCALLY and probe-verified (both modules),
30/37 proved behaviorally. Seven went GREEN-ON-BASE - they never
reproduced their bug on a complete tree; their earlier reds were
import crashes: **R02, R05, R06, I02, I07, I08, I11**.

For each: diagnose leg-vs-app the way you did R07/I09. The APP fixes
are separately proven (VS's Test Files suites use the stash protocol
against the real repo tree - e.g. payroll 0/8 on 5b5ffbb, twice), so
these are LEG problems. VS's leading hypothesis for the 5b5ffbb pair
(R02/I02): entry-state drift - the fixture builds with the BASELINE's
stage machinery and may leave a stage active on older commits, so the
correction lands through the stage-flow door (which existed at
5b5ffbb) instead of the broken completed-state path. Check the
fixture asserts `_next_financials_stage(fin) is None` under the
ROOT's own code, and mirror VS's Test Files fixtures (which do go red
on those baselines). I07/I08/I11/R05/R06: likely stage/fixture drift
of the same family against their older baselines.

Also for the record: all eleven bad trees traced to ONE origin - they
were created from your remote session (/sessions/... mounts, locked
worktrees, slow-mount checkout timeouts, absolute paths breaking
local repair). Baselines must be materialized on the machine that
runs the prove. The registry is clean now; prove rebuilds locally.

## CW-028 legs (Alder & Vine, baseline `af791ec`)

Reference red-proofs: `Test Files/_redproof_cw028.py` (X1-X9; 0/9 on
af791ec, 9/9 on the fix - X5's fixture must keep the stored capacity
CLEAN pre-capture or the restatement skip makes old code vacuously
green; X6 is the positive invariant Nick required).

- **R20 capacity-twin-invariant**: weekly cadence => period twin
  derives from the weekly value at the canonical pass (X1: 2 -> 185
  through `_sync_financials_consult_persistence_state`).
- **R21 reconciliation-loop-pin**: the anchor-vs-ops hold can never
  re-issue verbatim - the repeat exposes its stored operands (X2:
  two identical-signature holds through `gate_and_turn`; second
  message differs and shows the drivers).
- **R22 sibling-figure-references**: the reference-vs-statement law's
  self-attribution forms - ratio-twin-of-landed (X3, the verbatim
  [55]), arithmetic-of-landed (X4, the verbatim [81]),
  count-of-persons (X5, the verbatim [85]) - PLUS the positive
  invariant X6 (real capacity statements still capture 40, both
  phrasings). All four asserts belong to one leg.
- **R23 compound-word-numbers**: "one hundred and eighty-five
  checkouts" -> figures contain 185 never 85, and the mover
  attributes capacity 185 (X7).
- **R24 owner-never-third-party** (copy leg, VS's call per Nick):
  `_build_rest_of_team_payroll_question` never names an owner-titled
  row alongside "yourself" (X8) - guards the CW-024 double-count
  invitation. Cheap, deterministic, no stored-state cut.
- **(fold into R22 or I07)**: X9 repair receipt - an extra applied
  non-stage field is always named in the ack.

- **I13 owner-draw-clears**: `section._owner_draw_exit_tail` with
  cause {staffed 30000, phasable 0} + wall {payroll_to_clear 122500} →
  offers $7,708/mo (not $10,208); zero-case (staffed 130000) → NO
  "draw at or below" in the tail, revenue named. On ff1da19 the
  function doesn't exist → RED. The invariant in words: the offered
  draw ACTUALLY clears the wall, and an unreachable exit is never
  offered. (Q8/Q9)

## WS1/WS2 legs (per-line COGS + confidence gate + retention door, baseline = the commit BEFORE this one)

Reference proofs: scratchpad `_ws1b_engine_smoke.py` (10 checks),
`_ws1b_intake_smoke.py` (9 checks), `_ws1b_thistledown_fixture.py`
(RED on baseline: one blended 52% for the two-line bike shop; GREEN:
per-line 52%/22% + copy names both lines), `_retention_probe.py`
(RED on baseline: price lands, no frame, 85% ignored; GREEN: frame
stamped, question rides receipt, utilization 0.72->0.612).

- **R26 per-line-cogs-sigma-invariant** (THE invariant leg): on any
  model_input_json whose revenue slots carry `driver="COGS %"` rows,
  for EVERY period index: Sigma(line_rev x line_pct) equals
  total_rev x blend_row_value within 0.5% (line_rev = Capacity x
  Unit Price x Utilization at that index; blend row =
  expenses::Cost of Goods Sold). And finmo cogs equals the Sigma.
  Structural absence on single-line drafts: NO COGS % rows exist and
  the serialized model_input_json is byte-identical to baseline
  (the non-negotiable floor: FINMO_SHA/MODEL_INPUT_SHA of a rerun of
  a clean single-line draft must match across old/new code - proven
  live on Sunny 6feac758).
- **R27 per-line-lockstep**: writing `expenses::Cost of Goods Sold`
  (set_simple_driver or raw-JSON apply through
  apply_derived_driver_policies_to_model_input) scales every line
  percent by ONE multiplier (same ratio to 1e-12) and the Sigma
  matches the new blend. No per-line solver levers exist
  (COGS % rows are controller_write=False,
  derived_driver="per_line_cogs_source").
- **R28 per-line-proposal-fixture** (Thistledown #138): a two-line
  ops model through `_compute_cogs_baseline` returns cogs_per_line
  (one entry per line, retail pct > service pct) and
  `_build_cogs_baseline_message` names each line with its own band,
  blend as arithmetic, collapse invited. Baseline: no cogs_per_line,
  single blended proposal.
- **R29 line-split-confidence-gate** (WS1a): consultant chat-turn
  patch schema carries line_split_confidence/split_rationale
  (structural absence on baseline); recorded fixtures: obvious
  single -> confident_single + no split question; goods+servicing ->
  confident_multi + split proposed INSIDE the restatement + collapse
  invited; "treat them as one" -> collapses without pushback.
- **R30 price-change-stamps-retention** (WS2): ANY door that changes
  a product unit_price stamps `retention_pending`
  (retained_used=1.0) - proven at the edit_patch door
  (`_changed_product_prices` + stamp after
  `_reconcile_driver_correction`) and the forward-move door. The
  existing any-surface consumer then scales utilization on the
  answer. Baseline: the probe's exact turns leave
  retention_pending=False and utilization unmoved.

## R31/R26 GOLDEN-SHA boundary — EXACTLY what the c77094a proof hashed

Mini: the byte-identity proof is now COMMITTED and reproducible at
`Test Files/_prove_single_line_byte_floor.py` (full protocol in its
docstring). The two SHAs in the c77094a commit message hashed the
PERSISTED PRODUCTION ARTIFACTS, not a dataclass round-trip and not
the workbook file:

- Source row: the latest `planning_run_checkpoints` row (created_at
  DESC) WHERE finmo_json IS NOT NULL, for the LATEST planning run of
  draft 6feac758 (Sunny, single-line) - in a clean run that is the
  post_intake_finalize_validation_completed checkpoint.
- MODEL_INPUT_SHA d7cc7683... = sha256 of
  json.dumps(json.loads(checkpoint.model_input_json),
  sort_keys=True, separators=(",", ":")) - i.e. the persisted output
  of build_python_model_input_json ->
  apply_derived_driver_policies_to_model_input -> solver
  applications. NOT FinancialModelInputs.to_model_input_json(). If
  R31 currently hashes to_model_input_json() after a round-trip,
  that is a DIFFERENT (also real, dataclass-serializer) boundary -
  keep it if you want, but the GOLDEN floor line must hash the
  persisted column exactly as above or the two will drift
  independently of my proof.
- FINMO_SHA 9549d3a9... = the same canonicalization of
  checkpoint.finmo_json (the build_python_finmo_json output:
  quarter_rows etc.). It does NOT cover the workbook.
- THE WORKBOOK IS NOT BYTE-HASHABLE (.xlsx zip metadata/timestamps
  differ every export). finmo_sheet.py's 45 changed lines are
  covered structurally today (single-line: exactly one plain
  "Cost of Goods Sold" P&L row, formula shape
  =<revenue cell>*<Model Inputs cogs cell>; multi-line: one
  "Cost of Goods Sold - <line>" row per line + total =SUM over
  them - see Test Files/_ws1b_multiline_e2e.py section (4)). If you
  want a GOLDEN hash for the workbook surface, hash the FORMULA
  GRID: for each sheet, (row label, column) -> formula STRING,
  serialized sorted - that is deterministic across exports and
  catches formula regressions the JSON hashes cannot.

Also committed for reproducibility: _ws1b_engine_smoke.py (10
checks), _ws1b_intake_smoke.py (9 checks),
_ws1b_thistledown_fixture.py (R28's fixture),
_ws2_retention_probe.py (R30's probe), _ws1b_multiline_e2e.py
(R26's SIGMA==blend==finmo E2E + workbook structure).

## Shakedown audit (_prove_20260812_ws1ws2_shakedown.txt, build 50da8fe)

41 behavioural + 5 structural-absence, 0 DRIFT. R28 + R30 PROVEN
clean on first contact. The 15 baseline re-checkouts were the
expected workbook-package repair, not an error. Per-leg diagnoses
for the four quarantined:

- **R26 (RED on current = LEG ASSERTION WRONG-WAY, app is correct)**:
  the leg moved a LINE row's percent and expected COGS to respond.
  On the current build the engine moved -0.00 BY DESIGN: COGS % rows
  are controller_write=False/derived - a raw line-row edit is not a
  sanctioned write, and apply_derived_driver_policies_to_model_input
  reconciles lines BACK to the blend (the blend is the ONE lever;
  lines follow it, never lead it). That snap-back is R27's lockstep
  working, not a dead read. Re-fixture R26 as the EQUALITY invariant
  it was spec'd as: build a per-line-ACTIVE payload through the
  production door (ops product rows carrying
  cogs_percent_of_line_revenue -> build_python_model_input_json, or
  clone the plcogs43 checkpoint) and assert
  Sigma(line_rev x line_pct) == total_rev x blend == finmo cogs per
  period. For a RESPONSE probe, move the BLEND
  (expenses::Cost of Goods Sold) and assert the lines scale and the
  Sigma tracks - never move a derived line row and expect COGS to
  follow.
- **R29 (current build: both fields present=True - only the vocab
  probe misses)**: it found only 'unsure'. The source carries all
  three tokens in THREE places: the chat-turn patch schema enum
  (intake_consultant.py ~line 490s: ["confident_single",
  "confident_multi", "unsure", None]), the _final_schema enum
  (~line 157), and the gate prompt (~lines 270-274). Point the
  vocabulary probe at the chat-turn schema enum (or a plain source
  grep of intake_consultant.py) - whatever artifact it scans today
  is a subset that happens to contain only 'unsure'.
- **R31 (UNEARNED both sides: fixture gap, mini's predicted trap at
  a different door)**: build_python_model_input_json raised
  forecast_starting_ppe_missing - the fixture's financials_json has
  no initial_assets. Fix: give the fixture financials
  "initial_assets": <any positive number> OR pass
  forecast_starting_ppe explicitly (VS's committed floor script and
  smokes pass forecast_starting_ppe / draft-real financials). Same
  payload works on 9d2c41c - both sides then hash.
- **R32 (SETUP: builder entry point - mini's guesses were both
  wrong)**: the real entry is
  client_statements_output_excel.workbook_builder.
  build_client_financial_model_workbook(data: DraftWorkbookData)
  -> openpyxl Workbook (no draft-id variant at build level; the
  draft-id wrapper is export_client_workbook.
  export_workbook_for_draft_id, which SAVES to disk - use the
  builder, not the exporter, for an in-memory grid hash).
  DraftWorkbookData comes from
  client_statements_output_excel.data.draft_data_from_row(row) -
  feed it a draft-shaped dict carrying model_input_json /
  finmo_json / payroll etc. Then hash (sheet, row-label, column) ->
  formula string, sorted.
