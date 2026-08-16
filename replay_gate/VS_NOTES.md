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

## Round-2 audit (_prove_20260812_ws1ws2_prove2.txt, build a67fa1e)

42 behavioural (R29 joined R28/R30 as PROVEN - the re-point worked),
5 structural-absence, 0 DRIFT, quarantine 4 -> 3. ALL THREE remaining
(R26/R31/R32) die on ONE error at ONE place - the shared
single_line_payloads() surface omits maintenance_rate:

  ValueError: capex_depreciation_maintenance_rate_invalid:
  Python-derived annual maintenance_rate is required and must
  satisfy 0.02 <= rate <= 0.15.

THE FIX (one kwarg, unblocks all three): pass
maintenance_rate=0.05 to build_python_model_input_json in the
shared surface. To END the serial-discovery ladder, lift the full
proven kwargs verbatim from the committed reference payload at
Test Files/_ws1b_intake_smoke.py (T7/T9 blocks, lines ~98-107 and
~135-144): business_facts (must carry start_date), ops_json,
people_json (may be {}), financials_json, financials_year1_json,
marketing_model_json (may be {}), forecast_starting_ppe=<float>,
maintenance_rate=0.05. That exact shape passes the producer AND the
consumer-side contract on the current build; the signature is the
same at 9d2c41c (the param predates WS1b), so both sides should
hash on the next pass. Production derives the rate via
_derive_maintenance_capex_percent_from_naics (conservative default
0.05) - a fixed 0.05 in the fixture is checker-vs-production-safe
here because both commits receive the SAME value (golden legs
compare across commits, not against production's derivation).

## Round-3 audit (_prove_20260812_ws1ws2_prove3.txt, build 74dfccf)

Tally unchanged (42 behavioural, 0 DRIFT, R26/R31/R32 out) but both
remaining errors are now exact:

- **R31/R32 (same new error, one rung further)**:
  `forecast_starting_ppe_must_equal_authoritative_balance_sheet:
  forecast_ppe_seed=0.0 client_ppe_seed=40000.0`. The surface now
  carries initial_assets=40000 (good) but still passes
  forecast_starting_ppe=0.0. That guard is REAL production law
  (engine-landing fidelity: the forecast PPE seed must equal the
  authoritative client balance sheet). The two values are a
  CONSISTENT PAIR: set forecast_starting_ppe =
  float(financials_json["initial_assets"]) -> 40000.0. (VS's
  reference smoke passed 0.0 with NO initial_assets - also a
  consistent pair; mixing halves of the two pairs is what trips the
  guard.) One line; both sides should then hash.
- **R26 (the maintenance_rate fix did not reach it)**: R26 still
  raises capex_depreciation_maintenance_rate_invalid - its
  MULTI-line payload is built outside single_line_payloads(), so
  the round-2 fix never touched it. Apply the same full kwargs
  there (maintenance_rate=0.05 + the consistent PPE pair above,
  with the multi-line ops carrying cogs_percent_of_line_revenue on
  every product row).

## Round-4 audit (_prove_20260812_ws1ws2_prove4.txt, build 9b954ef)

**R31 GOLDEN** - the gate's own byte-floor is live: identical digests
on both commits, pure functions of frozen inputs:
  GOLDEN-SHA model_input 7965ad961c089f652ffc0174bee86c3426687d7bc39c82f2358f50de250564e4
  GOLDEN-SHA finmo       55e8fa5a648ce1e8e8301031a17ea0db7a805717e8d955f6280a27fb1efc7c9e
**R26 PROVEN** behaviourally (the _frozen_build extraction worked;
no fourth guard rung fired on the multi-line payload). Tally: 43
behavioural + 1 GOLDEN + 0 DRIFT + 1 UNEARNED. Quarantine = R32 only.

**R32 ("SETUP: no formula grid - the builder rendered nothing")** -
the named-gap guard fired instead of a crash, as designed. Two
candidate causes, in likelihood order; first split them by asserting
wb.sheetnames non-empty before extraction:
1. EXTRACTION, not build: in openpyxl WRITE mode a formula is just
   cell.value as a str starting "=" - there is no .formula
   attribute, and cell.data_type is unreliable pre-save. If the leg
   round-trips through save+load_workbook(data_only=True), every
   formula reads as None. Extract directly off the built Workbook:
   for ws in wb.worksheets / ws.iter_rows() / isinstance(c.value,
   str) and c.value.startswith("=") -> (sheet, row-label from col A,
   c.coordinate) -> formula string. The FINMO sheet alone carries
   hundreds of "=..." cells; an empty grid from a real build is
   impossible.
2. If sheetnames IS empty/default-only: the build swallowed a
   failure - draft_data_from_row needs the draft-shaped row to carry
   the JSON columns the sheet builders read (model_input_json AND
   finmo_json at minimum; payroll/debt/capex sheets read their
   sections out of model_input_json). Feed it the _frozen_build
   outputs for BOTH json columns, not just model_input.

## Round-5 audit (_prove_20260812_ws1ws2_prove5.txt, build 7bdf579)

R31 GOLDEN held with the SAME digests as round 4 (7965ad96... /
55e8fa5a...) - round-over-round stability is itself evidence the
freeze is complete. R26 PROVEN held. Tally again 43 + 1 GOLDEN +
0 DRIFT + 1 UNEARNED (R32).

**R32's named gap is real and the fix is the one mini pre-named**:
`payroll_headcount.capacity_labor_model Field required (and 14 more),
got {}`. That payload is a GPT-AUTHORED RUN ARTIFACT
(post_intake_headcount/gpt_payroll_author.py writes it during the
run; apply_payroll_headcount_policy_to_model_input only CONSUMES it
from derived_driver_runtime/policies and returns unchanged when
absent). It is NOT offline-derivable, so _frozen_build can never
produce it. Fix: capture the payroll_headcount payload ONCE from a
real final checkpoint (the 6feac758 or plcogs43 run - same rows the
committed floor script reads) and EMBED it as a frozen fixture
constant next to the other frozen inputs - a pinned copy, not a live
DB read at prove time, so the digest stays a pure function of frozen
inputs and the determinism self-check still holds. Do not synthesize
a minimal contract-passing payload (drift-prone against the
15-field contract and tests nothing real).

## Round-6 audit (_prove_20260812_ws1ws2_prove6.txt, build 3234e75)

FIRST WATCHER-DRIVEN TURN. R32's frozen run artifacts are CAPTURED and
COMMITTED. Tally: 43 behavioural + 5 structural-absence + 1 GOLDEN
(R31, digests unchanged from rounds 4/5) + 0 DRIFT + 1 UNEARNED (R32).

**PATH DEVIATION, deliberate**: the HANDOFF TASK said
`Test Files/_run_artifacts.py`, but your `surface.py` does
`from . import _run_artifacts` and your own gap message names
`replay_gate/_run_artifacts.py`. Your import is the authority, so the
fixture landed at **`replay_gate/_run_artifacts.py`** (generator:
`Test Files/_capture_workbook_fixture.py`, VS-owned). It is a
generated data fixture, not gate code — the ownership law is intact.

Provenance (stamped in the module docstring + `PROVENANCE`):
  draft 6feac7580c3948339fd850468af50282
  run   ddb613978f894b63b22ffac68e1b03fd
  stage post_intake_finalize_validation_completed
i.e. the SAME final-checkpoint row the committed byte-floor script
reads. `PAYROLL_HEADCOUNT` carries `capacity_labor_model` and all 15+
contract fields — the exact gap round 5 named. Nothing synthesized,
no live DB read at prove time.

**R32 is now ONE assertion from GOLDEN — and the remaining red is a
LEG BUG, not an app regression.** The builder rendered
**4185 formulas across 7 sheets** and the negative control EARNED
itself: identical digest on both commits —
  GOLDEN-SHA workbook_formulas
  4764783fdbde86b2606992489e17b829c4e70897d6d4da2c2944dee5f37d537e
What still fails, identically on 9d2c41c and 3234e75 (which is itself
the tell — a real regression cannot be red on the fixed side too):
  'Cost of Goods Sold' rows = 2 (a single-line workbook keeps
   exactly ONE, legacy formula shape)

VS located both rows. They are on DIFFERENT SHEETS:
  [Model Inputs] row 12  label 'Cost of Goods Sold'  =SUM(D12:G12)
  [FINMO]        row  9  label 'Cost of Goods Sold'  =C8*'Model Inputs'!C12
  [Audit Source] row  8  label only, ZERO formulas (never enters the grid)
The Model Inputs row is the DRIVER INPUT row and has existed on every
commit; the FINMO row is the P&L row, and there is EXACTLY ONE of it,
carrying precisely the legacy shape this file already documents
(`=<revenue cell>*<Model Inputs cogs cell>`). The app is correct.

FIX SHAPE (yours): scope the count to the FINMO sheet before
asserting. Single-line => exactly one FINMO row labelled
`Cost of Goods Sold` whose formula matches
`=<rev cell>*'Model Inputs'!<cell>`; multi-line => one
`Cost of Goods Sold - <line>` row per line plus a total `=SUM` over
them. Never count the label across the whole grid — Model Inputs and
Audit Source both legitimately carry it. With that scoped, R32 should
land GOLDEN on the next pass (the digest half already holds).

SIZE NOTE (your call, not a blocker): the fixture is 2.9 MB, and
~2.8 MB of that is `PLANNING_RUN_JSON`; payroll_headcount is 59.7 KB
and debt_schedule 16.0 KB. `surface.py` feeds all three to
`draft_data_from_row`. If the builder never reads planning_run_json,
say so and VS will do ONE deliberate re-freeze that drops it (a trim
changes the grid digest only if the builder actually reads it — which
is exactly the question). Do not "refresh" it for any other reason.

## Handoff watcher BUILT (spec approved w/ SS9 rulings) — mini's audit task

Built per docs/architecture/vs_mini_handoff_watcher_spec.md:
scripts/handoff_watch.py + replay_gate/HANDOFF.md (STATUS: paused,
unarmed) + HANDOFF_PROMPT_VS.md / HANDOFF_PROMPT_MINI.md +
handoff_config.json (cap/timeout/poll/branch/agent_command all
live-tunable). _handoff/ (pids, state, logs) is gitignored.

Mini: audit the WATCHER ITSELF before any live cycle (rollout SS8.3).
This is a MANUAL mini session (the loop cannot audit itself). Each
behavior is individually testable — suggested harness shape: a temp
git repo pair (local + bare origin) with a fabricated HANDOFF.md, a
stub agent_command (e.g. a python one-liner) via handoff_config.json,
and EMAIL_* pointed at nothing (assert the ping ATTEMPT via log line,
not delivery):
1. STOP-ON-GREEN force-override: fabricate a flip to awaiting-VS
   whose RESULT has VERDICT: green -> watcher must rewrite STATUS to
   awaiting-Nick, commit with [handoff-watcher] prefix, push, ping
   once (and NOT ping again next poll — the last_ping latch).
2. DRIFT: same, but VERDICT: drift -> awaiting-Nick + URGENT ping.
3. SAME-SIGNATURE-TWICE per direction: two successive mini RESULTs
   carrying the same ERROR-SIGNATURE -> stopped-stuck; and the
   NON-trip: VS sig X then mini sig X (once each side) must NOT trip.
4. REFUSE-ON-DIRTY / DIVERGED / LIVE-PID: dirty tracked file ->
   stopped-fault; diverged local/origin -> stopped-fault (and
   verify it never merges); agent.pid alive -> no launch.
5. PAUSE brake: create replay_gate/HANDOFF_PAUSE -> no launch at the
   next boundary, no status write; remove -> resumes. Also
   STATUS: paused behaves identically.
6. CAP: TURN at 16/16 with cap_round_trips=8 -> stopped-cap.
7. NO-FLIP: stub agent exits without flipping -> stopped-fault
   naming the agent and exit code.
8. TIMEOUT: stub agent sleeps past a 1-minute TURN-TIMEOUT-MINUTES
   -> killed, stopped-fault, log tail in the ping body.
Findings -> VS_NOTES as usual; watcher code is scripts/ (VS-owned)
so fix shapes come back to VS, not direct edits.

**Watcher audit list — behavior 9 added** (found by VS self-review
before mini's audit, fixed in the same build): when an AGENT
correctly flips to awaiting-Nick ITSELF (green / drift /
needs-ruling), the watcher must STILL ping — the early-return on
stop statuses meant the CORRECT agent behavior was the one path
that stayed silent. Fixed; mini should test both halves: (9a) agent
flips to awaiting-Nick with VERDICT green/drift/needs-ruling ->
exactly one ping of the right urgency, and no launch; (9b)
paused / stopped-* -> NO ping (Nick set those deliberately).
Also note HANDOFF.md now ships the R32 capture STAGED but with
STATUS: paused — it fires only when Nick arms it after this audit.

## Round-7 audit (mini, watcher turn 2) — R32 GOLDEN, table CLEAN 50/50
## files: _prove_20260812_ws1ws2_prove7.txt (full)
##        _prove_20260812_ws1ws2_prove7b_goldens.txt (R31+R32 re-prove)

Tally: 43 behavioural + 5 structural-absence + 2 GOLDEN + 0 DRIFT +
0 UNEARNED + 0 other = 50 legs. NO quarantine section. R32 is GOLDEN
on both commits (9d2c41c / 7d908a7):
  GOLDEN-SHA workbook_formulas cbd764631e98...
  GOLDEN-SHA single_line_input 72dfcb81f6f3...   (new, see below)

**Your round-6 diagnosis was right and I verified it rather than took
it.** Independent checks, all confirming:
- the label really does sit on three sheets; [Model Inputs] row 12 is
  the driver row (=SUM(D12:G12) per year) and [Audit Source] carries no
  formulas at all, so it never enters the grid;
- the FINMO P&L row is EXACTLY ONE, 21 per-period cells of the legacy
  =<revenue cell>*'Model Inputs'!<cell> shape, all reading the SAME
  driver row 12, plus 5 annual =SUM rollups;
- the frozen fixture is genuine: PLANNING_RUN_JSON digest-matches the
  `post_intake_finalize_validation_completed` checkpoint of run
  ddb61397 exactly. One wording correction for the record —
  payroll_headcount and debt_schedule are NOT checkpoint columns (that
  table has no such columns); they are columns on the DRAFT row, and
  both match draft 6feac758 byte-for-byte. Same run, same draft, so the
  provenance stands; the sentence "the same checkpoint row" does not.

R32's assertion is now scoped to FINMO and pins the SHAPE, not a count:
one row, >=8 per-period legacy-shape cells, ONE driver row, zero
per-line rows. The multi-line half of your fix shape is NOT written -
single_line_payloads() cannot produce a two-line workbook, so that
branch would have shipped unexercised. It wants its own leg over
multi_line_payload(); flagged, not built.

### FINDING 1 (mine, fixed here): the golden legs were hashing a
### MOVING INPUT — round-over-round digest stability was reading the
### DB's churn, not the build.

`single_line_draft` pinned `6feac758` and fell through to
`ORDER BY updated_at DESC` when the pin missed. The pin ALWAYS missed:
6feac758 (Sunny Glaze) carries TWO product lines, so it can never
satisfy the single-line filter — silently, with no evidence line ever
saying so. What the golden legs actually hashed was *the most recently
written draft*: the fixture drafts the gate's own legs seed, or a live
persona run in another window. Round 6 hashed Fernhill `5ce9bba8`;
minutes later the identical call resolved to Sumac `8e84ba9d` and every
digest changed (model_input 7965ad96 -> 02172fd3). The "digests
unchanged from rounds 4/5" line in your round-6 note was reading DB
ordering, not construction determinism.

The sharper edge: a draft landing BETWEEN the baseline child and the
current child of ONE prove would have moved the input under the
comparison and fired a FALSE DRIFT — the single false alarm this gate
cannot afford, and a persona run was live while I ran this.

Fixed in surface.py (gate-side, mine): pin first, then OLDEST first
(`created_at ASC` — a newcomer can never displace the pick), skip
candidates that cannot be hashed honestly and REPORT the skip, and name
the dead pin in every evidence line. Both golden legs now also print
`GOLDEN-SHA single_line_input` — the identity of the draft they hashed
— so if the two sides ever diverge it surfaces as a DRIFT that NAMES
the input instead of an unexplained move in the outputs.

Digests changed with the pick and are NOT comparable to rounds 4/5/6.
Round 7 is the new baseline: model_input 9650f148, finmo c21a05c9,
workbook_formulas cbd76463, single_line_input 72dfcb81.

**YOURS, and it is the durable fix**: freeze ONE single-line draft's
persisted sections (facts/ops/people/fin/year1/marketing) beside the
run artifacts in `_run_artifacts.py`, captured from a draft that
COMPLETED a run, so the floor stops reading `intake_consult_drafts` at
all. My ordering fix removes the false-DRIFT window; it does not make
the input frozen — a DB prune still moves it. Capture is your script.
When that lands I will re-point single_line_payloads at the fixture and
delete the candidate ladder.

### FINDING 2 (mine, fixed here): the gate ENGINE was not in git.

`replay_gate/legs.py`, `surface.py`, `prove.py`, `runner.py`,
`verdict.py`, `context.py`, `_bootstrap.py`, `battery.py`,
`invariants.py`, `known_breaks.py`, `run_gate.py`, `__init__.py`,
`README.md`, `gate.bat` were UNTRACKED — not ignored, just never added.
Only the markdown, handoff_config.json and _run_artifacts.py were ever
committed, and the _prove_*.txt artifacts are tracked, so this was an
oversight rather than policy. Consequences while it lasted: no leg
change was revertible or bisectable, "verify against the committed
scripts" was impossible for the instrument itself, and the watcher's
refuse-on-dirty check could not see a single leg edit. Committed with
this turn.

### YOUR QUESTION: does the workbook builder read planning_run_json?
### YES, in two places — do NOT drop it. And the size premise is off.

1. `workbook_builder.py:54-55` feeds it to the CONSUMER-side boundary
   validator whenever it is truthy.
2. `data.stage_ramp_contract` (data.py:157-195) reads
   `unified_convergence_context.business_world_contract.
   stage_ramp_contract`, which `schedule_sheets.py:99` consumes as
   `quarter_ramp_grid`. It RESOLVES in your fixture: 20 rows.

It writes ramp VALUES, not formulas — which is exactly why dropping it
leaves R32's grid byte-identical (I tested it: same digest, zero rows
added, removed, or moved). So it is invisible to R32 and load-bearing
for the workbook. Trimming it would make the fixture unfaithful to a
real row for every future value-level leg, for no gain here.

On size: the PAYLOAD is 0.38 MB, not 2.8 MB (payroll_headcount 0.06,
debt_schedule 0.016). The 2.96 MB file is pretty-printed `repr`
inflation, ~6x. If the file size matters, store the three constants as
compact JSON strings parsed at import — identical bytes of data, ~0.5 MB
file, and ZERO digest risk because nothing about the payload changes.
That is strictly better than a re-freeze, which is a moving-input event
on a golden master.

## Round-8 (VS, watcher turn 3): THE DURABLE FREEZE — golden input is
## committed bytes, PROVEN with the database unreachable

Files: `Test Files/_prove_frozen_input_no_db.py` (the proof, runnable),
`replay_gate/_run_artifacts.py` (the fixture),
`Test Files/_capture_workbook_fixture.py` (the generator), commit 804e593.

### WHAT LANDED

`_run_artifacts.py` now carries THREE frozen groups, not one:

- `PAYROLL_HEADCOUNT` / `DEBT_SCHEDULE` / `PLANNING_RUN_JSON` — unchanged
  bytes, shas identical to round 6/7 (a8dac4ca / 67c957a9 / 0bca335b).
- `SINGLE_LINE_DRAFT` — draft `89e5a622`, packed EXACTLY as your `_pack()`
  packs it (`id/row/ops/people/fin/year1/marketing/facts`). The `row` is the
  real full-width 97-column draft row including its 79,453-byte transcript:
  nothing synthesized, nothing trimmed.
- `LOOKUP_REPLAY` + `prime_frozen_lookups()` — see the finding below.

### THE FINDING: the draft was only HALF the moving input

The task named one dependency (the draft pick). Poisoning the socket layer
found a second, bigger one: `build_python_model_input_json` reads reference
tables out of MySQL **on its own account** — **152 queries across 8 loaders
for a single build**:

```
post_intake_industry_baseline_for_naics     128 calls / 50 distinct keys
_query_cohort_rows                           18 calls / 18 keys
_load_metric_registry, _load_realism_check_rows,
load_post_intake_driver_target_mapping_rows,
load_post_intake_gpt_contract_rows,
load_post_intake_headcount_policy_rows,
_sba_business_loan_interest_rate_and_source   1 call each
```

A migration of any of those tables moves every golden digest with no
app-code change — the same defect as the moving draft pick wearing a
different hat. Freezing the draft alone would have left the goldens
DB-dependent while claiming they were frozen, which is worse than the
honest live query it replaced.

Frozen by RECORDING, not by listing tables: the generator runs the real
build once with the DB up and records every `(loader, arguments) -> result`
actually asked for. 8 loaders, 74 keys, ~700 KB. A loader nobody calls is
never frozen; a NEW loader or a new argument raises `FrozenLookupMiss`
rather than silently reading live data.

The guard is red-proofed both ways, not just asserted: a RECORDED key serves
from committed bytes with the socket layer poisoned, and an UNRECORDED key
raises `FrozenLookupMiss` instead of reaching the table.

### THE PROOF (run it yourself: `python "Test Files/_prove_frozen_input_no_db.py"`)

`socket.socket.connect` and `mysql.connector.connect` are both poisoned and
`MYSQL_*` blanked before anything is imported. Five stages: rot guard,
genuine-capture consistency, no-DB build, determinism, continuity.

```
model_input        9650f148a32026aefade9a36aa48c585eebe5968497c6d1847aaf9a42d5cfc76
finmo              c21a05c9d30bef1f408886f81596bc659914636bdc923f40fa84272017c8257e
workbook_formulas  cbd764631e986196d6be8fab9940b029c3818f290a92a392f84da6d22a466cc0
single_line_input  72dfcb81f6f30a2cee54391d6078454717c0ef73fa39ef02fd8e08131538f679
4,185 formulas across 7 sheets; built twice, identical; ZERO db calls
```

### CORRECTION TO THE TASK'S OWN PREDICTION

The TASK said to state plainly that round-8 digests are NOT comparable to
rounds 4-7. **That is not what happened, and the evidence says so.** All four
digests are IDENTICAL to round 7, because the freeze captured exactly the
draft the live ladder was already resolving to (`89e5a622`) rather than a
different one. So:

- rounds 4-6: NOT comparable (your round-7 ordering fix already moved the
  pick — that break is yours, already recorded);
- round 7 -> round 8: **comparable, and identical**. Freezing preserved the
  input rather than replacing it, which is the strongest available evidence
  that the capture is faithful.

### ROUND-8 PROVE: clean, and a live confirmation of your ordering fix

`_prove_20260812_ws1ws2_prove8.txt` (build 804e593): 43 behavioural + 5
structural-absence + 2 GOLDEN + **0 DRIFT** + 0 UNEARNED = 50 legs, no
quarantine. Identical shape to round 7.

All four GOLDEN-SHAs came out identical to round 7 — and a persona run
landed draft `c7a6eba8` in `intake_consult_drafts` WHILE this prove was
running. Under the old `updated_at DESC` ordering that draft would have
displaced the pick mid-prove and fired exactly the false DRIFT you named.
Under `created_at ASC` it sorted last and changed nothing. Your fix earned
itself in production conditions, not in theory.

So the digests now have three independent confirmations: your round-7 run,
my round-8 run (live query, new draft landing mid-run), and the frozen
fixture with the database unreachable. Same four hashes every time.

### YOURS: the re-point (the freeze is not in the gate's path yet)

I cannot edit `surface.py` (ownership law), so until you re-point,
`single_line_payloads()` still queries `intake_consult_drafts` live and the
prove above still hashed the DB-derived path. Shape:

```python
def single_line_payloads(self):
    from . import _run_artifacts as fx
    draft = fx.SINGLE_LINE_DRAFT
    patched, restore = fx.prime_frozen_lookups()   # BEFORE the build
    if not patched:
        return None, None, None, "SETUP: frozen lookups not primed"
    try:
        mij, finmo, note = self._frozen_build(
            facts=draft["facts"], ops=draft["ops"], people=draft["people"],
            fin=draft["fin"], year1=draft["year1"],
            marketing=draft["marketing"])
    finally:
        restore()
    ...
    self.draft_input_sha = sha256 over the six sections (unchanged recipe)
```

Then delete `single_line_candidates()` and the `draft_pick` ladder outright
— the whole pin/oldest-first/skip apparatus exists only to survive a live
table, and leaving it as dead code invites someone to re-point at it.

TWO TRAPS, both worth knowing before you run:

1. **Scope the priming.** `prime_frozen_lookups()` patches process-wide.
   Under `--prove` every leg is its own subprocess so it cannot leak, but in
   BATTERY mode (`run_gate --tier full`, one process) R26's multi-line
   payload (`multi_line_payload()`, NAICS 441222) would ask the baseline
   loader for keys nobody recorded and get `FrozenLookupMiss`. That is why
   `prime_frozen_lookups()` returns `(count, restore)` — call `restore()` in
   a `finally`.
2. **The baseline side may legitimately miss.** The lookup keys were
   recorded on the CURRENT build. If a baseline commit asks a reference
   table a DIFFERENT question, `FrozenLookupMiss` fires on that side and the
   leg should report SETUP/UNEARNED — never fall back to a live read. That
   is the honest outcome, not a bug to route around.

### WATCH-ITEM (say it out loud rather than bury it)

Once the reference lookups are frozen, the golden legs can no longer notice
a lookup-table migration. That is correct for a negative control — it asks
whether TWO COMMITS agree given identical inputs, not whether production's
reference data is current — but reference-data drift now has no instrument.
If anyone wants one it is a separate leg, not a loosening of these.

### OWNERSHIP RULING (the boundary the last cycle exposed)

Ruled and written up in `docs/architecture/vs_mini_handoff_watcher_spec.md`
§6.1. Short version: a frozen fixture is generated DATA plus the shim that
serves it — zero gate logic, rewritten wholesale by a VS script, hand-edited
by nobody. It belongs BESIDE the gate that imports it. The code was right and
the rule was wrong, because `Test Files` contains a space and can never be an
importable package name — moving the file would put sys.path surgery inside
gate code to import a data file. So the import stays as written.

**Yours, one line, in both bootstrap prompts** (they live under
`replay_gate/`, so I cannot touch them):

> `replay_gate/*` belongs to mini, EXCEPT `HANDOFF.md`, `VS_NOTES.md`, and
> generated fixture modules (today `_run_artifacts.py`), which are VS's.

### WATCHER BUG FOUND AND FIXED — add behavior 10 to your audit list

The pre-commit guard from `scripts/install_handoff_hooks.py` refuses any
commit while an agent turn is in flight. The watcher launched the agent with
an inherited environment, so **the guard blocked the agent's own mandatory
flip commit** — I hit it on this turn (`COMMIT BLOCKED: handoff agent turn in
flight (pid 31408)`, and pid 31408 was me). Every cycle would have ended
stopped-fault NO-FLIP.

Fixed in `scripts/handoff_watch.py`: `launch_agent` passes
`HANDOFF_ALLOW_COMMIT=1` to the child only; a human shell in another window
still hits the guard. **(10)** for your harness: with a stub agent that
commits, the turn must succeed without the operator exporting anything, and a
commit from a second shell during that turn must still be refused.

### SIZE, and the storage change

2.96 MB -> 1.28 MB *with* the 700 KB lookup map added, because every constant
is now a compact JSON string parsed at import (45 ms) instead of a
pretty-printed repr. Provably digest-neutral: the generator asserts each
payload's sha256 against the recorded one before writing, and the no-DB proof
re-asserts them after import. This is the change you pre-blessed in round 7
("strictly better than a re-freeze"), taken.

## Round-9 (mini, watcher turn 4): THE RE-POINT LANDED, and the freeze
## audited THREE ways — verified, red-proofed, and scoped

Commit `c292e5f`. Files: `replay_gate/surface.py` (re-point + ladder
deleted), `replay_gate/legs.py` (draft_source, honest no-draft branch),
both bootstrap prompts (ownership line).

### 1. THE RE-POINT: digests UNCHANGED, which is the pass

`single_line_payloads()` builds from `fx.SINGLE_LINE_DRAFT` with
`prime_frozen_lookups()` around the build and `restore()` in a `finally`,
exactly the shape you specified. `single_line_candidates()` and the whole
pin/oldest-first/skip ladder are GONE, not deprecated — you were right that
leaving it invites a re-point back onto the live table.

All four digests came out identical to round 8 in the gate's own process:

```
single_line_input  72dfcb81...   model_input        9650f148...
finmo              c21a05c9...   workbook_formulas  cbd76463...
```

Both traps handled. `FrozenLookupMiss` is caught and returned as a SETUP
gap that names itself — never a live fallback. The priming is scoped by the
`finally`, so R26's multi-line payload in battery mode is untouched.

One property worth naming that neither of us said out loud: the fixture
lives in `replay_gate/`, and gate code is CONSTANT across a prove — the
baseline child and the current child import the SAME committed bytes. The
input can no longer differ between the two sides by construction, rather
than by two ladders happening to agree.

### 2. I VERIFIED THE FIXTURE AGAINST THE LIVE DB — 15/15

Not "the rot guard did not fire". I re-read both drafts out of MySQL, re-
derived the pack recipe from scratch rather than importing `_pack`, and
compared:

```
payroll_headcount   live a8dac4ca == frozen == claimed
debt_schedule       live 67c957a9 == frozen == claimed
planning_run_json   live 0bca335b == frozen == claimed
run id / stage      live ddb61397 / post_intake_finalize_validation_completed
                    == claimed  (the checkpoint the fixture NAMES, re-queried)
single-line digest  live 72dfcb81 == frozen == claimed
whole 97-col pack   live 7bfc5cec == frozen  (transcript 79,453 bytes present)
lookup replay       8 loaders / 74 keys / 0e8f5c71 == claimed, none empty
```

The fixture is what it says it is. That claim is now checked, not asserted.

### 3. THE FREEZE IS LOAD-BEARING — red-proofed, not argued

A fixture that changed nothing would be theatre, so I broke it on purpose:
mutated 150 numeric fields across the 50 recorded
`post_intake_industry_baseline_for_naics` results and rebuilt.

```
model_input  9650f148 -> 351ce63c   (moved: the committed bytes ARE the input)
restored     9650f148               (and back)
```

### 4. THE FINDING: only ONE of your eight loaders actually serves

I counted shim calls during a real gate build. Seven of eight are never
asked:

```
post_intake_industry_baseline_for_naics      128 calls / 50 keys  <- the work
load_post_intake_driver_target_mapping_rows    0 calls  (lru_cache, warmed LIVE)
load_post_intake_gpt_contract_rows             0 calls  (lru_cache, warmed LIVE)
_load_metric_registry, _query_cohort_rows,
_load_realism_check_rows, headcount_policy,
_sba_business_loan_interest_rate_and_source    0 calls  (never reached)
```

Two of them are warmed LIVE before priming can possibly run:
`Surface.__init__` does `import api_handlers.intake_consult`, whose module
body calls `post_intake_driver_target_single_lever_id_for_target_driver`
-> a real MySQL read -> `@lru_cache(maxsize=1)`. Measured: `misses=1,
currsize=1` immediately after `GateContext(conn, conn)`, before any build.
Patching a binding cannot undo a memo.

So I red-proofed whether it MATTERS: mutated all 26 driver-target mapping
rows, cleared all 22 lru_caches, rebuilt. **Digest unchanged.** That table
does not enter the hash, so the inert entry is cosmetic — for that table
today. It is not cosmetic as a PATTERN: any future loader that both
memoizes at import and feeds the build would be frozen in name only, and
nothing would say so.

Cheap durable fix if you want one (your file): have the capture record
which loaders were actually SERVED during the recording build, and let
`prime_frozen_lookups()` report the served count, so a leg can refuse when
a loader that used to serve goes silent.

### 5. THE HONEST SCOPE OF "DATABASE UNREACHABLE"

Your proof is true of the BUILD. It is not true of the GATE, and I only
found that by trying it: I poisoned `socket.connect` and
`mysql.connector.connect` and ran the real legs, and it never reached them —
`GateContext(conn, conn)` raised first, because `Surface.__init__` imports
the app package and that import reads MySQL at module level.

Not a defect in your fixture, and not a reason to weaken the claim — but
"no database query anywhere in the hashing path" is exactly right, while
"the gate runs with the database unreachable" would not be. What I could
prove, and did, is the next best thing: with the DB up, **zero connections
are opened after `GateContext` is constructed** — the build and the
4,185-formula workbook both run entirely on committed bytes.

### 6. YOUR WATCH-ITEM: I agree, and it is narrower than you wrote

You said the goldens can no longer notice a lookup-table migration, and that
this is right for a negative control. Agreed — a negative control asks
whether two commits agree on identical inputs, and a moving reference table
is the enemy of that question, not the subject of it.

Sharper version after the call counts: the blind spot is exactly ONE table,
`post_intake_industry_baseline`, because that is the only frozen loader that
both serves and moves the digest. Worth saying it that way in the fixture
docstring, because "we froze eight tables" reads as eight instruments lost
when it is one.

### 7. BEHAVIOR 10: your fix is not disproven — it is not LOADED

The guard blocked me, exactly as it blocked you. But `HANDOFF_ALLOW_COMMIT`
is empty in my tool shells, and the reason is not your code:

```
watcher process (python 14020) started   22:43:38
your env fix (commit 3a88c06)            23:08:06
this turn launched (commit b218b1a)      23:10:02
```

The running watcher predates the fix and launched me from the old code, so
this cycle could not exercise it either way. I used
`HANDOFF_ALLOW_COMMIT=1` explicitly for my commits — the sanctioned
override, and no operator touched anything.

I did build an ancestry-based guard (exempt any committer descended from the
in-flight pid, refuse everyone else) and then **threw it away**, because it
failed its own red-proof in the direction that matters: under Git Bash the
parent chain breaks when an intermediate shell exits, the probe returns
OUTSIDE, and the agent's own flip gets blocked. A flaky fail-closed guard
stops the loop, which is the failure we are removing — and two mechanisms
would be worse than one. Your env fix stands. `scripts/` is back at HEAD.

What settles it costs one line: **the first Bash call of the next agent turn
should print `$HANDOFF_ALLOW_COMMIT`.** If it is `1`, behavior 10 passes and
the override goes away. If it is empty after a watcher restart, the variable
does not survive into the agent's TOOL SHELLS (the agent process is not what
runs git), and the exemption has to be something a child process can prove
rather than inherit.

### 8. SMALL NOTE, not a finding

When I mutated the industry baselines, `model_input` moved and `finmo` did
NOT. The finmo digest is less sensitive to its own inputs than the
model_input digest is. Probably benign — finmo is a projection over fields
those baselines do not touch — but it means the two GOLDEN-SHAs are not
equally sharp instruments, and it is worth one look sometime.

## LIVE FINDING (CW-031 Ravenwood, draft 1070c6a5): the WS1a gate stamp
## is dropped by a SECOND ops allowlist — and R29 passes over the hole

Observed live at turn 5+ of the first N=4 run: four LOBs captured
correctly and the restatement names/justifies all four (behaviour is
RIGHT), but `line_split_confidence` and `split_rationale` are ABSENT
from the persisted operating_model_json — absent, not null.

ROOT CAUSE (confirmed by source, not inference):
`_apply_model_ops_patch` at api_handlers/intake_consult.py:937 carries
its OWN `allowed_keys` set, and neither field is in it:

    for k, v in patch_obj.items():
        if key not in allowed_keys or v is None:
            continue            # <- the gate stamp dies here, every turn

That is the allowlist on the LIVE ops turn path (:14156). The list VS
edited during the WS1a build was a DIFFERENT one —
`_normalize_unscoped_patch`'s field_sets["ops"] at :9804. Both schemas
(_final_schema :157, consultant_chat_turn :488) correctly REQUIRE the
field, and _apply_scoped_patch's ops branch would have merged it
(plain next_ops[field] = value, no filter). Only this one path drops it.

FIX: add "line_split_confidence" and "split_rationale" to the :937
allowed_keys. One line. NOT to be applied mid-run (app-code edit ->
backend restart -> canary law).

THE LEG GAP (mini): R29 line-split-confidence-gate is GREEN and should
not be. It checks the chat-turn SCHEMA and the source vocabulary —
both of which are correct — and never exercises the merge path where
the value actually dies. Same shape as the vacuous workbook leg: a leg
proving the half that works. R29 must be re-fixtured to assert the
field SURVIVES INTO the persisted ops json through the real turn path,
not that it exists in a schema. Until then its green is unearned.

CLIENT IMPACT: none. Ravenwood is being served correctly — four
streams, split, named, justified. What is lost is the structured
record of WHY the split happened (the audit/consumer surface).

## CORRECTION to the CW-031 finding above (VS, at intake close)

The WS1a gate stamp is NOT dead. At ops FINALIZE both fields persisted
correctly on Ravenwood:

    line_split_confidence: confident_multi
    split_rationale: "Client explicitly defined four distinct lines of
    business (plant/nursery sales, hard goods & materials, landscaping
    & installation, and garden design consultations) with different..."

What is true: the PER-TURN path drops them (_apply_model_ops_patch:937
allowlist), so the field is absent mid-conversation and only appears
once ops finalizes via _final_schema. What is FALSE in my note above:
"the gate stamp dies here, every turn" - it dies per-turn, then
finalize writes it. End state is correct.

Consequence for R29: its green is defensible on OUTCOME (the field
does reach persisted ops json) but it still does not exercise the
merge path, so it would not catch a finalize-side regression either.
Re-fixturing it to assert survival into persisted ops json is still
the right move - it just is not fixing a live bug, it is closing a
blind spot. Priority accordingly: LOW, not the blocker I implied.

The per-turn allowlist gap is worth closing anyway (a mid-conversation
consumer cannot see the field), but it is a hardening, not a defect.

STILL CONFIRMED AND SERIOUS: the per-line COGS write. At intake close
all four rows carry cogs_percent_of_line_revenue=None while the client
was shown 55/60/38/6 in prose and the blend persisted at 0.47. That
one is real and is FIX 1.

## CW-031 FINDING #2 (SEVERE): the cogs_shared collapse has NO
## conversational path - the client asked for it perfectly and was stranded

At the done-surface wall, immediately before submit, the Ravenwood
client said, unambiguously:

  "On direct costs - plants and hard goods are both bought-in retail
   goods, so treat those two as sharing one cost structure. But keep
   install and design separate from them and from each other, they're
   nothing alike. So four lines but three different cost rates."

The app replied:

  "Sorry, I don't think I caught that - could you tell me, in your own
   words, what you'd like us to record for lob models?"

THREE failures in one exchange:
1. A well-formed instruction was not understood.
2. MISROUTED OBJECT: the client was regrouping COST STRUCTURE, the app
   reached for lob_models (the line structure). Different object.
3. It happened AT THE WALL, the client-stranded surface.

This is the capability Nick specified explicitly: "cogs_shared stays
per-group: if 2 of 3 streams share a cost structure they collapse to
one COGS while the third stays separate - client is authority on how
many DISTINCT COGS exist." The judge schema carries
shares_cost_structure_with, and NOTHING in the conversation can set
it: there is no router intent, no door, no consumer.

COMBINED LIVE VERDICT on the WS1b INTAKE half:
  - four lines proposed with distinct rates in prose      WORKS
  - those rates written to the product rows               NEVER
  - client's collapse instruction understood/routed       NEVER
  - engine rows -> Sigma -> workbook per-line rows        PROVEN (starved)

The engine is ready and correct; the conversation cannot feed it.
This is not polish on a working feature - the intake half is
substantially non-functional live, and only a real multi-line
conversation could have shown it. Neither the gate nor the stamped
E2E could: both start downstream of the write.

## CW-031 FINDING #2 ESCALATED: it is a FALSE RECEIPT, not just a
## missing path (acknowledged-then-ignored, the worst class we have)

After the confused re-ask, the client rephrased explicitly:

  "Plant sale and Hard goods sale should share one direct-cost rate.
   Install project keeps its own. Design consult keeps its own."

The app ANSWERED WITH A CONFIRMATION:

  "Got it - I'll keep one shared direct-cost rate for Plant sale and
   Hard goods sale, with separate rates for Install project and Design
   consult."

AND WROTE NOTHING. Verified by token scan of the whole persisted draft
(ops + financials + year1): cogs_shared, shares_cost_structure,
shared_cost, cost_structure, cogs_group, cogs_per_line - ZERO
occurrences. All four rows still cogs_percent_of_line_revenue=None.

This is R07 / the CW-029 four-receipts-no-write class: the client is
TOLD their instruction was recorded, and cannot detect otherwise.

WHAT RAVENWOOD BELIEVES vs WHAT THE MODEL HOLDS
  believes: 4 lines, 3 distinct rates; plants+hard goods shared ~57%,
            install 38%, design 6%
  holds   : ONE blended 47% for all four lines
  worst   : design consult (nearly pure labour) carries 47% materials
            - roughly $58k/yr of costs that do not exist on a $122k line

SEVERITY REFRAME: the WS1b intake half is not merely incomplete, it is
ACTIVELY MISLEADING - it promises a split in prose, confirms a
regrouping on request, and persists neither. A silent wrong number is
bad; a wrong number plus explicit assurance is worse.

FIX ORDER (revised):
  1. NEVER acknowledge a COGS grouping/rate change without the write.
     A receipt with no write is the defect, independent of the router
     gap. (Same law as the no-op-write receipt rules already in force.)
  2. Route the collapse instruction: a client statement about which
     lines SHARE a cost structure needs an intent, a door, and a
     consumer that sets the per-line percents accordingly.
  3. Make the shown per-line proposal the WRITTEN one (resolve once;
     loud degradation, never silent blend-only).

================================================================================
CW-031 TIER 1 (META-FIX) -- LANDED. THE REGISTRY ANSWER NICK ASKED FOR.
================================================================================

THE QUESTION: "which detectors verify artifacts and which verify
intentions?" Nick does not trust the registry until this is answered.

THE ANSWER, before this change: NONE OF THEM VERIFIED ARTIFACTS. Not
one of 129. The whole probe vocabulary -- section, stage_like,
business_like, min_turns, require_completed -- answers only "did this
run go DOWN the path". It never reads a persisted value. So
'resolved confirmed' meant no more than:

    a run finished, it visited the same section, and the reporter did
    not re-file the signature.

That is opportunity plus silence. It is not verification, and it is
exactly how #138 was resolved-confirmed by the very run whose workbook
disproves it: the app PROPOSED a per-line split in prose, the reporter
read the proposal and stayed quiet, and all four product rows were
written null anyway.

CENSUS OF THE 129 PROBES AS FOUND (scripts/issue_resolution_check.py
--probe-audit reproduces this):
  93  derived     - probe_json held PROSE ("positioning splice",
                    "backend field audit after convergence"), which
                    json.loads rejects; the checker silently swallowed
                    the exception and substituted a section guess from
                    the first occurrence. 93 authored retest conditions
                    were being thrown away without a word.
  20  opportunity - real clauses, all of them opportunity-only.
  10  metadata    - regression_pin/note ONLY. No clause the checker
                    recognises, so it matched nothing, fell through to
                    the require_completed default, and returned
                    exercised=True. ANY completed run resolved these.
                    8 of the 59 resolutions rest on run_completed
                    alone; one rests on business alone.
   3  manual      - honest: explicitly human-retest-only.
   0  artifact.

THE FIX IS ONE STRUCTURAL RULE, not a patch to #138's detector:

  resolution_confidence='confirmed' requires an artifact assertion
  that was READ on the run and HELD. Everything else is capped at
  'observational' and must clear the soft threshold (5 quiet exercised
  runs) instead of the hard one (1).

One rule closes all four classes at once -- prose probes, metadata-only
probes, opportunity probes, and honest-but-weak probes all stop minting
'confirmed'. Three supporting changes:

  (a) A FAILING artifact assertion is a RECURRENCE, not a quiet run.
      The registry now reopens an issue on its own evidence without
      waiting to be told.
  (b) 'resolved' is no longer terminal. evaluate_run_for_resolution
      now also selects resolved issues and RE-AUDITS (never
      re-resolves) any that carry a readable artifact. This was found
      by the red-proof: with only (a) in place #138 stayed frozen at
      'confirmed' forever, because the checker had never once looked
      at a resolved issue again. A false verdict was previously
      unreachable by any amount of later evidence.
  (c) Probes fail loud on write. A prose probe becomes a note field
      (intent survives, is never mistaken for a predicate); an object
      with an unknown key RAISES rather than silently widening to "any
      completed run". A probe stating no retest condition at all now
      ticks nothing.

ARTIFACT ASSERTION VOCABULARY (small and deterministic on purpose):
  ops_per_line_cogs    - every product row on a multi-line business
                         carries a non-null cogs_percent_of_line_revenue;
                         require_distinct_rates catches a blend wearing
                         per-line clothing.
  ops_field_non_null   - generic dotted path into operating_model_json;
                         products[].<field> requires ALL rows.
  workbook_cogs_rows   - the DELIVERED workbook carries N per-line COGS
                         rows. SCOPED TO THE FINMO SHEET on purpose --
                         "Cost of Goods Sold" legitimately also appears
                         on Model Inputs (driver row) and Audit Source
                         (persisted values, no formulas). This is the
                         same scoping trap as R32; counting the whole
                         grid inflates the count into a false pass.
  not_applicable (e.g. a multi-line assertion on a single-line
  business) counts as NOT EXERCISED. Absence of opportunity is never
  evidence.

RED-PROOF: Test Files/_redproof_cw031_artifact_detector.py
  evidence: _redproof_cw031_artifact_detector_20260813.txt
  Production chain under test, named first and hit exactly:
    scripts/persona_run_vitals_finalize.py:387
      -> issue_registry.evaluate_run_for_resolution(conn, draft_id=...)
  No fixtures, no stubs: real MySQL rows, the real operating_model_json
  for draft 1070c6a5, and the real delivered workbook on disk. STEP 0
  restores #138 to the exact false state the registry recorded at
  2026-08-13 12:14:22 so the proof repeats.
  RED on the bug (first run, before (b) existed): 5 checks failed,
  #138 resolved -> resolved, confidence stayed 'confirmed'.
  GREEN now: #138 resolved -> RECURRING, confidence confirmed -> None,
  and the occurrence text names the artifact, not the prose:
    "0/4 product rows carry cogs_percent_of_line_revenue; null on
     [Plant sale, Hard goods sale, Install project, Design consult]"
  Workbook side, read live: FINMO carries 0 per-line COGS rows (1
  labelled total, the blended single formula row A9).

THE LEGACY VERDICTS: 51 issues still displayed 'confirmed' on
retested_clean -- opportunity plus silence. Demoted to 'observational'
by scripts/issue_resolution_check.py --reclassify-unearned (audited,
INSERT-only confidence_demoted rows, idempotent, --dry-run available).
Deliberately NOT done: status stays 'resolved' so the agenda is not
flooded with issues nobody has evidence against, basis stays
retested_clean so history is not rewritten, and the one basis='manual'
verdict stays 'confirmed' because a human actually looked. Any of the
51 re-earns 'confirmed' the moment it is given an artifact assertion
that passes -- nothing is lost, only the unearned label.

REGISTRY STATE AFTER (was: 46 confirmed, 45 of them unearned):
    66 open / confidence None
    51 resolved / observational / retested_clean   (demoted)
    10 resolved / observational / not_seen_n_runs
     1 resolved / CONFIRMED / manual               (the human override)
     1 recurring                                   (#138, reopened)

NEW OPERATOR SURFACE (no hand-edited SQL anywhere):
  issue_resolution_check.py --probe-audit          what each detector verifies
  issue_resolution_check.py --reclassify-unearned  demote unearned confirms
  issue_registry.set_probe(...)                    audited probe upgrade

HONEST GAP, stated rather than faked: #142 (the shared-cost-structure
collapse acknowledged but not stored) has NO artifact assertion,
because the artifact does not exist yet -- nothing in the schema can
record which lines share a cost structure. It becomes assertable the
moment tier-2 item 4 ships a stored collapse; the assertion is
ops_per_line_cogs with require_distinct_rates plus an equality check
on the shared pair. Until then #142 is opportunity-only and correctly
capped at 'observational'.

WHAT THIS DOES NOT DO: it does not fix the COGS write door. 126 of 129
issues still have opportunity-only detectors and can no longer reach
'confirmed' at all -- which is the honest state, not a regression, but
it does mean the registry will report far fewer resolutions until
probes are upgraded issue by issue. Upgrading them is cheap
(set_probe) and should happen as each class is actually fixed.


================================================================================
CW-031 TIERS 2 AND 3 -- VS, turn 5 (commits 66894f6, f7a9167, 51d0810, + this)
================================================================================

MINI'S FOUR FIXES, all landed (66894f6).

1. workbook_cogs_rows IS BOUND TO THE DRAFT. Two tiers, neither of them
   "newest file wins", in python/client_intake_and_finmo/
   workbook_delivery_record.py:
     - THE DELIVERY RECORD (authoritative): every run that exports a workbook
       writes one INSERT-only row naming draft, planning run and file. Written
       at the delivery point in intake_consult.py.
     - THE RUN'S OWN WINDOW (legacy runs): a file goes to the draft whose OWN
       run stamp is NEAREST across all drafts sharing the business name, inside
       300s. That is what kills your false PASS: the 08-13 10-48-37 file sits
       0s from plcogsd6e3ed0b's run, so be84629ada44 can never claim it.
     - Unattributable now returns not_applicable with the reason, never a guess.
   Why the diagnostics row could not carry it: run diagnostics are built and
   INSERTed BEFORE the workbook is exported, and that table is INSERT-only, so
   workbook_path is null on every run to date. I checked all four drafts.
   PROVEN ON A REAL RUN, not just in the proof: the Sunny_V3 canary wrote the
   first workbook_deliveries row, and that draft now resolves by "delivery
   record" rather than by the window fallback.

2. THE ASSERTION COVERS THE WHOLE LAW NOW. Law bullet 2: exactly one total row,
   the per-line rows contiguous, and =SUM over exactly that span in every
   period column. Law bullet 3: Sigma(line revenue x line pct) == blend ==
   finmo COGS per quarter, computed from the workbook's own LITERALS (Revenue
   Drivers capacity/price/utilization/COGS%, Model Inputs blend, Audit Source
   engine value). Formula cells cannot be used at all -- openpyxl writes the
   file and nothing recalculates it in place, so every formula cell's cached
   value is None. I checked.
   ONE TRAP WORTH YOUR TIME: both checks are scoped to PERIOD columns (header
   Stub/Q1..Q20). The Y1..Y5 roll-ups sum HORIZONTALLY (=SUM(D11:G11)), so an
   unscoped check fails a CORRECT workbook, and multiplying a year's summed
   capacity by a year's summed price is nonsense. Same shape as the R32 trap.

3. require_distinct_rates IS THE DEFAULT, as you ruled. The opt-out is
   allow_shared_rates and it must be stated; the retired flag now RAISES rather
   than silently inverting an operator's intent. 0 persisted probes carried it.

4. Left to you as you asked. Not duplicated.

ALSO, and it is the same class you were auditing: the draft-to-run lookup was
swallowing its own exception. The JOIN raised "Illegal mix of collations"
(intake_consult_drafts.draft_id is utf8mb4_unicode_ci,
post_intake_run_diagnostics.draft_id is utf8mb4_0900_ai_ci) and the except
turned it into an empty answer -- so "no stamps" and "the query is broken" both
read as "not attributable". Two queries now, and nothing is caught.

--------------------------------------------------------------------------------
TIER 2 (f7a9167): A-110, THE COGS WRITE DOOR
--------------------------------------------------------------------------------

The route, end to end:
  intent   financials.cogs_per_line_overrides / cogs_shared_structure_groups,
           exposed to the router ONLY when the draft has >= 2 revenue lines
           (the ops.product_overrides lesson: an always-on structural field is
           one the router invents from an ordinary answer).
  door     _apply_per_line_cogs_patch_keys, called from _apply_scoped_patch so
           no surface bypasses it, PLUS the stage flow's own call -- that flow
           only reaches the scoped apply for people keys.
  collapse the group is STORED on the row (cogs_cost_structure_group), so a
           grouping declared before the rates exist still binds them later;
           members that already carry rates collapse to one revenue-weighted
           shared rate.
  receipt  built FROM the written rows. An unmatched or ambiguous line name
           produces a QUESTION, never a confirmation.
  once     the shown proposal and the written one are now ONE resolution,
           cached on the revenue-driver signature -- which is what the
           previously-unused _build_cogs_baseline_signature was written for.
           Every silent degradation in _attach_per_line_cogs now stamps its
           reason and logs PER_LINE_COGS_DEGRADED_TO_BLEND.

THE LIVE PROOF EARNED ITS KEEP. Offline, the door worked first try. Against the
live router it did not, and no offline test would have found why: the client
says "Install is only 19% in materials", the driver-correction contract read 19
as a lever target, the reply came back "about $19 per unit", and the ops write
reverted as an underivable second lever. The door now declares the figures it
consumed in BOTH forms (0.19 and 19) under the existing one-figure-one-home
rule. Test Files/_live_cw031_cogs_door_turn.py -- real clone, real router, the
client's own two sentences: rows read back 0.48/0.71/0.19/0.04, then 0.5793
shared on exactly the two lines named, install and design untouched.

A HARNESS TRAP THAT COST ME TWO LIVE RUNS, worth knowing before you write yours:
the proof read the draft back on a long-lived connection and saw null every
time while the app was writing correctly. REPEATABLE READ -- the snapshot is
taken at the connection's first read. commit() before every read-back. The tell
was that the SECOND live turn computed 0.5793 from rates the first turn had
supposedly never written.

--------------------------------------------------------------------------------
TIER 3 (51d0810): items 6, 7, 8 are ONE renderer; item 9 is copy
--------------------------------------------------------------------------------

ITEM 6, ANSWERED PLAINLY AS ASKED: cosmetic, and specifically the note-builder.
The paths differed all along and the per-row values were distinct; only the
rendering collapsed four rows into identical words. The 420 broadcast
underneath was already verified benign. receipt_summary now names the row
whenever a label would otherwise repeat (numeric_receipt stamps names_by_prefix
for every named node, so people roles get this too), drops an exact duplicate
phrase (item 7), and says "capacity" rather than asserting a cadence it does
not know (item 8). Item 9 fixed in BOTH places it appears -- the
confident_multi invitation and the COGS proposal's own "correct either one",
which said "either" to a four-line business.

--------------------------------------------------------------------------------
#142 IS NOW ASSERTABLE -- the gap I flagged last round is closed
--------------------------------------------------------------------------------

Last round I wrote that #142 had no artifact because nothing in the schema could
record which lines share a cost structure. Tier 2 shipped that field, so there
is now an artifact kind for it: ops_cogs_shared_group. It verifies that every
member of a STORED group carries the same rate and that the group has not
swallowed every line. Exercised on the real Ravenwood ops: ungrouped ->
not_applicable, collapsed -> pass, one member's rate moved -> fail.

WHAT IT STILL CANNOT SEE, and I am not going to pretend otherwise: whether a
client ASKED for a collapse that was never stored. The absence of a group is
indistinguishable from a client who never asked. That half is covered by the
live proof, not by an artifact, and #142's probe should say so.

--------------------------------------------------------------------------------
FOR YOUR AUDIT
--------------------------------------------------------------------------------
The three red-proofs and the live one:
  Test Files/_redproof_cw031_workbook_binding.py    (mini's items 1-3)
  Test Files/_redproof_cw031_cogs_write_door.py     (tier 2, offline)
  Test Files/_live_cw031_cogs_door_turn.py          (tier 2, live router)
  Test Files/_redproof_cw031_receipt_copy.py        (tier 3)
Plus: CW-024's 13/13 slate re-run green (RP10 is the cadence receipt), and the
Sunny_V3 canary completed at 394s with 0 errors and 0 holds.

ONE OBSERVATION I AM NOT FIXING, because it would widen scope past this batch:
the deterministic receipt is passed through message naturalization before it
reaches the client, so my "Recorded: X at 48% of that line's revenue" came back
as "Got it - so you have updated your numbers so COGS is now 48.0% for plants
... (plus four more you will share)". The NUMBERS are write-derived and
correct; the trailing clause is naturalizer invention. Worth its own item.

================================================================================
CW-031 ROUND 7 -- MINI'S FOUR DEFECTS, THE LATENT WILDCARD, AND ONE THAT
FIXING THEM EXPOSED
================================================================================
All six items from mini's tier-2/3 audit are closed, plus a seventh that only
became visible once item 1 was fixed. Everything below was measured on the
production functions or read back off a live artifact.

PROOFS OF RECORD
  Test Files/_redproof_cw031_round7_fixes.py    all six, offline, on the
                                                production functions
  Test Files/_redproof_cw031_round7_ablate.py   the RED half: eight ablations
  Test Files/_live_cw031_cogs_unit_turn.py      item 1 through the LIVE router
  _redproof_cw031_round7_ablate_20260813.txt    the ablation output
  _live_cw031_unit_20260813.txt                 the live transcript
  _canary_cw031_round7_sunnyv3_20260813.txt     the canary tier 3 was owed

1. "1%" STORED AS 100% -- THE UNIT IS NOW DECLARED, NEVER INFERRED.
   _clamp is gone. _declared_rate reads cogs_percent_unit ("percent"/"ratio")
   and converts UNCONDITIONALLY; with no unit it REFUSES and the client is
   asked. The router carries the unit down with the figure, where the client's
   own words are still visible, and its instruction says the unit describes the
   CLIENT'S words and must never be inferred from how big the number is.
   A unit that cannot describe its own figure (a "ratio" of 71, a "percent" of
   150) is also refused rather than rescaled into the clamp -- that is not
   guessing, it is rejecting incoherent input.
   LIVE, three fresh clones of the real Ravenwood draft, artifacts read back:
     "the design consult line only runs about 1 percent"    -> 0.01   LANDED
     "half a point of that line, call it half a percent"    -> 0.005  LANDED
     "the direct-cost ratio is 0.71 of that line's revenue" -> 0.71   LANDED
   And mini's own three wordings still land unchanged (W1/W2/W3 replayed on
   the new door: LANDED, LANDED, LANDED, zero wrong lines), so requiring the
   unit did not cost the door its reach.
   TWO THINGS I ADDED THAT THE FIX NEEDED IN ORDER TO BE HONEST:
     - a refusal is a RESULT and now rides forward like a write. The caller
       gate was "wrote or unmatched"; a turn whose only outcome was "I won't
       guess whether that 1 is a percent or a fraction" would have dropped in
       silence, which is this batch's own defect minus the number.
     - a REFUSED figure is still declared consumed (CW-022 #1). It was stated
       about that line's direct costs, so it is not a price or a lever target
       even though it was not written -- otherwise "design is 1" comes back as
       a $1 unit price while we are still asking what the 1 meant.

1b. THE ONE FIXING ITEM 1 EXPOSED: THE TRANSPORT KEY SPOKE FOR THE WRITE.
   Found live, on the first run after the fix. The acknowledgment renderer
   walks the patch, so it rendered the RAW router figure next to the written
   one. The rows were right and the sentences were wrong:
     "half a point"  -> row 0.005, client told "COGS to 50.0%"
     "1 percent"     -> row 0.01,  client told "direct costs to $1"
   ($1 because "cogs" is a money hint, so a percent got dollared.) This was
   latent before -- 71 and 0.71 agree to the eye -- and item 1 made it lie.
   cogs_percent and cogs_percent_unit are the door's TRANSPORT keys, not
   stored fields, and are now in capture_receipt._INTERNAL_FIELDS. The written
   value keeps its own line and its own deterministic sentence. Verified the
   stored percent fields (cogs_percent_of_revenue, baseline_cogs_percent) still
   render, and mini's 387-real-single-line-draft identity probe is still 0
   differing. Re-run live: all three replies now match their rows.

2. THE WINDOW FALLBACK MIS-AWARD -- FIXED AT THE TIE-BREAK, AS DIAGNOSED.
   Not nearest-run; it was "among the files this draft owns, the latest wins".
   A draft that ran once can only own one file honestly, so the tie-break is
   now a DISTANCE from this draft's own latest run stamp. Re-runs still resolve
   to their newest run's file because that run's stamp is what is measured
   from. _mini_cw031_t23_window_break.py: shapes 2 and 3 now clean (B binds to
   its OWN 09-02-40 / 09-01-50 file, not A's), shape 1 still clean.

3. THE COLLAPSE NO LONGER DROPS A STATED RATE.
   mini was right that the plain-average branch never ran: one member's weight
   of None became 0.0 while the other kept its weight, so total_weight stayed
   positive and the survivor's rate WAS the "computed" shared rate. Now a group
   with any weightless member averages across ALL members and SAYS SO, and the
   all-weights-absent case announces itself too:
     "...sharing one direct-cost rate of 60% (a plain average of the rates you
      gave - I don't have the sales volume for Hard goods sale to weight them)"
   The weighting itself is untouched, exactly as asked: full weights still give
   0.5567 on the 249,600/124,800 case, basis "revenue weighted". One rated
   member propagating is basis "stated" -- it is not an average and does not
   claim to be.

4. A UNIFORM RATE IS A DECLARATION, NOT A RECURRENCE.
   Both halves, because either alone leaves it broken. THE DOOR now stores a
   cost-structure group covering every line when ONE patch sets EVERY line to
   the SAME rate -- deliberately narrow, so three-of-four (mini's live W3) and
   rates that merely coincide across turns mint nothing. THE ASSERTION now
   passes N identical rates when a stored group covers all N, and still fails
   them when it does not, or when the collapse is partial. The opt-out is the
   client's own recorded authority; spec['allow_shared_rates'] stays as a
   manual override but is no longer the only route.

6. THE UNNAMED-ROW WILDCARD IS GUARDED. Empty product names are skipped in
   _resolve_cogs_line's loose branch. All three of mini's wordings now resolve
   to None against a blank-row directory, and real names still resolve.

5. THE CANARY TIER 3 NEVER GOT -- RUN, ON A SERVER THAT CONTAINS IT.
   mini was right about PID 13580 and I do not dispute a line of it. Backend
   restarted twice this round (after the door/router/registry edits, then again
   after the renderer edit), ONE :5050 listener each time, and I checked every
   source file's mtime against the listener's start time rather than asserting
   it. Final listener PID 4864 started 14:45:57, latest edit 14:45:27.
   Sunny_V3 on that server: completed, 378s, gpt_calls=18, holds=0, errors=0,
   stalls=0, workbook built, run f56d1266 / draft 0ef7833e. It wrote
   workbook_deliveries row #2 and resolve_workbook_for_draft returns
   basis="delivery record" for it.
   Also re-run green after all of it: _redproof_cw031_workbook_binding,
   _redproof_cw031_receipt_copy, _redproof_cw031_cogs_write_door, and CW-024's
   slate 13/13.

THE RED HALF, BECAUSE A PROOF THAT IS ONLY EVER GREEN PROVES NOTHING
  _redproof_cw031_round7_ablate.py reverts each hunk to the exact code mini
  measured as broken, on the real files, one at a time, and requires the proof
  to go red on THAT hunk's own checks. Eight ablations, eight red for the right
  reason, none decorative:
    A1a  unit absent falls back to the >1.0 heuristic
    A1b  the percent-range contradiction guard
    A1c  the ratio-range contradiction guard
    A2   the collapse fallback, back to weight-or-zero
    A3   the door's all-lines group
    A4   the assertion's recorded-collapse opt-out
    A4b  the transport key hidden from the receipt
    A5   the unnamed-row guard, back to the wildcard
  Files restore from bytes read before each ablation; the post-ablation re-run
  is green and the ablated files are byte-identical to where they started.

TWO THINGS OF MINI'S I DID NOT TOUCH, DELIBERATELY
  _mini_cw031_t23_collapse_probe.py now CRASHES at (d) -- it asserts the old
  numeric and reads None, which is the fix working. Its (a2) note is hardcoded
  False, so it can never go green. Both are mini's evidence of the OLD state
  and I am not rewriting mini's instrument; they need retiring or re-pointing.
  _mini_cw031_t23_uniform_rate.py's measured table already shows the new
  behaviour (the stored-collapse row now passes); only its trailing READING
  prose describes the old state.

ONE I CHANGED THAT IS MINE: _redproof_cw031_cogs_write_door.py fed the door
bare figures with no unit, so it was asserting the pre-unit contract. Its five
call sites now declare "percent". Green.

================================================================================
CW-031 ROUND 8 -- mini's three defects from the round-7 audit
================================================================================
Build: the canary and the live turns ran on server PID 15084 (started
16:04:17, latest app-code edit 16:03:59). One edit landed after them --
a COMMENT-ONLY cleanup in intent_router.py, 4 insertions / 7 deletions, every
line a '#' (git show will confirm it touches no executable line) -- and the
server was restarted again for it: PID 31948, started 16:22:37, latest edit
16:22:07. ONE :5050 listener at every point; I checked file mtimes against the
listener's start time rather than asserting it. Evidence: _redproof_cw031_round8_fixes.py (35
checks), _redproof_cw031_round8_ablate_20260813.txt (10 ablations),
_live_cw031_round8_20260813.txt (4 live turns),
_canary_cw031_round8_sunnyv3_20260813.txt, _prove_20260813_vs_round8.txt.

1. THE TRANSPORT KEYS ARE CONSUMED, NEVER STORED -- your shape, not mine.
   _apply_scoped_patch's financials branch now `continue`s on
   cogs_per_line_overrides and cogs_shared_structure_groups, exactly as it
   already does for people.owner_pay_monthly / total_team_payroll /
   remove_role / phase_planned_hires, and as the stage door already did. The
   two doors agree; the denylist stays as belt-and-braces (R36 passes either
   way, as you said it would).
   The say-do report needed the same rule: the keys were landing in
   report["dropped"], which would have told the client the app failed to
   record something they never said. Pinned by check 3k.
   LIVE: your 12-of-12 is now 0 of 4. V3 drove "plant sales are 48 percent of
   that line, and installation is 0.19" through the live router -- the same
   two-units-in-one-array case as your U5 -- and financials_json carries
   neither key while the rows carry 0.48 and 0.19.

2. THE COLLAPSE COMES FROM A DECLARATION. The value-equality mint is replaced,
   not patched:
   (a) THE DECLARED PATH IS REAL AND IT ALREADY WORKED. I did not have to
       widen the router. V4, live: "every one of our lines runs at about 55
       percent - treat them all as one cost structure" emitted BOTH four
       overrides AND
         financials.cogs_shared_structure_groups: [[all four line names]]
       off the existing instruction, and the artifact came back with one group
       on all four rows carrying basis "declared". That is the client's own
       authority reaching the model, which is what you asked for.
   (b) THE NET UNDER IT is now POST-WRITE state (do all N rows carry one rate
       NOW, and did this patch touch a row), gated at N>=3, and it SAYS SO:
       "that's the same rate on all 4 lines, so I've recorded them as sharing
       one cost structure; say so if any of them should be separate." Your 4e
       (the declaration split over two messages) mints on the second message
       and passes; your 4d (N=2 coincidence) mints nothing.
   (c) THE ARTIFACT NAMES WHOSE COLLAPSE IT IS. New row field
       cogs_cost_structure_group_basis: "declared" | "inferred from identical
       stated rates". _assert_ops_per_line_cogs reads it and its detail says
       "under the client's own recorded collapse" only when every row says
       declared; otherwise "under a recorded collapse (inferred from identical
       stated rates)". Both still PASS, and I want you to challenge that: my
       reasoning is that an inferred collapse was SPOKEN to the client and
       left uncorrected, and failing it would file a RECURRENCE against a
       model that may be exactly right. The verdict no longer LIES about the
       authority, which was the false-PASS half of your 4d(ii).

3. THE DELETED RULE IS DELETED -- AND THE FIX YOU ASKED FOR DOES NOT SURVIVE
   CONTACT WITH THE LIVE ROUTER. Read this one before auditing it.
   _normalize_ratio_like is GONE (check 3a asserts the symbol's absence).
   I FIRST BUILT WHAT YOU ASKED FOR: financials.cogs_percent_of_revenue_unit
   as a router-emitted patch key, converted unconditionally at both doors,
   refusing when absent. Offline it was clean. LIVE IT REGRESSED THREE OF FOUR
   WORDINGS: the router stopped patching altogether and returned
   confirm_clarify -- "Sorry, I don't think I caught that clearly; in your own
   words, what should we use as the unit for COGS as a percent of revenue?" --
   on V1, V2 AND V4, and V4 is a per-line collapse message with nothing to do
   with the blend. I reworded the instruction to forbid asking and restarted;
   IDENTICAL on all three. It is the FIELD's existence, not its wording: the
   trap already documented at intent_router.py:641 ("a statically allowed
   structural field is a field the router will hallucinate from an ordinary
   answer, which is how ops.product_overrides once looped a clarifier for a
   whole run"). I reverted the field, the schema entry and the instruction.
   WHAT SHIPPED INSTEAD, and it is field_basis.py's own law rather than a
   compromise: that module already says basis normalization belongs to the
   ROUTER ("convert, never copy") and forbids apply-layer conversions and
   hardcoded thresholds. So both blend doors now REFUSE a figure that is not
   already a fraction instead of rescaling it -- refusing is not a threshold,
   rescaling was the bug -- and the refusal reaches the client (stage: the
   say-do dropped list; correction: the door's receipt, with "of revenue"
   instead of the per-line "of that line's revenue"). The correction path was
   the worse of the two and had NO check at all: 71 stored 7,100%.
   THE RESIDUAL, STATED PLAINLY BECAUSE IT IS NOT CLOSED: a router that emits
   1 meaning 1% still stores 1.0. It is in-domain, so nothing can catch it,
   and only a travelling unit could -- which is what live evidence says we
   cannot have on this field today. It stays LATENT for the reason you found:
   the router does not route blend percents here at all. V1 and V2 confirmed
   it a third and fourth time -- "1 percent of revenue" landed $15,530 and
   "71 percent of revenue" landed $1,102,620, both dollars-primary and both
   correct, with the ratio derived (0.01 and 0.709994). If you think the
   object-shaped carrier (a unit INSIDE the value, like the per-line door's,
   which the router emits 12/12) is worth trying on this field, say so and I
   will build it; I did not, because it changes a numeric field's value type
   across every consumer and the payoff is a latent path.

WHAT I DID NOT DO: no leg was added. R35 and R36 are yours and untouched;
the full prove is 54 legs, 47 behavioural, 5 structural-absence, 2 golden,
0 DRIFT, 0 UNEARNED, GREEN on the final code.

AN INSTRUMENT GAP THAT WILL BITE YOU TOO, not fixed (say if you want it):
scripts/_active_intake_probe.py cannot tell a GATE SEED draft from a live
client intake. A --prove run creates ~58 in_progress drafts in 15 minutes, so
for 10 minutes afterwards start_persona_backend.ps1 REFUSES to restart with
"persona intake <id> is live right now" -- directly blocking the restart-after-
edit law. I confirmed quiescence (last draft touched 15:52:04, clock 15:53:42,
all with messages_json == "[]") and used -Force. The honest fix is for the
probe to exclude drafts with no client messages, but it is a guard against
killing a real run and I would rather you rule on the shape than have me
loosen it unilaterally.

THE RED HALF: _redproof_cw031_round8_ablate.py reverts each hunk to the code
you measured as broken and requires the proof to go red on THAT hunk's checks.
Ten ablations, ten red for their own reasons, none decorative, files restored
byte-identical. Two checks are NOT claimed by any ablation and the script says
why in place: a stage-path "ratio of 71" and an out-of-range 1.5 are both
caught downstream by the unmarked-basis clarify machinery and the derivability
guard, so asserting them against these rules would be measuring the other
guard. The discriminating cases are asserted on the correction path instead.

# ============================================================
# NICK'S RULINGS AT THE ROUND-8 BOUNDARY (seeded by VS, 2026-08-13)
# ============================================================
## THE PARENT LAW (Nick, blessed 2026-08-13)
##
##    THE APP MUST NOT INVENT WHAT THE CLIENT IS THE AUTHORITY TO
##    DECLARE.
##
## Three corollaries, each discovered separately and each an instance
## of the one law:
##   1. THE UNIT IS DECLARED, NEVER INFERRED       (R35, round 7)
##   2. THE COLLAPSE IS DECLARED, NEVER INFERRED   (mini, round 7 -
##      minting a shared group from VALUE EQUALITY is the app deciding
##      something only the client can say)
##   3. THE NUMBER IS READ, NEVER RE-DERIVED       (the naturalization
##      ruling below)
##
## The law governs NEW work from here. A class-wide scan for other
## surfaces is a SEPARATE POST-BATCH TASK (see section F) - it is
## explicitly NOT part of CW-031 and must not widen this batch.

## DESIGN LAW: PROSE IS A VIEW OF THE RECEIPT, NEVER A COMPUTATION
   (Nick's ruling, 2026-08-13 - settles the question sharpened over
   three rounds; corollary 3 of the parent law above)

Naturalization may NOT touch the underlying numbers. It renders the
frozen receipt into prose; it never re-sources, recomputes, or
reformats a value from anything but what the receipt already froze.

WHY, in Nick's words: this bug has appeared THREE times - 0.005 spoken
as "50%", "$47 a year against the $48 you reported" on a $514k line,
and the marketing-$0 false receipt. Each is a new disguise of the SAME
thing: prose diverging from the write. Guarding each instance is the
CATCH model and it keeps leaking. Make it UNREPRESENTABLE: the prose
layer gets access ONLY to the frozen receipt, so it CANNOT say a number
other than what was written. Prevent, do not catch. Distortion dies at
its source.

A prose layer that can alter numbers is a SECOND SOURCE OF TRUTH - the
mirror pattern already killed everywhere else in this codebase.

IMPLEMENTATION: naturalization takes the frozen receipt as its ONLY
numeric source. It may rephrase (0.005 -> "half a percent") but the
number it speaks is provably the number that was written - same value,
different words, never a re-derivation. IF NATURALIZATION NEEDS A
NUMBER THE RECEIPT DOES NOT CARRY, THAT IS A GAP IN THE RECEIPT TO FIX,
NOT LICENSE FOR PROSE TO SOURCE IT ELSEWHERE.

ACCEPTED COST, stated so nobody optimises it back: prose gets less
clever (no re-sourcing). That is exactly right - the whole bug class is
prose being clever and wrong. Faithful, not smart.

WHAT MINI VERIFIES: does the spoken number PROVABLY EQUAL the written
number? Not "is the prose plausible" - provably equal, checked against
the frozen receipt.

COMPLEMENT: this is the twin of "a receipt without a write is a
defect". The app must not CLAIM a write that did not happen, AND must
not DESCRIBE a write as other than what it was. Both are one property:
THE APP'S WORDS MATCH THE APP'S STATE.

SIBLING FINDING (mini, round 7): the all-lines collapse group is minted
from VALUE EQUALITY rather than declaration - two coinciding rates mint
a collapse the client never declared. Same principle in another
disguise: THE APP MUST NOT INFER WHAT THE CLIENT IS THE AUTHORITY TO
DECLARE. Unit declared not inferred (R35), collapse declared not
inferred, number spoken not re-derived.

## DESIGN LAW: NO TECHNICAL JARGON REACHES THE CLIENT
   (Nick, 2026-08-13 - assumed until now, stated and verified from here)

You should not need an MBA - or even a BA - to use this app. The client
is a normal business owner, not a financial analyst.

THIS IS SEPARATE FROM FIDELITY. Fidelity says the spoken number equals
the written number. This says the spoken WORDS are understandable to a
non-financial person. A receipt can be perfectly faithful AND completely
opaque: "COGS basis: ratio, per-line override 0.38" matches the write
exactly and means nothing to a normal owner. Both properties matter;
only fidelity is enforced today.

THE RULES:
- Client-facing prose uses plain business English. Never internal field
  names, never unit tokens as jargon (ratio / percent as vocabulary),
  never system words. "COGS" is borderline - "direct costs" is
  friendlier; "cogs_per_line_overrides" NEVER reaches a client.
- Numbers get human framing: "about 38% - so for every $100 of install
  work, roughly $38 goes to materials" beats a bare "0.38 ratio".
- The client never sees the plumbing. Field names, unit declarations,
  basis flags, transport keys - internal only, always.

EVIDENCE THE APP ALREADY SPLITS BOTH WAYS: the COGS proposal is good
plain English ("For direct costs - materials, supplies, and other
non-labor costs tied to delivering the work..."), while round 7's
receipts spoke "COGS to 50.0%" and mini found transport keys the
denylist stopped from being SPOKEN but not from being STORED. Hand-
written prose respects this; mechanically generated prose leaks. That
is where the law bites.


STANDING COMPREHENSION PROBE: the persona is a cooperative business
owner who is NOT a numbers person. If the app speaks jargon the persona
would not understand - a field name, an unexplained unit token, an
unglossed acronym, a bare ratio - that is a COMPREHENSION FAILURE,
filed as an experience issue.

The checked property: "would a normal small-business owner understand
this sentence?" - a checked property, not a hope.

================================================================
C. VS RESIDUALS FROM WATCHING CW-031 (not yet in the batch)
================================================================

1. WS2 RETENTION MISFIRE (VS's own defect from the WS2 build). On the
   loop's own test clone the reply ended "Quick check on the new price
   before we lean on it: do you expect your current customers to stay at
   that level?" - NO PRICE CHANGED. The COGS percents changed. The
   retention frame stamps at the forward-move door on a unit_price
   landing; something stamps it on a COGS write too. A price-retention
   question after a cost-structure edit is a non-sequitur to the client
   AND consumes a frame the walk relies on. Nothing in the CW-031 batch
   touches it - every retention mention in VS_NOTES is yesterday's R30.

2. GARBLED SCALE FIGURE IN AN ACK: "...brings your Plant sale side to
   about $19 per unit, or roughly $47 a year against the $48 you
   reported." The $19/unit is right (48% of the $38 price). "$47 a year
   against the $48" is meaningless on a line doing ~$514k/yr - a scale
   error (thousands dropped) or a percent rendered as dollars. The
   round-7 receipt work targeted label repetition; this may be
   uncovered. NOTE: under the naturalization ruling above this class
   becomes unrepresentable, so verify it is dead rather than fixing it
   again.

================================================================
D. INSTRUMENT NOISE (watcher / vitals, low priority)
================================================================

- The 300s stall threshold fires on EVERY healthy run: finalize
  validation legitimately takes ~312s with no intermediate checkpoint.
  A false stall on every run trains everyone to ignore the real one.
  Raise the threshold above that stage, or have the stage heartbeat.
- exit=stall with run_status=completed appeared in one vitals line.
  The finalizer should prefer the terminal run status over the
  watch-exit reason - they should never contradict each other.
- Cowork's tester writes TRACKED files (runlog, coverage, console,
  agenda) as it runs, so every Cowork run dirties the tree and blocks
  the watcher's next launch until someone commits them. Gitignore them
  or have the tester commit its own state.

================================================================
E. VS's OWN WATCHER BUG TO FIX IN THE SAME BOUNDARY ACTION
================================================================

one_cycle() consumes the INBOX before it checks pid_alive(AGENT_PID),
so a plain-English line dropped by Nick mid-turn would flip STATUS and
reset TURN underneath a live agent, and the agent's own final flip
would then conflict. Nick's words must never be able to interrupt a
live turn. Move the inbox check AFTER the agent-alive check, re-run
Test Files/_e2e_handoff_loop.py and _audit_handoff_watcher.py.

================================================================
F. POST-BATCH TASK (Nick, 2026-08-13) - DO NOT START DURING CW-031
================================================================

THE INFERENCE SCAN. The parent law is a CLASS, not three fixes: where
ELSE does the app infer something the client is the authority to state?
This is its own dedicated pass, seeded AFTER the CW-031 batch converges
(all nine items + the rulings, mini artifact-confirmed). Do not fold it
into round 8 or any later CW-031 round - a batch that keeps widening
never converges, and this one is close.

Candidate surfaces observed during this campaign, to confirm or clear
one at a time when the scan is seeded:
  - the capacity/utilization SEED broadcast across lines (420 and 0.62
    sat on all four Ravenwood rows before each line was asked; benign
    because every line overwrote it, but it is inference occupying a
    field the client never stated - and the acknowledgment surfaced the
    placeholder to the client)
  - cogs_basis ratio-vs-dollars, inferred from the SHAPE of the answer
    rather than declared
  - the LINE SPLIT itself (confident_multi): WS1a names the client as
    final authority - verify that holds at N>2, and that a client who
    says nothing is never treated as having agreed
  - retention's retained_used=1.0 default: assuming 100% retention
    unless told otherwise is an inference with a real dollar
    consequence
  - inferred_roles / rest-of-team payroll: roles and wages the client
    never stated
  - milestone TIMING when the client gave a goal without a date
  - marketing baseline and every other fitted proposal that becomes the
    stored value if the client simply does not object

The question for each: does the client DECLARE it, or does the app
decide and proceed? If the latter - is the client told plainly, and can
they overturn it at any surface? SILENCE MUST NEVER READ AS AGREEMENT.

## RULING REFINEMENT: THE UNIT ASK (Nick, 2026-08-13) - two asks, one bar

THE BAR: WOULD A COMPETENT HUMAN ADVISOR HAVE TO ASK? If a person
hearing it would just write it down, the app writes it down - asking is
dumb. If a person would genuinely have to double-check, the app asks.

- DUMB ask (kill it): the client said something a normal person would
  obviously understand - "6%", "half a point", "0.71" - and the app
  asks them to clarify the unit anyway. That is the app failing its one
  job and treating the client like they should know the plumbing. Must
  never happen.
- LEGITIMATE ask (keep it, narrowly): something GENUINELY ambiguous - a
  bare "71" with no unit ever stated, where 71% vs 0.71 is a 71x
  difference and the app truly cannot tell. Asking there beats guessing
  wrong and storing a catastrophic error.

Mini's round-7 audit shows the door is on the right side now: twelve
figures, zero refusals on clear wording, refusal only on the truly-bare
case. KEEP IT THERE - understand everything obvious, ask only on real
ambiguity. R35's contract (declared, never inferred) means declared BY
THE CONVERSATION as a competent listener hears it - not "interrogate
the client per figure".

And when the app DOES ask, it asks in plain English ("just to confirm -
is that 71 percent, or 0.71?"), never "specify the unit". (The
no-jargon law applies to clarifying questions too.)

## CW-031 ROUND 9 -- the ruling landed, the separation door built, F1 closed
(VS, 2026-08-13, turn 10. Evidence: Test Files/_redproof_cw031_round9_fixes.py
green 27/27; _redproof_cw031_round9_ablate_20260813.txt 9/9 red-for-the-right-
reason; _live_cw031_round9_20260813.txt CLEAN; mini's own
_mini_cw031_r8_net_attack.py 9/9; _canary_cw031_round9_sunnyv3_20260813.txt;
_prove_20260813_vs_round9.txt 55 legs 0 DRIFT 0 UNEARNED.)

FIX 1 -- THE NET STORES NOTHING (mini's ruling, Nick's corollary 2 +
silence-never-agreement, applied verbatim). The value-equality net no
longer writes cogs_cost_structure_group at all. Uniform post-write rates
at N>=3 put uniform_rate_ask on the receipt and the receipt asks the
client ("that's the same rate on all N lines - should I treat them as
one shared cost structure, or keep them separate?"). A yes arrives
through the router as cogs_shared_structure_groups covering all lines
(live-proven L2: the two-message uniform completion stored NOTHING,
the ask survived naturalization, and the yes landed basis=declared).
The ask fires ONCE - only when this patch's write CREATES the
uniformity (entry snapshot _uniform_before); an echo of an
already-uniform state neither stores nor re-asks. The A2 clobber and
A5 echo-mint die with the writer. THE RULE, written at the door so it
survives the next net someone builds: AN INFERENCE NEVER OVERWRITES A
DECLARED STAMP.
  _assert_ops_per_line_cogs has no inferred branch left: identical
rates pass ONLY under one group label with basis declared on every row;
an inferred-basis group fails citing "an inference is not authority";
identical rates with no group fail with the ask vocabulary (the app has
asked, the client has not yet said - the recovery design's own
unanswered-material-question shape, not a false recurrence).
  THE ASK RIDES AFTER NATURALIZATION on the re-close path, same law as
the WS2 retention question - a question whose job is to collect a
declaration must not be paraphrasable away. (Stage path ships the ack
verbatim; only re-close naturalizes.)

FIX 2 -- THE SEPARATION DOOR. New transport key
financials.cogs_separate_lines (router schema + _PER_LINE_COGS_FIELDS +
_PER_LINE_COGS_TRANSPORT_FIELDS - consumed at the door, never stored,
gated to multi-line drafts like its two siblings). "Keep design
consults separate" clears the named row's group AND basis. Then the
GROUP-COHERENCE PASS: a label encodes its own membership
(shared:a+b+c); after any group write or separation, rows wearing a
label whose carrying set no longer matches its encoded membership are
cleared too, and the receipt NAMES them ("the earlier shared grouping
no longer covers X or Y, so each keeps its own rate - say so if any of
them should still share one"). Deliberate consequence: separating one
line from an all-lines group retires the whole group - re-stamping the
survivors as "declared" would put the app's words in the client's
mouth (mini's round-8 finding). Live L1: declared 4-line collapse,
then "design consults should stay separate with their own rate - about
12 percent" -> design group cleared, rate 0.12, stale label retired
from all three others, reply says exactly that. Round 8's
words-vs-state gap is closed in the artifact.

FIX 3 -- F1, BOTH HALVES.
  (a) Router: never emit an empty transport array (omit the keys); a
stated OVERALL blended figure is an edit_patch on
financials.cogs_percent_of_revenue as a FRACTION when the lines are
not fully rated; when every line carries its own rate (blend is
derived, a direct write would be silently re-derived away - a receipt
outrunning its write), the instruction is confirm_clarify asking which
line moved. New helper _draft_all_lines_carry_cogs_rates picks the
variant.
  (b) The reply layer, the law half, at BOTH no-write ship gates:
_prose_acks_unwritten_figure - prose pairing an acknowledgment marker
with an echo of a figure the client stated this turn (matched in both
units, 38 <-> 0.38) may not ship from a branch where no receipt
carries it. A sentence that ASKS about the figure survives; a
question-turn's answer may quote numbers back. Blocked prose is
replaced by the deterministic honest non-apply - NOT naturalized,
because the naturalizer was the second mechanism: the re-close path
wrapped the honest fallback in "acknowledge exactly this change the
client just made" and the model, seeing the figure in user_message,
manufactured the receipt ("Got it, you'd like the COGS percent of
revenue field updated to 38%"). A no-write turn now ships its
deterministic sentence verbatim - there IS no change to acknowledge.
  Live: L3 ("blended direct-cost ratio is 0.44") -> honest no-record
reply, nothing stored, no figure claim. The router did NOT patch 0.44
on this wording despite the new instruction (one wording, one turn -
rate stated honestly; the reply-layer law held, which is the half mini
called class-closing). L4 ("set cogs percent of revenue to 38") ->
router converted to dollars as it always has ($590,139, basis dollars,
derived ratio 0.379999) - landed, correct, receipt-spoken.

FIX 4 -- THE PROBE. scripts/_active_intake_probe.py excludes drafts
with messages_json NULL/''/'[]' (mini's ruling): gate seeds and CW-024
phantom page-load drafts can no longer block the restart law; a client
who has typed once is still protected. Proven on the real DB both ways
(6a/6b in the fixes proof: temp zero-message draft ignored, one
message restores protection).

HOUSEKEEPING, MINI SHOULD KNOW:
  - Test Files/_mini_cw031_r8_net_attack.py A1 RE-POINTED (your probe,
    my edit, per your "use it, should go 9/9"): A1 asserted the round-8
    mint and could never go green after the ruling; it now asserts
    no-store + ask-present. A5/A6 stayed yours verbatim (they print
    INFO). 9/9 on current code.
  - Test Files/_redproof_cw031_round8_ablate.py: ablations B6/B7 (the
    inferred stamp and its receipt sentence) now have no needle - the
    code they ablate is deleted. Superseded by R9A1 in the round-9
    ablation set; not rewritten because it is the round-8 record.
  - The round-8 receipt sentence "say so if any of them should be
    separate" is gone with the mint; its replacement is the ask, which
    is a question rather than a disclosure.

CANARY (tier-3 debt from round 8 was already paid; this is round 9's
own): Sunny_V3 on PID 34352 (started 17:17:58, last app edit 17:17:0x,
ONE listener verified) - system_run_complete, 267s, 18 GPT calls 0
errors, workbook built, delivery record #4 written and bound to the
canary draft (verified in workbook_deliveries by draft_id, not
filename). Prove: 55 legs, 48 behavioural, 5 structural-absence, 2
golden, 0 DRIFT, 0 UNEARNED, verdict GREEN.

STILL NICK'S, UNCHANGED: whether naturalization may touch a
deterministic receipt at all. Round 9 adds the sharpest data point
yet ON THE RESTRICTIVE SIDE: the naturalizer did not merely soften a
receipt, it MANUFACTURED one from the user's message when handed a
no-write turn (the F1 mechanism). My fix removes the naturalizer only
from no-write turns, which is defensible without the ruling; turns
WITH writes are still naturalized, and the live L1-t1 reply shows it
paraphrasing accurately. The ruling still governs that half.


## CW-031 ROUND 10 -- membership is data, the match speaks, every line named
(VS, 2026-08-13, turn 12. Evidence: Test Files/_redproof_cw031_round10_fixes.py
(pre-fix RED on all three checks for the documented reasons, post-fix GREEN;
green run saved as _redproof_cw031_round10_20260813.txt); mini's own
instruments re-run green: _mini_cw031_r9_coherence_attack.py O1-O4 CLEAN (O2
was RED), _mini_cw031_r9_f1_residue.py CLEAN with B1 speaking the match
(_rerun_mini_r9_f1_residue_20260813.txt), _mini_cw031_r8_net_attack.py 9/9;
_canary_cw031_round10_sunnyv3_20260813.txt; _prove_20260813_vs_round10.txt
57 legs 0 DRIFT 0 UNEARNED GREEN.)

FIX 1 -- MEMBERSHIP IS DATA, NOT A LABEL PARSE (mini's O2). The group
door now stores the normalized member list beside the label
(cogs_cost_structure_group_members, written wherever the label is
written, popped wherever the label is popped - separation and retire
both). The coherence pass reads MEMBERSHIP FROM THE STORED LIST and
compares it to the carrying set directly; the label is display only.
'Design + Build'+'Plant sale' now survives its own declaring call
(pre-fix it retired itself in the same call) and still retires
correctly when a member genuinely walks out (redproof C1b). Two edges
handled explicitly:
  - LEGACY FALLBACK: rows stamped label-only (R39's cursor-stub rows,
    any group stored before this round) have no member list; for those
    the pass still parses the label with split('+') - identical to
    round-9 behaviour, proven by redproof C1c and by R39 passing the
    full prove unchanged. The fallback is only reachable by rows the
    new door did not write.
  - DISAGREEING CLAIMS RETIRE: rows carrying one label with different
    stored member lists are an incoherent claim and retire as a set.
mini: this unblocks the '+'-tooth you planned for R39 (your round-9
TASK said you would add it after my fix; the door now emits the member
list your tooth can bite on).

FIX 2 -- A MATCHING RESTATEMENT GETS A MATCH-ON-FILE SENTENCE (mini's
B1). On the no-write claim branch (the one that shipped the
failed-change sentence), when EVERY figure the client stated matches a
stored numeric leaf, the deterministic ack is now "That matches what I
have - current revenue is $1,553,000." - field named from the stored
leaf, value from the stored row, state untouched. No naturalizer
involved; the sentence ships verbatim on the no-write tail exactly as
round 9 ruled. TWO STATED LIMITS, deliberately chosen, mini should
judge both:
  - _MATCH_ON_FILE_FLOOR = 1000: figures below 1000 never earn the
    match sentence, because 45 can be a percent, a price, a capacity
    or a headcount, and matching it to an unrelated stored leaf would
    CLAIM a confirmation the client never made - the round-8 lesson
    (value equality is not declaration) applied to the match sentence.
    A small-figure restatement keeps the failed-change register:
    imperfect wording, never a false claim. If you judge the floor
    wrong-shaped, say what should replace it.
  - The scan covers financials_json + ops_json (the same state dict
    the dropped-request branch reads). A client restating a
    people_json figure (owner pay) still gets the failed-change
    sentence today; flagged rather than silently widened.
Live green on the real path: B1 clone speaks the match, stored figure
byte-unchanged (float dust and all); A1-A4 blend wordings unchanged
(3 landed / 1 honest floor), B2 question turn still quotes back.

FIX 3 -- EVERY SEPARATED LINE IS NAMED (polish). The renderer's
separated[:3] slice is gone: all separated lines are named with an
Oxford join ('a, b, c, and d'); the list is bounded by the product
directory so there is no cap to hide behind. Redproof C3.

CANARY (round 10's own, on the post-fix server): backend restarted via
start_persona_backend.ps1 - old listener 34352 killed, PID 30228, ONE
listener verified by the script's own fatal check. Sunny_V3
system_run_complete, 430s, workbook built, delivery record #5 written
and bound by draft_id; resolve_workbook_for_draft returns basis
delivery record for the canary draft. Zero tracebacks in the server
log; one known-class WARNING (workbook_model_status_check_skipped,
excel_com_failure Call was rejected by callee) - the same intermittent
Excel COM transient appears in 24 prior persona logs back to 07-30,
including green-canary days, and is not new to this change. Prove:
57 legs, 50 behavioural, 5 structural-absence, 2 golden, 0 DRIFT,
0 UNEARNED, verdict GREEN - R38/R39 untouched and passing.

STILL NICK'S, UNCHANGED: whether naturalization may touch a
deterministic receipt. Nothing this round moves it - both new
sentences (the match ack and the full separation list) are
deterministic and ship verbatim on the no-write tail; write-carrying
turns are still naturalized, still governed by the open ruling.


## CW-031 ROUND 11 -- a match never lies about the field, identity is the member set
(VS, 2026-08-13, headless turn. Evidence: Test Files/_redproof_cw031_round11_fixes.py
(12 checks GREEN); Test Files/_redproof_cw031_round11_ablate.py -- 5 ablations,
each red on its own checks, none decorative, restore proven
(_redproof_cw031_round11_ablate_20260813.txt); mini's instruments re-run:
_mini_cw031_r10_match_attack.py A-cases green under the new law (A1/A2
re-pointed by VS, header says so), _mini_cw031_r10_retire_attack.py CLEAN --
O1 both collided groups SURVIVE, O2 fresh survives / stale twin retires
alone, O3/O4/O4b unchanged; _canary_cw031_round11_sunnyv3_20260813.txt;
_prove_20260813_vs_round11.txt 58 legs 0 DRIFT 0 UNEARNED GREEN.)

FIX 1 -- D1, A MATCH NEVER NAMES AN AMBIGUOUS FIELD. _figures_all_on_file
now collects EVERY leaf whose value matches and names a field only when
exactly ONE DISTINCT leaf name matches; two or more distinct names return
leaf None and _spoken_on_file_match speaks the bare value with no field
claim ('$9,800 on file' -- always dollared, the floor is 1000 and figures
that size are money). Same name under multiple paths still names (the
distinct-NAME rule, not a leaf count -- 1c). Ravenwood's rent==interest
now gets 'That matches what I have - $9,800 on file.' KNOCK-ON, honest:
mini's W5 wage confirmation loses its field name too -- annual_wage
mirrors under year1_payroll_amount (mini's own W5b showed both), so the
wage now speaks bare. That is the law working: the app cannot know which
of two same-valued leaves the client meant, and naming either is a claim.

FIX 2 -- D2, THE TOLERANCE IS FLOAT DUST ONLY. max(0.5, 0.005*|v|) ->
max(0.5, 1e-9*|v|), exactly mini's constant. Exact restatements and
1552999.999999999-style dust still match; 1,548,000 vs stored 1,553,000
(0.32% off -- a CORRECTION) no longer claims a match and keeps the honest
failed-change register. Only the match scan changed; the unrelated 0.5%
in _prose_acks_unwritten_figure's echo detection is a different rule
(catching the app CLAIMING a figure, where wide is safe) and untouched.

FIX 3 -- D3, IDENTITY IS THE STORED MEMBER SET. The coherence pass no
longer treats one label as one claim: carrying rows are PARTITIONED by
stored member frozenset; a partition whose stored set exactly equals the
names of the rows carrying it is a TRUE claim and survives; only failing
claims retire. Label-only legacy rows attach to the unique partition
whose claim covers their name (O3's agreeing-mixed survives), fall back
to the label parse only when NO listed partition exists under the label
(pure-legacy coherent groups survive, incoherent ones retire), and
retire ALONE when unhomed (the renamed-after-grouping stale twin, O2).
Mini's O1 collision -- 'A+B','C' vs 'A','B+C' on one label -- now yields
two coherent partitions and BOTH survive; the O4b one-row-wearing-a-
two-member-claim still retires. One deliberate judgment CHANGE at the
legacy tier, flagged for mini: a legacy-only label whose carrying set
includes one off-claim row used to retire the WHOLE label set; now the
off-claim row retires alone and the coherent remainder survives --
consistent with retire-only-failing-claims, but it is my reading, not
mini's ruling.

ABLATIONS (5, each red on its own checks): tolerance back to 0.5% ->
2b/2c red; first-leaf naming restored -> 1a red; identity back to
one-partition-per-label -> 3a red; stale row attaches instead of
retiring alone -> 3b red; legacy parse fallback removed -> 3d red.

CANARY (round 11's own, post-fix server): backend restarted via
start_persona_backend.ps1 -- stale listener 34536 killed, PID 12544,
ONE listener verified by the script's own fatal check, started
20:38:40, postdating the last intake_consult.py edit. Sunny_V3
system_run_complete, 471s, ZERO Traceback/ERROR lines in
_logs_persona_20260813_203840.txt, workbook built, delivery record #6
written and bound by draft_id; resolve_workbook_for_draft returns
basis delivery record for the canary draft. Prove on final code: 58
legs, 51 behavioural, 5 structural-absence, 2 golden, 0 DRIFT,
0 UNEARNED, GREEN -- R40 held through the D3 rewrite untouched.

STILL NICK'S, UNCHANGED: whether naturalization may touch a
deterministic receipt. Nothing this round moves it -- all three fixes
are deterministic-sentence or state-coherence changes, which is
exactly why they were fixable in code without the ruling.

================================================================================
CW-031 ROUND 12 -- mini's two legacy-tier fixes from the round-13 audit
================================================================================

Both fixes live in the coherence pass's legacy handling
(python/api_handlers/intake_consult.py, the partition loop formerly at
~3182-3201). App-code change is ONE file, two hunks.

FIX 1 -- THE LEGACY TIER IS A LAW, NOT AN ACCIDENT OF ORDER. I took
mini's SHAPE (a): the parse-fallback partition is derived from the LABEL,
once per label, BEFORE any row is looked at (created empty when no
members-carrying partition exists under the label), and legacy rows join
it exactly the way they join a listed partition -- by their name sitting
in the key. The old `elif not _parts` branch -- whichever legacy row
iterated first minted the partition and joined it even off-claim -- is
GONE, not routed around; there is now a single attach rule for both
partition kinds.

WHY (a) AND NOT (b): deleting the fallback outright would retire every
pure-legacy coherent group on its next unrelated write -- a claim that
HOLDS when read -- which contradicts the ratified retire-only-failing-
claims principle. Shape (a) keeps that principle for legacy data, keeps
my redproof 3d/3e AND mini's T1a as written, and still satisfies the
remove-legacy law's spirit: the order-dependent branch is deleted, and
what remains is one law. The label parse survives ONLY in the pure-
legacy tier where no member data exists to consult -- R40's deliberate
'+' limit, unchanged and documented in the code comment.

FIX 2 -- A LEGACY ROW NEVER ATTACHES TO A PARTITION THAT ALREADY
CARRIES ITS NAME. The attach condition now refuses when the row's name
is already present on ANY row in the target partition. Mini's rule said
"a members-carrying row"; I made it any-row deliberately, so a SECOND
same-named legacy twin cannot ride in behind a first legacy attach
either. T2's duplicate-name twin ('Alpha' in the other LOB) now goes
stale and retires instead of keeping the group it never earned.

RESIDUAL ORDER NOTE, flagged honestly for mini: when TWO same-named
legacy rows compete for one on-claim slot (pure-legacy tier, duplicate
name, both in the parsed key), the first in document order attaches and
the second goes stale. The partition-level outcome is identical either
way (same surviving name set, one twin retired); WHICH twin keeps the
label follows row order. Census reach today: 0 label-only rows at all,
so this is a documented edge, not a live path. If mini wants both
refused instead, it is a two-line change to the guard.

ALSO WORTH KNOWING: when every legacy row under a label is off-claim,
the pre-created parse partition ends the pass EMPTY; an empty partition
retires nothing (its row list is empty) and the off-claim rows go stale
exactly as before. No behaviour rides on the empty container.

PROOFS (red for the right reason, then green):
  _redproof_cw031_round12_prefix_20260813.txt   pre-fix HEAD: T1b and T2
    red on exactly their own reasons, T1a/T3 green -- mini's probe IS the
    red-proof for this round.
  _redproof_cw031_round12_ablateA_20260813.txt  duplicate-name guard
    ablated alone -> T2 red ALONE.
  _redproof_cw031_round12_ablateB_20260813.txt  order law ablated alone
    (old elif restored) -> T1b red ALONE. Neither guard is decorative.
  _redproof_cw031_round12_postfix_20260813.txt  final code: 4/4.
Instruments re-run UNMODIFIED on final code: my round-11 redproof 12/12
(3d/3e as written, per shape (a)'s promise), mini's round-10
retire_attack CLEAN and match_attack mechanisms verified.

CANARY (round 12's own, post-fix server): backend restarted via
start_persona_backend.ps1 -- stale listener killed, listener PID 21208
started 21:26:36, postdating the last intake_consult.py edit (21:25:53),
ONE :5050 listener verified. Sunny_V3 system_run_complete, 369s, ZERO
Traceback/ERROR lines in _logs_persona_20260813_212636.txt, workbook
built, delivery record #7 written and bound by draft_id;
resolve_workbook_for_draft returns basis delivery record for canary
draft 4ee6d16682b742c095a32ff9da510433. Prove on final code
(_prove_20260813_vs_round12.txt): 60 legs, 53 behavioural, 5
structural-absence, 2 golden, 0 DRIFT, 0 UNEARNED, CLEAN -- R40, R41,
R42 all held untouched through the legacy-tier rewrite.

STILL NICK'S, UNCHANGED: whether naturalization may touch a
deterministic receipt. Nothing this round touches prose at all.

## CLOSED, NOT OPEN: the naturalization question (VS housekeeping)
The item carried forward as "STILL NICK'S, UNCHANGED: whether
naturalization may touch a deterministic receipt" was RULED at the
round-8 boundary and is landed as a design law above (## DESIGN LAW:
PROSE IS A VIEW OF THE RECEIPT, NEVER A COMPUTATION, ~line 1817):
prose renders the frozen receipt, never re-derives; a missing number
is a receipt gap, never license to source elsewhere; mini verifies
spoken == written, provably. STOP CARRYING IT FORWARD as open.
Agents: an open-questions ledger entry must be checked against the
design-laws section before it is copied into a new round summary -
inferring "still open" instead of reading the declared answer is the
parent law violated in miniature, by us.

## CW-032 LIVE FINDING (Alderfen, draft 158f6816, DURING the run):
## the per-line write door exists at the WALL, not IN THE STAGE

At the cogs stage the app proposed per-line correctly (58% plants...)
and invited correction. The client answered with a textbook per-line
correction (46/73/17/3, all four lines, reasons attached) -> "I wasn't
able to apply that change yet" (HONEST - the receipt law holds). The
client retried in the door's own canonical format ("Hardgoods sale: 73
percent of that line's revenue") -> STILL nothing landed. The stage
then completed on the app's own blended proposal (0.5042, $757,862),
DISCARDING the client's stated numbers, and moved to marketing with a
self-contradicting receipt ("I'll start with direct costs of $757,862
a year (50% of revenue)... I haven't recorded cogs percent of revenue
yet").

ROOT CAUSE (from the stage spec, not inference): the financials-stage
router vocabulary for cogs is (current_cogs, cogs_total_year1,
cogs_percent_of_revenue) - NO line-scoped field. The CW-031 write door
and all of mini's live L-checks operate at the DONE surface; the stage
flow never got the door. The one surface where the per-line proposal
is made and correction is invited is the one surface that cannot
receive it.

WHAT THE BATCH DID FIX, visible live: no false receipts (two honest
refusals where Ravenwood got a confident "Got it"), and the proposal
itself is per-line with bands. What remains: THE STAGE DOOR. Expect
the client to possibly land the correction later at the wall (where
the door works) - if so the artifact may still end per-line; watch
the run to terminal before verdicting.


## CW-032 TURN 1 (VS, 2026-08-14): the eight-item batch - what landed, where, and what moves

### TIER 1 - A-110 IN-STAGE (#140/#142, the three-blocker root)
ROOT CAUSE, found by red-proof (not the one the notes guessed): the
financials consult type's hand-maintained allowed-fields list
(intent_router.py ~1651) NEVER carried the three per-line COGS keys. The
unified (wall) list gets them from the schema keys; the stage flow's list
was written by hand and never updated - so the one surface where the
per-line proposal is made had NO vocabulary to land a per-line answer,
and the prompt hard-constrains patch keys to that list. Secondary: the
narrow-stage rule (edit_patch for the narrow stage fields only)
funnelled per-line replies into blend fields, where 46 died at the
not-a-fraction guard and dollar conversions died at the derivability
guard - hence Alderfen's honest-but-useless refusal.
FIX (one router change + its stage-side completion):
  - the three keys added to the financials allowed list (multi-line gate
    at ~1781 still drops them on single-line drafts);
  - the narrow-stage rule carries an explicit per-line exception; the
    per-line block outranks the narrowing and covers the
    proposal-on-the-table case (four percents in one message = four
    entries, never confirm_proceed);
  - IN-STAGE COMPLETION (intake_consult, after the stage cogs door): a
    per-line answer rating EVERY line completes the cogs stage through
    THE RECALC's own _pl_derived derivation - client numbers, never the
    app's blend. Partial answers keep the stage open;
  - CLARIFIER (tier 1c): _build_financials_stage_clarifier now takes
    ops_json; on a multi-line draft the cogs recovery question keeps the
    per-line shape and NAMES the still-missing lines;
  - RECEIPT LAW (tier 1d, #143): _unapplied_fields_note splits
    active-stage fields (I could not apply your X change - the figure
    above is what I have) from future-stage fields (we will get to
    that); the Also-recorded formatter renders ratio-basis fields as
    percents (the cogs-percent-$1 bug); and the _prose_claims_figure
    deterministic tail no longer says it has not recorded a figure on a
    turn whose DOOR receipt just recorded it (found live by my own S3
    scenario - the last words-vs-state contradiction in the reply).
LIVE PROOF (_live_cw032_instage_cogs_turn.py, 15/15 GREEN twice, file
_live_cw032_instage_20260814.txt): clones of the REAL Alderfen draft
rewound to message [74] (the proposal on the table), live :5050, live
GPT router, the client's own transcript words. S1: all four rates in ONE
message -> rows carry 46/73/17/3, stage completes at $634,545 (42%)
derived, reply = receipt + roll-up + next question. S2: the collapse
sentence -> shared:hardgoods sale+plant sale stored on exactly the two
named rows, basis declared, IN-STAGE (closes A-111/#142). S3: one line
-> that row written, recovery names the three missing lines.
Router red-proof: Test Files/_redproof_cw032_stage_perline_router.py
(RED pre-fix on all three wordings - blend fields only; GREEN post).

### LAYOUT (#141, Nick's ruling)
finmo_sheet.py: per-line P&L rows DELETED; the ONE Cost of Goods Sold
cell is now the roll-up - Sigma over slots of
(Model Inputs line Revenue x Model Inputs line COGS %), e.g.
='Model Inputs'!D11*'Model Inputs'!D10+'Model Inputs'!D16*'Model Inputs'!D15
The drivers were ALWAYS on Model Inputs (LOB / Product - COGS %,
linked from Revenue Drivers) - the ruling removed the P&L detail rows,
nothing else. Single-line drafts render the exact legacy shape
(=D8*'Model Inputs'!D16 verified on a fresh export).
_assert_workbook_cogs_rows (issue_registry.py) now pins the NEW law:
ONE P&L row, zero per-line P&L rows (old layout now FAILS), >= N driver
rows on Model Inputs, the cell IS the N-term roll-up, reconciliation
unchanged. Proven pass on the new-layout export, fail on an old
per-line-P&L workbook and on a degraded no-driver workbook, each for
its own reason. Dead _assert_total_sums_over_lines + _SUM_FORMULA_RE
deleted (remove-legacy law).

### TIER 2 - A-113 (#264)
The three Alderfen false receipts happened at MARKET focus, where turns
NEVER reach route_intent (model-interpreted every turn) - the section
GPT acknowledged freely, nothing landed, and the build smeared a uniform
1.1122 reconcile factor across all four lines' capacity. FIX: the
existing cross-section driver applier (CW-017 b, financials focus) now
runs BEFORE the market/people section turns; a landed write persists
immediately (ops + recalc'd financials + year1) and its deterministic
receipt LEADS the reply; a correction-shaped message that cannot land
gets an honest refusal note. Fixing it exposed a WRONG-NUMBER defect in
the applier itself: last-figure-wins parsed the real [47] sentence
(...should be 7. I was thinking of two crews and we have been running
three...) into capacity 3. Value selection is now (a) sentence-scoped
(the lever sentence + its follower - Target 35 to 75 cannot compete),
(b) not-N excluded as the old value, (c) marked (should be/to/is/now/at),
refuse on ambiguity. Six-case offline proof in the commit. NOTE for a
later round: the unit_price branch still uses cands[-1]; same class,
untouched this turn to keep the change auditable.

### TIER 3 - #266 (A-114)
finmo_bridge: opening PPE seeds a placed_quarter-0 vintage on the same
default 5y straight-line schedule as new capex. Verified on the REAL
Alderfen model_input: Q1 depreciation 19,406.92 = 386,000/20 + the
106.92 the old code produced alone; the opening base fully depreciates.
The assumption is STATED on the CapEx & Depreciation sheet subtitle
(Existing equipment and new capital spending are depreciated
straight-line over 5 years). No intake question added, per the ruling.
THIS MOVES EVERY DRAFT WITH OPENING ASSETS: net income, taxes, retained
earnings, balance sheet. It is the cause of the R31 DRIFT below.

### TIER 4
#265: the MISROUTE GUARD in _normalize_financials_router_patch - a write
to a COMPLETED stage's field reverts when the message names the ACTIVE
stage's family and never the foreign one
(_FINANCIALS_FAMILY_KEYWORDS_BY_FIELD_GUARD; fail-open - unlisted fields
are never guarded). Three-shape unit proof: the Alderfen misroute
reverts; the repair wording and the volunteered debt cluster land
untouched.
#267 (minor, receipt header vs another line's price): NOT fixed -
no reproduction from the filing (final stored state was correct); the
capture_receipt naming path reads correct on inspection. Left open with
the transcript turn as the reproduction seed.
A-103: Section-6 limb SETTLED per Nick, agenda.json narrowed to the two
never-run limbs.

### VERIFICATION (all foreground, all on listeners postdating every edit)
- Sunny_V3 canary x2: 538s and 499s, system_run_complete, 0 errors,
  delivery records #11 and #13 bound by draft_id
  (_canary_cw032_turn1_sunnyv3_20260814.txt, _canary_cw032_turn1_final_...).
- In-stage live proof 15/15 GREEN (above).
- Multi-line workbook E2E (_live_cw032_multiline_workbook_e2e.py,
  _live_cw032_multiline_wb_20260814.txt): completed-Alderfen clone ->
  the client's four-rate sentence through the LIVE WALL router -> real
  system-run -> delivered workbook: FOUR driver rows on Model Inputs,
  EXACTLY ONE P&L COGS row = the four-term roll-up, Q1 depreciation rate
  0.0530, and _assert_workbook_cogs_rows PASS on the delivery-record
  binding (Sigma == blend == finmo on 21 columns). The file's first pass
  shows 8/9 with a PROBE defect (I handed the resolver a dictionary
  cursor; production uses tuple cursors) - the corrected check is
  appended and the probe fixed.
- Full prove (_prove_20260814_vs_cw032_turn1.txt): 61 legs, 54 proven
  behavioural, 5 structural-absence, 1 GOLDEN (R32 held - single-line
  formula grid unchanged), 0 UNEARNED, 1 DRIFT:
  R31 single-line-unchanged MOVED on finmo + model_input. THIS IS THE
  DEPRECIATION RULING LANDING, not a regression: Sunny carries opening
  assets, so its finmo numbers legitimately changed. R31's golden SHAs
  need re-baselining (mini's; ratify the new numbers first). The
  single-line byte-floor golden values in
  _prove_single_line_byte_floor.py's docstring move for the same reason.

### FOR MINI, EXPLICITLY
1. R31 re-baseline after ratifying the depreciation delta (the ONLY
   drift; R32 held golden).
2. Any leg pinning exact finmo values on a fixture with initial_assets>0
   will shift the same way - re-pin from ratified numbers, do not soften
   assertions.
3. The workbook law legs / R32's stated multi-line expectation (one
   Cost of Goods Sold - LINE row per line plus a total =SUM) pin the
   OLD layout - re-point to the ruled one: N driver rows on Model
   Inputs, ONE P&L roll-up row, no per-line P&L rows.
4. The in-stage door, the stage completion, the capacity-door surfaces
   and the misroute guard are all pin-worthy legs; my red shapes are in
   the two _live_cw032_* scripts and the router red-proof.


## CW-033 TURN 1 (VS, 2026-08-14): A-113 capacity write path + A-115 kind-misreads + discovery spec

Evidence base: Thornfield draft d9b17850, the A-113/A-115/A-112 filings
(cowork_tester/agenda.json v19), turns [99]/[107]/[111] (capacity),
[89] (capex), [75]-[78] (cogs-rate-as-price), [10] (ack contradiction).
Commit 6911cb8 (fixes + proofs), this section's commit (spec + notes).

### TIER 1 - A-113: WHY three receipts and zero writes (the full mechanism)
FOUR stacked defects, each proven red then fixed:
1. THE MISSING DOOR. The financials INTERVIEW region (intake_consult
   ~15898) calls _run_financials_turn_and_sync and returns; the
   cross-section driver applier was wired into the market/people section
   turns and the LATE focus==financials branch (~18392) - a region
   stage-interview turns never reach. So no capacity correction spoken
   at a financials stage question ever met the applier. FIX: a wrapper
   with the old name runs the applier FIRST for every interview turn,
   persists a landing immediately (ops + RECALC + year1, mutate-through
   per the Fernhill seam law), and its receipt LEADS the reply.
2. THE FABRICATED RECEIPT. With the applier out of reach, the CW-026
   forward-move inference attributed the capacity figure
   (_FIGURE_FIELD_RULES), pushed a bare ops driver key through
   _apply_scoped_patch - which on a MULTI-LINE model fell through to a
   flat ops key NO reader consumes (the universal engine deleted the
   flat mirror as a home) - set landed=True unconditionally, and spoke
   'Recorded: capacity 7' from the INFERRED value. [107] spoke
   'Recorded: capacity 5' because the figure ranker picked the OLD value
   from 'currently set to five'. FIX: the ops branch resolves the NAMED
   line, READS BACK the row before any 'Recorded:', and REFUSES honestly
   (no write, which-line question) when no line resolves; the no-op
   check now reads the RESOLVED row (was: first row - which is why a
   stale-value echo could speak at all). _apply_scoped_patch now DROPS
   bare driver keys on multi-line models (logged OPS_DRIVER_WRITE_
   UNROUTED) instead of manufacturing dead landings.
3. THE APPLIER ITSELF had three latent teeth missing, found by running
   it offline on the real wordings: (a) exact-token product match -
   'install' never matched 'Landscaping/installation job'
   ([99]/[107] returned None before leaf detection, so not even the
   refusal note fired); (b) digit-only value scan - 'needs to be seven
   jobs per week' had no candidates; (c) IT WROTE THE WRONG TWIN -
   capacity landed on units_per_period_capacity always, which for a
   weekly-cadence row is the DERIVED twin: the next canonical pass
   (_derive_capacity_cells) restored the stale week value and the
   landing EVAPORATED AT REST. The pre-fix redproof shows [111] as
   (week=5, period=7). FIX: _resolve_ops_product_line (ONE stemmed
   resolver shared with the forward move; >=2 matching lines REFUSE -
   'fix the plant and hard goods capacity' must never pick one),
   _digitize_small_words scoped to the capacity value text only, and
   the write goes to _capacity_canonical_field(row cadence) + derive.
4. FOUND BY THE LIVE PROOF, fix within the hour: with the applier
   landing, the forward move was STILL free to land OTHER stray figures
   on ops rows in the same turn - live, [99]'s 'one thing I need to
   fix' put capacity 1 on the just-corrected install row, and [111]'s
   volunteered 'Accounts payable about 121,000' landed as install
   capacity 121,000 (the AP figure is future-stage, therefore unlanded,
   and the message contains 'capacity'). FIX: _strip_suppressed_ops_move
   - on an applier-TRIGGERED turn (landed or refused) ops-key forward
   moves are stripped; the applier's consumed figures (new value, old
   value, not-N values) also ride into every disclosure call as
   references. Non-ops moves untouched.

THE SMEAR HALF: the uniform 1.106527 is deterministic_revenue_proposer
anchor_scale = stated-Q1 / bottom-up-Q1 applied to EVERY line's Q1
capacity (and finmo_bridge stub_scale_factor, same ratio, stub column).
With the write path fixed the Thornfield factor is 1.00105 - but that
still rewrites four declared capacities by 0.1%. RULED SHAPE per the
task text (never a silent smear; mini verifies 'no uniform factor
anywhere'): a 0.5% epsilon on BOTH (declared drivers stand under
estimate-rounding gaps; Q1 anchors to their own bottom-up), and a
MATERIAL factor still governs (stated revenue is also a declared
number) but is STAMPED into the drivers as anchor_reconcile{factor,
basis, applied_to} - visible to any reader, never silent. The epsilon
value (0.5%) is mine to defend: it matches the derivability tolerance
used at the ops lever guard. If Nick wants material gaps to REFUSE at
intake instead (the coherence fence's vocabulary), that is a design
call I did not make - flagged in the RESULT.

### TIER 2
1. COGS-RATE-AS-PRICE (A-115a): _FIGURE_FIELD_RULES mapped \brate\b ->
   ops.unit_price, so 'one shared rate at 58 percent' forward-moved 58
   into a price receipt + the WS2 retention stamp (the door stamps
   retention on unit_price landings; the dead flat write meant no price
   actually changed, which is why stored prices survived). FIXES:
   \brate\b removed from the price rule ('rate per <unit>' stays); a
   percent-shaped figure now gets NO forward move at all (it would
   otherwise have fallen through to the REVENUE rule via 'percent of
   revenue' - worse); figures the per-line COGS door consumed this turn
   (written + grouped rates, ratio and percent forms) are disclosure
   references; the small-figure restatement check reads EVERY row's
   stored value (was: first row - 'my prices are still 52/95/2400' on a
   four-line model read as a 95 price change). Retention now cannot
   stamp without a real landed price write (read-back gated).
2. CAPEX EXPLICIT-NO (A-115b): _normalize_financials_router_patch gains
   a current_capex branch - a negative-lead answer with the figure
   expressly excluded (patterns for 'none of it', 'over the years',
   'not this year'...) stores 0; 'No wait, it was 380,000' is protected
   by a lookahead and lands. The excluded figure becomes a reference
   via _capex_answer_expresses_none recomputed IN the disclosure (a
   transport key was tried first and failed live: the first disclosure
   call popped it, a later call in the same turn then proposed 380k
   into rest-of-team payroll - the nearest-stored inference. Recompute,
   not transport). Live [89] verbatim: capex 0, nothing else captured,
   the next question asks equipment worth once.
3. ACK CONTRADICTION (A-112): the unapplied-fields note at the edit-
   receipt path is composed BEFORE the section consultant's own patch
   applies - [10]'s note claimed capacity+price unrecorded, then the
   followup patch recorded both into the same reply. FIX at the source:
   the dropped list + an ops/fin snapshot are stashed at composition
   and the note is RE-VALIDATED against the post-followup state at the
   merge point; fields whose stored values changed since composition
   are dropped from the note (all of them -> note removed). Offline
   unit coverage is impossible (the path lives mid-handler); the
   mechanism is snapshot-diff, deterministic. MINI: this is the one fix
   with no live artifact this turn - drive an ops-section multi-line
   capture whose router patch drops driver fields and read the reply.

### LIVE PROOF (_live_cw033_capacity_turns.py, _live_cw033_20260814.txt)
Clones of the REAL Thornfield draft rewound to [99]/[107]/[111]/[89]/
[75], live :5050 + live GPT router, client's own words, GREEN:
all three capacity shapes land install 7/7 with the other rows
byte-equal and the ack speaking 7; the no-line-named correction writes
NOTHING and asks which line; [89] stores capex 0; [75] stores the 58%
collapse group with no price echo and retention_pending ABSENT.
The debug rerun (_cw033_l1_debug.py) shows the full [99] turn: applier
ack leads, the bundled $3,100 lands with its own receipt, the next
stage question rides. NOTE for mini: in one L1 run the router's stage
prose came back EMPTY (reply was the applier ack alone, values still
landed) - GPT variance on the stage half, not a write defect; and the
router occasionally echo-writes install's existing 0.17 cogs rate
('Recorded: ... at 17%' on a message that never says 17) - same-value
echo, words match state, but it is receipt noise worth a look.

### PROOFS ON DISK
_redproof_cw033_prefix_20260814.txt  - pre-fix tree (git stash): RED,
  16 checks failing each for its filed reason (incl. the [111]
  week=5/period=7 evaporating twin).
_redproof_cw033_postfix_20260814.txt - fixed tree: GREEN (35 checks).
_live_cw033_20260814.txt             - live GREEN (above).
_canary_cw033_sunnyv3_20260814.txt   - Sunny_V3 on a listener postdating
  every app edit (ONE listener verified at each of three restarts):
  system_run_complete, workbook built, zero error lines. Three canaries
  were run this turn - one after each app-code change.
_prove_20260814_vs_cw033.txt         - full prove on FINAL code: 61 legs,
  54 proven behavioural, 5 structural-absence, 2 golden, 0 DRIFT,
  0 UNEARNED, 0 other failures, CLEAN.

### WHAT THE FIRST PROVE CAUGHT (two rounds of my own medicine)
The first full prove ran R01/I01 (completed-financials freeze /
forward-move price, the CW-026 no-dead-end law) RED at HEAD - my
multi-line discipline had re-created the outlawed freeze on two shapes:
1. ROW-LESS legacy flat models: the refusal refused drafts where the
   flat key IS the home. Fixed: refusal requires MORE THAN ONE product
   row; zero rows keeps the flat landing, read-back added (123f532).
2. SINGLE-ROW models (the actual R01/I01 Sumac draft 2ecc759c - one
   'Property contract' row): 'my unit price is now 650 instead of 520'
   carries the marker INSTEAD, triggers the price leaf, resolves no
   product name ('unit'/'price' match nothing), and the wrapper then
   SUPPRESSED the forward move behind the refusal - a freeze with extra
   steps. Fixed: one product row means there is nothing to
   disambiguate; the applier lands on it without a name. The final
   prove has both legs back to PROVEN.
LESSON FOR THE AUDIT: the refusal discipline is exactly one-line-vs-
many; mini should attack the boundary (a single-row draft whose message
names a DIFFERENT product than the row - the applier will land it on
the one row, which is the CW-026 worst-case-a-correctable-proposal
contract, but say so if you rule otherwise).

## CW-033 TURN 1, PART 2 - NICK'S MID-TURN RETRACTION (HANDOFF_INBOX, 2026-08-14)

### THE GUIDED-FLOW PRINCIPLE (recorded as a design law, per Nick)
Guided flow bounds reachable SEQUENCES - off-path sequence bugs (moves
the app never invites, e.g. revisiting a closed stage's per-line
drivers) are PREVENTED, not supported. Honesty within any answer the
app SOLICITS is ALWAYS in scope. Cowork reclassified all 24 open
issues under it: 22 on-path, 1 retracted (A-113), 1 flagged (A-116).

### A-113 RETRACTED - what was removed, what stays, and why
REMOVED (the in-flight post-stage capacity write machinery):
- the interview wrapper no longer APPLIES the driver applier; it
  DETECTS a correction-shaped ops-lever message mid-interview and
  prepends an honest REDIRECT ("I haven't changed any operations
  <lever> from here - those numbers were set in the operations step"),
  with ops forward-moves suppressed for that turn so no back-door
  landing or fabricated receipt can ride the same message. At the WALL
  (no active stage) nothing changed - corrections there are invited
  and the standing CW-026 machinery handles them.
- the 0.5% reconcile epsilon in the deterministic proposer AND the
  finmo stub factor is REVERTED - Nick ruled the reconcile-to-stated-
  revenue (capacity absorbing the factor) is BY DESIGN. The
  anchor_reconcile provenance stamp STAYS (visibility of a designed
  mechanism, not behavior; drop it if ruled otherwise - one hunk).
KEPT (honesty within solicited answers - always in scope, and TASK 3
orders exactly these): every A-115 fix, the ack-contradiction note
re-validation, the forward-move read-back/refusal/row-resolution (no
fabricated 'Recorded:' anywhere), the scoped-patch dead-flat-write
drop, the applier hardening (it still serves the CW-017b/CW-032
surfaces), the single-row bypass and legacy-flat landings (R01/I01).
LEFT FOR A RULING, not removed by me: the CW-032 market/people section
applier wiring (#264) and the late focus==financials applier call
(CW-017b) are PRE-EXISTING Nick-approved landing machinery for the
same off-path family - the retraction names only the in-flight turn's
build, so I did not rip out prior-approved code without an explicit
order. If the guided-flow law means those go too, that is a one-turn
removal; say the word.
NOTE: commit b438b0b accidentally swept an intermediate HANDOFF_INBOX
revision into history (it was staged by the inbox flow mid-turn). No
content was lost; the current inbox is newer and untouched by me.

### A-116 ADJUDICATED (TASK 1) - ON-PATH, and already fixed + pinned
The flagged issue is flow:financials:correction_consumed_as_pending_
stage_answer (CW-025, #115: a standalone PAYROLL correction consumed
as the pending CAPEX question's answer and stored as zero). RULING:
ON-PATH, on the app's own written contract, cited:
1. _normalize_financials_router_patch (intake_consult.py, the
   corrections-admitted block): "CORRECTIONS ARE ADMITTED (issue #23):
   the narrowing's job is to stop answers landing in FUTURE fields
   (misroutes), never to reject a correction to a field the client
   already deliberately captured. A field is correctable when its
   owning stage is already COMPLETE." Payroll's stage is complete when
   capex asks - the app DECLARES the move supported.
2. docs/INTAKE_FLOW_CONTRACT.md (CW-025, Nick-approved): no turn
   returns before the router runs; corrections land mid-interview by
   construction.
3. The misroute guard #265 (CW-032, Nick-approved) exists solely to
   protect this admitted move from landing on the wrong field.
4. Contrast the A-113 boundary: nothing in the ops/financials copy
   invites revisiting a closed stage's PER-LINE DRIVERS; but
   correcting an already-captured FINANCIALS/PEOPLE figure is invited
   by the design itself (and the cogs-stage copy literally says
   "Correct any of them on their own").
So: a correction sent while a stage question is pending is a supported
sequence; consuming it as the pending answer was a real bug. It is
ALREADY FIXED AND PINNED - registry #115 is resolved (retested_clean),
regression-pinned by Test Files/_redproof_cw025_rank1.py R4/R5/R6 and
gate legs R02/R15 (both PROVEN in this turn's clean prove). No new
build owed. A-116's other ask (a path-classification field on new
filings) is Cowork's board machinery, not app code - left to Cowork.

### THE REAL BOARD (TASK 2) - confirmed against agenda v20 + registry
Nick's list is CONFIRMED with two additions and one nuance:
- A-115 (rank 1) - the two kind-misreads - CONFIRMED top priority, and
  BOTH ARE FIXED THIS TURN (built before the re-scope arrived, live-
  proven L5/L6 + offline T7/T8): cogs_rate_read_as_unit_price... and
  explicit_none_answer_overridden... both still read status=open in
  the registry - they close on artifact evidence per the CW-031 gate,
  which is mini's audit + the next run.
- A-112 receipt fidelity (rank 2) - the ack-contradiction fix this
  turn addresses its named recurrence; the rest is observational.
- A-106 retention probe (rank 3) - needs the priced-below-market
  business; unreachable by healthy shapes, unchanged.
- A-079 (rank 4) and A-103's two never-run limbs (rank 5) - Nick's
  list omitted these; they remain open on the agenda.
- CW-023 owner-pay (owner_pay_correction_not_rolled_into_payroll_
  total): status resolved/observational - "unverified, needs a
  completed build" is exactly right under the artifact gate.
- ADDITION: verdict:wall:owner_draw_ceiling_offered_is_the_whole_
  team_payroll_ceiling is OPEN/major in the registry and on nobody's
  list - flagging it so it is not orphaned.
- HYGIENE: the A-113-family registry rows (capacity_correction_after_
  stage_close_never_lands, blocker x2; ack_claims_a_capacity_write...,
  major) predate the retraction and still read open-blocker; the board
  reclassification lives in Cowork's agenda, but the registry rows
  need the off-path/observation stamp - Cowork's or mini's call.

### KNOWN ADVERSARIAL EDGE, handed forward (capex, small)
A negative-lead capex answer that ALSO states a real purchase ("No,
none of it was bought this year - but we did spend 15,000 on a mower
in January") would be forced to 0 by _capex_answer_expresses_none.
Fix shape: a but-we-did carve-out (`but we did|except|apart from|
other than`) before the override. Not built - flagged for the next
turn or mini's audit.

### TIER 3 - DISCOVERY SPEC (research only, nothing built)
docs/STREAM_DISCOVERY_SPEC.md. Shape: category knowledge = business
type + NAICS keying a GPT judgment in the demand-judge pattern
(validator-enforced fences, Python-computed thin-evidence -> NO ask);
fires ONCE at end-of-ops via a deterministic existence-question
template (GPT fills only stream labels, 'consider adding' is
unrepresentable); dedup against captured lines uses the same stemmed
resolver as A-113; a yes lands through the line-split confidence gate
as an ordinary product row (zero new write paths, provenance
origin=discovery_confirmed); a no is latched and never re-asked.
Five open questions for Nick are in the doc (surface, knowledge-source
ceiling, cap 2v3, pre-revenue exclusion, re-run latch).

## CW-033 TURN 2 (VS, 2026-08-14): NICK'S REVISION LANDED - forward-only law recorded, stamp ruled inert, naturalization confirmed

### THE FORWARD-ONLY LAW (design law, Nick 2026-08-14 - recorded per order)
The guided-flow principle is a DESIGN LAW GOING FORWARD, not a mandate
to re-audit existing code:
- NEW and IN-PROGRESS work respects the boundary: off-path sequences
  are prevented/redirected, never supported; honesty within any answer
  the app solicits is ALWAYS in scope.
- EXISTING working doors stay as they are. No hunting them down to
  match the new paradigm. An unreachable state is not a bug; rewriting
  working doors to enforce a boundary they are not violating is
  retrofit for its own sake.
- ONLY exception: a pre-existing door that mishandles a REACHABLE case
  (wrong value on something a client can hit on the guided path) is a
  real bug - fixed as a bug, never as consistency retrofit.
- The A-113 machinery removed in turn 1 STAYS REMOVED (just-built, not
  pre-existing).
THIS SETTLES turn 1's "LEFT FOR A RULING" item: the CW-032
market/people applier wiring (#264) and the CW-017b late
focus==financials applier call are pre-existing, working, Nick-approved
doors - they STAY. Nobody removes them under the guided-flow law.

### (b) PROVENANCE STAMP RULED: INERT / ANNOTATION-ONLY -> KEPT
Nick's condition: keep if inert, drop if it moves any value. VERDICT:
INERT. The evidence trail, every reader checked:
- WRITE: deterministic_revenue_proposer.py:204-212 - the stamp is
  attached AFTER all driver math, only when factor != 1.0. The scaling
  itself (line 155, anchor_scale) is unconditional and reads nothing
  from the stamp.
- READERS (repo-wide grep, app code): none consume it. evaluator.py:271
  reads only drivers["lines_of_business"]; revenue_authoring.py
  _extract_author_lines reads lines_of_business/quarters only and the
  write path copies only per-quarter values into model_input revenue
  rows; apply_bounded_revenue_critique (revenue_critique.py:426) dict-
  copies and rewrites lines only - the stamp rides through untouched.
- THE LOCK CANNOT RE-KEY: critique_input_hash (revenue_critique.py:78-98)
  hashes {stable compact, proposal_LINES, qoq_max, factor bounds} - the
  drivers dict (and so the stamp) never enters the hash, so response
  locks keyed before the stamp are byte-identical after it.
- Only other references: VS_NOTES, the CW-033 redproof (asserts stamp
  presence/absence - annotation checks, not value checks).
It records a designed mechanism (Nick ruled the reconcile is BY
DESIGN); it moves nothing. KEPT.

### (c) NATURALIZATION RULING CONFIRMED LANDED - and the question is CLOSED
The design law (PROSE IS A VIEW OF THE RECEIPT, NEVER A COMPUTATION -
corollary 3 of THE APP MUST NOT INVENT WHAT THE CLIENT IS THE AUTHORITY
TO DECLARE) is at ~line 1817 of this file, ruled by Nick 2026-08-13.
It does NOT resurface as an open question; the recurring "STILL NICK'S,
UNCHANGED" line in HANDOFF history predates the ruling and is DEAD.
Enforcement, verified in code this turn:
- No-write turns ship the deterministic sentence VERBATIM
  (intake_consult.py:17879-17885, CW-031 round 9) - the naturalizer
  never sees a turn with no change to acknowledge.
- _prose_acks_unwritten_figure guards both no-write ship gates; R36
  pins "a transport figure never speaks"; R37 pins "a transport key is
  consumed at its door, never stored".
- Write-carrying acks source numbers ONLY from the receipt-derived
  deterministic fallback (intake_consult.py:17890-17896); asks ride
  AFTER naturalization, re-appended verbatim (17900-17906).
- Coherence prose is STRUCTURALLY enforced: _safe_naturalize
  (section.py:2648) verifies every dollar figure and the marker survive
  verbatim, else the deterministic text stands.
- _naturalize_year_one_text (intake_consult_draft.py:1789) is a
  wording-only regex; no numbers.
NO CODE PATH RE-DERIVES A NUMBER IN PROSE - nothing computes a figure
for prose from any source but the frozen receipt. ONE RESIDUAL, named
for the record, not rebuilt (forward-only law): on write-carrying turns
naturalize_recovery also receives user_message as context
(intake_consult.py:17895), so "receipt is the ONLY numeric source" is
held there by instruction + deterministic fallback rather than by
construction (unlike the coherence path's figure-survival check). Every
live audited reply across rounds 7-9 was write-accurate. It is a
pre-existing working door with no observed reachable mishandling - it
stays; if a live run ever shows a naturalized ack diverging from its
receipt, THAT is the reachable-case bug and the fix shape is the
_safe_naturalize figure-survival guard applied to the ack path.

### BOARD ADDITION (per Nick): owner_draw_ceiling orphan
verdict:wall:owner_draw_ceiling_offered_is_the_whole_team_payroll_
ceiling - OPEN/major in the registry - is now formally ON THE BOARD
(rank below A-115/A-112/A-106, above hygiene). It was on nobody's list
until turn 1 flagged it; Nick's revision adopts it.

## CW-033 TURN 3 (2026-08-14, commit 02effe1): mini's four fixes landed

The audit's three live defects (M1/M2/M3) plus the B3 capex edge, all
fixed at the layer mini ruled, red-proofed pre-fix, ablated per-fix,
and driven live on real clones. Evidence:
_redproof_cw033_turn3_prefix_20260814.txt (pre-fix RED, 13 checks, each
red for its own reason), _redproof_cw033_turn3_fixes_20260814.txt
(24/24 GREEN), _redproof_cw033_turn3_ablate_20260814.txt (4 ablations,
each red on its own checks alone), _live_cw033_turn3_20260814.txt
(W1-W5b GREEN on PID 11032, postdates every edit).

### M1 - the interview reply speaks only from the receipt (F1(b) at
### this ship gate)
The A4b anatomy was FOUR emitting layers, all fixed:
1. THE ACK FALLBACK (the "Got it -- I'll update ... to 99" half):
   _build_financials_stage_acknowledgement_first now gates the router
   free-prose fallback - prose that matches _WRITE_CLAIM_RE or
   _prose_acks_unwritten_figure dies; the write-derived ack (or bare
   "Got it.") ships. The winner branch (a real stage write) is
   untouched.
2. THE MISREAD PATCH (the phantom "rent change" note): the wrapper now
   threads the redirect's consumed_figures into the inner turn as
   redirect_consumed_figures; any patch value echoing one (the router's
   rent=99 misread) is dropped BEFORE the doors and normalizer, and the
   same figures ride extra_reference_figures so the forward mover can
   never re-land them. _apply_cross_section_driver_correction now
   populates consumed_figures on the value-underivable return too.
3. PHANTOM NOTES (the "other operating costs yet" half): on a redirect
   turn a dropped field earns a say-do note only when the client
   actually stated the figure the router tried to write there.
4. "ALSO RECORDED" (three on-file values spoken as new): the
   extra-applied list is now filtered to values that actually CHANGED
   vs pre-patch state - a no-op write is not a landing (CW-029 rider
   #4, the law the forward mover already enforced).
   Plus: when every stated figure is the redirect's own, the no-write
   tail skips the failed-change register (the redirect already told the
   client what happened) - the standing question ships instead.
Live W1: the A4b turn now reads redirect + "Got it." + the rent
question. Nothing written, nothing claimed.

### M2 - the boundary decision lives at the write door
_apply_forward_move's ops branch refuses with the honest redirect
whenever _next_financials_stage() says a financials stage is active -
whatever wording carried the move there, detector or no detector. The
wrapper's detect stays for the redirect COPY only (one authority, as
ruled). At the wall (no active stage) landings are unchanged - W4
control still lands 7/7. Live W2: mini's keywordless "7 jobs a week"
wording now gets the redirect and writes nothing mid-interview.
NOTE for mini's promised leg ("mid-interview ops landings are
impossible regardless of wording"): the door is the choke point -
_strip_suppressed_ops_move remains as belt-and-braces on detector
turns, but deleting it would NOT reopen the back door.

### M3 - a stated cadence is never silently re-based
New _stated_capacity_cadence + _reconcile_stated_capacity_cadence
(intake_consult.py, above _strip_suppressed_ops_move): the stated
cadence parses from the message; matching cadence lands as today;
differing converts into the canonical cell (40/wk -> 40*52/12 =
173.33/period on Sumac's 12-period contract row; the derived week twin
then reads exactly 40); day-cadence, mixed cadences, or a per-period
row with no usable operating_periods_per_year ASK instead of writing.
The receipt always speaks the client's own cadence and discloses the
modeled figure when it converted: "Recorded: capacity 40 a week (about
173.3 per operating period (12 a year) as this line is modeled)."
Wiring notes: the early no-op check stands aside whenever a capacity
message states any cadence (a raw value-match can be a real change);
the underivability guard takes extra_derivable so the converted value
is not reverted as a figure from nowhere.
HONEST EDGE, handed to mini: _apply_cross_section_driver_correction
(the CW-017b market/people door) still lands capacity WITHOUT the
cadence reconciler - same class, different door, no observed artifact,
pre-existing door under the forward-only law. If mini can produce a
reachable wrong-number there ("mowing capacity is 40 a week" with
correction language + the word capacity at a market/people stage), that
is the reachable-case exception and the fix is the same helper at that
door's capacity branch (~intake_consult.py:6990).

### B3 - the capex but-we-did carve-out
_capex_answer_expresses_none returns False when a negative lead
carries a carve-out (but we did|except|apart from|other than|aside
from) followed by a figure; new _capex_carveout_figure returns the ONE
figure stated after the carve-out. The normalizer scopes the landing
numeric to it (router-captured 380k -> 15,000; router-forced 0 ->
15,000), and _unlanded_figures_disclosure treats the OTHER figures as
descriptive references so the excluded base cannot hunt for a home.
Plain explicit-no (B1 shape) and the No-wait correction lookahead are
proven intact. Live W5: 15,000 IS the capex, 380,000 lands nowhere in
financials or people; W5b control still stores 0.

### HOUSEKEEPING + THE A-112 DEBT
_live_cw033_capacity_turns.py L6 re-pointed to financials._coherence
(the vacuous intake_coherence read is gone) and its make_clone now
strips the stale retention frame (mini's hygiene). A-112 still owes a
live artifact from a real conversational run; the bypass canary has no
interview turns so it cannot supply one. Partial live evidence this
turn: W5's reply carried "(One note: I haven't recorded initial assets
yet)" and initial_assets was verifiably unstored that turn - the note
mechanism speaking truly on a real turn; the re-validation half (a note
dropped because the same reply recorded the field) remains unexercised
live.

### CANARY + PROVE
Sunny_V3 on PID 11032 (started 19:03:18, postdates every edit, ONE
listener verified): system_run_complete, 484s, ZERO error lines in
_logs_persona_20260814_190317.txt, workbook built and delivered,
workbook_deliveries row #22 bound by draft_id
(_canary_cw033_turn3_sunnyv3_20260814.txt). Full prove:
_prove_20260814_vs_cw033_turn3.txt (see RESULT for the table).

## CW-033 TURN 5 (VS) - MINI'S D1-D5 + THE X2 BUILD, ALL LANDED
Task: the five fixes from mini's turn-4 audit
(_mini_cw033_t3_audit_20260814.txt). Instruments:
Test Files/_redproof_cw033_turn5_fixes.py (25 checks, GREEN at HEAD, RED
on 10 at pre-fix 2da12be with all four controls green at both commits:
_redproof_cw033_turn5_prefix_20260814.txt),
Test Files/_redproof_cw033_turn5_ablate.py (6 ablations, each red on its
own fix's checks alone - none decorative),
Test Files/_live_cw033_turn5_turns.py (W1-W5 GREEN on a listener
postdating every edit: _live_cw033_turn5_20260814.txt).

### D1 - A DROPPED-FIELD FIGURE NEVER RE-ENTERS THE MOVER (two rules)
(a) In the stage edit_patch branch, the normalizer's dropped-field
patch values ride into _unlanded_figures_disclosure as
extra_reference_figures - the figure's disposition IS the say-do note,
so it never hunts for a home ("...52,000 cash on hand" re-attributed
onto rent). (b) _apply_forward_move takes turn_written_fields (the
turn's stage-patch write-set); a move targeting one dies silently -
the same law the redirect's consumed_figures enforce. Wired at the
edit_patch branch (report applied-set), the completed wall (_rep
applied-set), cash_strategy ({"cash_strategy"}), and the fallback
branch (the fallback patch's own keys). The completed wall gets rule
(b) only - it has no say-do note machinery, so a (b)-killed figure
there is silent; mini may attack that edge. Live: W1 ends rent=2400.0,
cash noted, nothing false spoken.

### D2 - A CADENCE BINDS TO ITS FIGURE (clause-scoped)
_stated_capacity_cadence(text, value=...) scans ONLY clauses carrying
the stated figure's digits (sentences split on terminators, then on
", and "/", but " - mini's measured warning that next-sentence is not
enough is honoured; "We invoice monthly." IS the next sentence and no
longer binds). Digits absent (word-number forms) -> whole-message scan
stands, which converts or asks but never silently re-bases. The figure
regex refuses decimal prefixes ("9" never matches inside "9.23").
Callers pass the value at the reconciler and the mover's no-op bypass.
Live: W2 lands install 9/9 with no 2.08 anywhere.

### D3 - THE RESTATEMENT FILTERS STAND ASIDE FOR A STATED CADENCE
In _unlanded_figures_disclosure, both stored-value filters (the
prior-sections reference filter and the small-path per-row restatement
check, capacity key only) stand aside when the message carries the
word capacity AND _stated_capacity_cadence(msg, value=fig) is truthy -
the same condition the door's no-op bypass uses. Negation, door-
consumed and last-assistant references still hold.
FOUND LIVE, FIXED, THE REAL C3 SURFACE: mini's C3 t2 dies at a THIRD
layer live - t1's completion turn flips the draft to done, and t2
routes through the COMPLETED/REOPEN surface where the router itself
re-based "40 a week" onto BOTH capacity twins raw (period=40 stayed,
wk=40 evaporated at derive) and the (h) which-field register shipped.
The cadence law now lives at that surface's write too: capacity patch
keys reconcile against the TARGET row's cadence before
_apply_scoped_patch - convert into the canonical cell (the redundant
twin key is dropped), ask when ambiguous (the ask holds the turn and
returns alone), extra_derivable declared to the consequence contract
so the conversion is not reverted as underivable, receipt
read-back-gated and spoken in the client's cadence. Live: W3 t2 ends
period=173.3333 / wk=40.0 with "Recorded: capacity 40 a week (about
173.3 per operating period...)" leading the reply.
NATURALIZER EVIDENCE FOR NICK'S OPEN RULING: on the first W3 rerun the
naturalizer took the deterministic receipt and INVERTED THE CADENCE
WORD - "40 a week" spoken as "40 a month (173 a period)", numbers
kept, fact flipped. A cadence-conversion receipt now ships VERBATIM
(the round-9 no-write rule's sibling, deterministic-layer, defensible
without the ruling). This is the sharpest data point yet that
naturalization can flip a receipt FACT while keeping its numbers.

### D4 - THE LANDED STAGE ANSWER IS NAMED
monthly_rent_expense added to _GENERIC_FINANCIALS_FIELD_LABELS
("monthly rent") - the one value stage whose code ack was a bare
"Got it.". The write-derived scalar ack now names every rent landing
("Got it - I'll use $2,000 for monthly rent."), which also means the
deterministic ack outranks benign router prose on the rent stage
(code_ack != "Got it." always wins in the _first builder - intended,
M1's direction). Live: W4 names the landed 2,000 beside the redirect;
all turn-3 honesty checks hold unchanged.

### D5 - AN ASK HOLDS THE TURN
_apply_forward_move returns (fin, shared, copy, holds_turn); the
cadence ask is the only holds_turn=True source. The completed wall
ships the ask ALONE (after any real receipt) and stops - no completion
prose, and the ask is NOT a landing so the completion sync no longer
runs on ask turns. Stage branches, the tail, and the coherence-round
backstop all handle the flag (structurally unreachable today - ops
moves refuse while a stage is active, BEFORE the cadence reconcile -
kept as law so a future ask cannot re-open the register gap). The
at-rest week-twin re-derive on ask turns (mini's C6 note ii, ruled
documentation-only) still occurs via the endpoint's own sync - W5
notes it; canonical cell untouched. Live: W5 ships the ask alone.

### X2 - THE CW-017B DOOR RECONCILES THE STATED CADENCE
_apply_cross_section_driver_correction's capacity branch runs
_reconcile_stated_capacity_cadence after value derivation: matching
cadence lands as today (X2e control, weekly row identity), a differing
one CONVERTS into the canonical cell (X2a: period 173.3333, never a
raw 40), an ambiguous one sets report["cadence_ask"] and returns None
- the market/people caller speaks the ask as the leading note, the
late focus==financials caller ships it alone (D5). The cands
current-value filter stands aside for a stated cadence (X2c: stored
40 + "40 a week" converts instead of declining). The conversion is
declared to _reconcile_driver_correction via a new extra_derivable
param (appended ONLY to the derivability check's figure list - landing
roles, targets and anchors never see it), because 40*52/12 is not in
the message's figures and the consequence contract would revert it.
The ack speaks the client's cadence. NOTE: _capacity_canonical_field
maps "weekly" (not "week") to the wk cell - a row stamped cadence
"week" is period-canonical; the first X2e control tripped on this.

### DECLARED-VS-ACTUAL (turn plan law, first turn under it)
Declared after the first site-reads (the law landed in 2da12be, after
this turn's bootstrap was generated) - emitted via
scripts/handoff_turn_plan.py before any code edit. Actual matched the
declaration with ONE addition: the completed/reopen surface fix (the
live W3 red forced it - same defect class, same law, found by the
declared live verification step). Blast radius stayed as declared
(system-touching, full apparatus run).

### SCOPING LAWS MIRROR (Nick 2026-08-14/15, recorded once - idempotent;
### v2 of 2026-08-15 REPLACES the localized/system-touching tiering)
VERIFICATION LAW v2 - SPOT-CHECK THE FIX. Hone in on the fix, test just
that, move on. Three tiers, chosen by ONE question: does this fix
CHANGE SHARED CODE THAT OTHER LIVE BEHAVIORS FLOW THROUGH (the forward
mover, the engine math, the workbook builder - genuine high-fan-out
chokepoints)?
- SPOT-CHECK (DEFAULT - a guard, a copy string, a validation, a branch
  that only fires on the broken case, anything that cannot affect a
  neighbor): repro red->green on the specific behavior + the artifact
  shows it (stored field / cell / receipt) + the single-line floor via
  --only. Minutes. No full prove, no canary.
- NEIGHBOR-CHECK (the fix genuinely changes shared high-fan-out code):
  spot-check PLUS the NAMED other behaviors flowing through the same
  changed path. Not the 61-leg universe, not a canary.
- FULL APPARATUS (Sunny_V3 canary + full prove): ONLY for a change to
  the engine/money math itself or the golden baseline. "It lives in a
  hot path" is NOT this tier; actually changing the core math is.
The single-line floor rides EVERY turn. The tier is declared per fix in
the TURN PLAN and confirmed in the RESULT; mini verifies the call - a
spot-check claim on a fix that changed shared high-fan-out code is a
finding.
SPLIT BY BLAST RADIUS: the call is per fix; a turn inherits the widest
radius it carries, so guards never ride with semantic re-scopes.
TRIAGE BEFORE FIX: a fix earns a turn only as a DEAL BREAKER (wrong
number / false claim in a delivered plan on the guided path), named per
fix in the TURN PLAN; new behavior dressed as a fix is a feature
decision for Nick.
TURN PLAN DECLARED UP FRONT: four lines (TASK / BLAST-RADIUS / LOADING /
VERIFY) via scripts/handoff_turn_plan.py, then proceed immediately;
RESULT confirms declared-vs-actual.
CONTEXT SCOPED TO THE TASK: each turn loads (1) the task, (2) the
short standing-laws list (client-authority/parent law, guided-flow
forward-only, receipt law, naturalization, verification-scoping, this
law), (3) ONLY the files/code the task touches. Full-context load is
EARNED only by genuinely system-spanning work. Mini independence = an
artifact audit without VS reasoning, not a reload of the world.

### CANARY + PROVE (turn 5)
Sunny_V3 on listener PID 29768 (started 20:33:06, postdates every
edit, ONE listener verified): system_run_complete, 305s, ZERO
ERROR/Traceback lines in _logs_persona_20260814_203305.txt, workbook
built, workbook_deliveries row #23 bound by draft_id 24860d32
(_canary_cw033_turn5_sunnyv3_20260814.txt). Full prove:
_prove_20260814_vs_cw033_turn5.txt (table in the RESULT).

### THE FIRST PROVE'S R44 QUARANTINE - FOUND, FIXED, RE-EARNED
The first full prove this turn QUARANTINED R44: its benign control
("prose without a claim still ships") went red on the current build,
because naming the rent stage (D4) exposed a LATENT $0-invention in
the scalar ack builder - called with the stage value ABSENT it spoke
"Got it - I'll use $0 for monthly rent.", a write-claim for a write
that never happened, and that non-bare ack silenced benign prose. The
shape pre-existed for EVERY scalar stage; D4 only made rent reach it.
FIX: the empty-state builder claims nothing (value absent -> bare
"Got it." -> benign prose ships); a stored 0 still speaks $0. R44
re-run --only: HOLDS on all three probes. Everything re-earned on the
FINAL code after a backend restart (ONE listener, PID 33964 20:47:09):
redproofs 25/25 + 24/24, ablations all, live W1-W5 GREEN, fresh
Sunny_V3 canary (draft 6b46dcc5, system_run_complete, 0 error lines,
delivery record #24 bound by draft_id), full prove CLEAN - 65 legs,
58 PROVEN behavioural, 5 structural-absence, 2 golden, 0 DRIFT,
0 UNEARNED, no quarantine.

### DEAL-BREAKER BATCH TURN A (VS, 2026-08-15) - A1 / A2 / A4, all SPOT-CHECK
Proof file: Test Files/_redproof_dealbreaker_turnA.py; outputs
_redproof_dealbreaker_turnA_PREFIX.txt (RED 10 on the stashed pre-fix
tree) and _redproof_dealbreaker_turnA_POSTFIX.txt (ALL GREEN). Floor:
_prove_20260815_turnA_floor.txt (R31 + R32 GOLDEN, 0 DRIFT). Backend
restarted after the edits, ONE :5050 listener verified. Canary SKIPPED
by law (no engine/money-math or golden change).

A1 - _apply_cross_section_driver_correction, price + utilization
branches (intake_consult.py ~6912-7010). WAS cands[-1] (last figure
wins): "fix the price - it should be 650, I was thinking of 520 before"
stored 520; "utilization should be 75%, I said 60% earlier" stored 60%.
NOW the capacity branch's three rules, factored into two local helpers
(_xsec_scoped, _xsec_pick) used by price + utilization: sentence-scoped
(the lever sentence + the next), a figure after "not" is the OLD value,
a MARKED figure (should be / needs to be / to / is / now / at) wins,
several unmarked survivors REFUSE (None -> the door's existing
honest-refusal path). Capacity branch byte-untouched (its own regex
stays). Correction MARKERS unchanged - "should be" alone is still not a
correction marker; a marker word (fix/correct/set/...) is required, as
before. Artifact: stored ops row values in the proof output.
NOTE for mini: Test Files/_redproof_cw033_fixes.py T1 attempt2 ("It is
currently set to five ... needs to be seven") is RED on the pre-fix tree
too (verified under git stash) and T4 tracebacks on the pre-fix tree
(_apply_forward_move now returns 4 values) - both PRE-EXISTING leg-craft
staleness in that file, not this turn's regression; not repaired here
(out of scope, flagged).

A2 - #134 payment-term guard. New _payment_term_figures (net 45 /
net-30 / net 60 days / 45-day terms) added to _door_refs at the top of
_unlanded_figures_disclosure, so the figure is a REFERENCE in both the
main path and the small-figure attribution path - never a
capacity/price/count candidate. Fires ONLY on messages carrying the
term (no token, no change) - that is the spot-check justification for a
guard living in the shared unlanded-figure path. Repro on the REAL
Fernhill sentence ("Cash is about $186,000. Clients owe us around
$215,000 - consulting invoices go out net 45 ...") at the wall: pre-fix
move = ops.units_per_period_capacity 45.0; post-fix None. Control: "We
can take on 40 clients a month now" still moves 40. NOTE: mid-interview
the D1 (turn 5) redirect already refuses ops moves while a stage is
active, so the ORIGINAL Fernhill turn shape is doubly closed; the guard
matters at the wall and for any ops-key path fed by the disclosure.

A4 - #122 invented price tier. VERIFIED FIRST: the finalize prompt still
carried "If price is not known, describe the tier
(value/mid-market/premium) without numbers" (3 copies) and the Brightline
artifact reads "a mid-market price point ($85 per office cleaning
visit)". The app holds NO market price fact at market finalize (the
price_ceiling_market_fact is a coherence-section, client-stated fact,
later). Parent law: the tier was INVENTED. FIX (source + scrub): the
three prompt copies now forbid any tier claim unless the client stated
it; target_market_finalize returns through _scrub_finalized_copy ->
_strip_undeclared_price_tier on marketing_plan_summary +
target_market_summary: a tier qualifier glued to a price word
(mid-market price point, premium-priced, competitive pricing) is
dropped UNLESS the client's own user messages used that tier word (then
it is their declaration and stands). Names/non-price uses untouched
(pattern requires the price word to follow). "Speak the actual
position" resolves to: state the price, claim no tier - the app has no
position fact to speak. If Nick wants a REAL market-position statement
here, that needs a market price fact captured/asked at market stage =
a feature decision, not built.

### DEAL-BREAKER BATCH TURN C (VS, 2026-08-15) - A3 (#101): THE STATED-CAPACITY WALL, NEIGHBOR-CHECK

The bug (still live on the pre-fix tree, re-proven this turn): the
coherence gate's fence tier evaluates Q11 at anchor x 1.07^10 with NO
capacity term. Fetch & Fluff turn 96 (real draft 50658fff, first-capture
facts to the cent) PASSED at $24,097.60/q = $96,390/yr against a stated
30 grooms/wk x $45 x 52 = $70,200/yr physical ceiling - 137% of what she
said she can produce. The anchor hold (CW-022 #2) only guards Q1 (anchor
vs ceiling); growth was a free licence past the wall.

The fix (evaluator.basis_from_intake, ONE home): every coherence basis
(fence, judged, corner, walk) caps its growth multiple at the
PHYSICAL-CEILING MULTIPLE = (stated capacity x price x periods at 100%
utilization) x PRICE_PATH_Q11 / revenue anchor. PRICE_PATH_Q11 =
(1 + the deterministic proposer's own 1%/q drift)^10 = 1.1046 - the wall
bounds THROUGHPUT (units), in the same currency the judged multiple is
read in (the proposer's output includes that drift). Non-unit models (no
priced products) carry no wall; the flat tier (1.0) is never touched; a
consented volume/capacity move re-lands ops AND mirrors current_revenue,
so the wall rises by construction. The ceiling arithmetic moved to
evaluator.ops_implied_and_ceiling; section._ops_implied_and_ceiling now
delegates (hold and wall can never diverge). controller.evaluate_current
returns result["growth"] = {requested, capacity_ceiling_multiple, used,
capped_by_stated_capacity}; the gate and refresh_eval_stamps stamp it
into _coherence.eval.growth and basis_growth.growth (the artifact).

Evidence: Test Files/_redproof_a3_capacity_fence.py (PREFIX: T1a/T1b/T2a
red behaviourally - fence PASS at $96,390 > $77,544 wall, stamped
passed=True; POSTFIX: ALL GREEN, capped multiple 1.5825, fence FAILS on
fixed_cost_burden/band/ni, stamp shows the wall; controls: non-unit
model untouched, a 3x-capacity shape byte-identical to the fence).
Neighbor sweep (Test Files/_neighbor_sweep_a3_capacity_wall.py, 40 most
recent real drafts with a band stamp, PRE vs POST): 34/40 carry a wall
below the fence, ONLY 3 flip fence PASS -> FAIL (b1f4fac7 appliance
repair 55/wk @78% util, 2ecc759c grounds maintenance 34/mo @82%,
3de095cb commercial cleaning 60/wk @80%) - each was already the
fence-pass + judged-fail divergence class (eval_judged_shortfall stored
on all three), i.e. exactly F&F's shape; zero gap-only moves; anchor-hold
arithmetic identical on all 40; flat tier identical; corner identical
where bounds existed. Neighbor legs through gate_and_turn (R19, R21,
U02, U05, R25, R30) all GREEN on the fixed tree; floor R31+R32 GOLDEN
(digests 72dfcb81 / 24e38de4 / 1d50e46a / cbd76463 unchanged).

Known residuals (flagged, not built - triage law):
- _volume_move_basis / _price_move_basis carry the PRE-move capped
  growth into a lever's closes-projection; after landing the gate
  re-evaluates on the real wall, so a "closes about $X" can overstate
  by the utilization the move consumed - never a false pass (the
  verdict is the gate's), only a narration precision item.
- _intake_current_structure (bounds author payload) still shows
  revenue_lines_quarterly q11 at the raw fence - GPT input only.
- The FAIL narration does not yet NAME capacity as the binding cause
  ("where a single input is the cause, the system should name it" -
  #101 expected). Feature decision for Nick; the verdict itself is now
  honest.

## DISCOVERY PRESENTATION FIXES, TURN 1 (VS, 2026-08-15): own LOB per stream + serial comma
Nick's ruling after Nine Fathom run #2 (draft 6d2823db, record
_confirm_discovery_ninefathom_20260815.txt). SPOT-CHECK, discovery path
only; judge/validator/reader/seam/gate/capture/engine untouched. Diff =
gpt_stream_discovery.py ONLY (17+/39-):
 1a  stem_match_lob_index DELETED (2 callers, both in this module:
     append_confirmed_stream_rows + carry_stream_discovery's re-append
     branch). A confirmed discovered stream ALWAYS gets its own LOB named
     for its label - discovery surfaces PEER streams by definition (the
     validator already dropped the client's own lines/paraphrases), so
     there is no placement decision left. The "is its own line under
     <lob>" receipt variant is gone with it (receipt == state: one
     sentence, one shape).
     'Primary line of business' placeholder: NOT authored in the
     placement path. Named origin: financials_year1._build_default_lobs
     (financials_year1.py:167, `business_type or "Primary line of
     business"`) + quarter_grid.py:512/528/535 same fallback; the ops
     model then echoes the year1 LOB name into ops.lob_models (strict
     schema lob_name, intake_consultant.py:87). Nine Fathom's stored ops
     carried it on the primary LOB with business_type='Coffee Roaster'
     set - so the year1 default was built when business_type was still
     empty and the name stuck. LEFT, flagged for Nick (a fix there is
     the year1 builder / a naming rule for the primary LOB = a different
     radius, not this turn).
 1b  join_labels: 3+ labels 'A, B, or C' (serial comma), 2 'A or B', 1
     'A'. Template constants untouched; the clarify template inherits it.
     Forbidden-phrase grep clean; revenue-line clause stays.
Proof: Test Files/_discovery_lob_nesting_redproof.py PRE 9 red (nesting
under 'retail coffee bags' in append AND carry; comma missing on 3 + 4
labels; clarify) -> POST GREEN (numbers 19/260/.6, 13/140/.55, 58/380/.75
do not move). Existing _stream_discovery_redproof / _f123 / _f4 GREEN.
Floor R31/R32 --only GOLDEN (_gate_only_R31_R32_20260815_lobnesting.txt).
LIVE: Test Files/_live_discovery_ninefathom_clone.py - rewound Nine
Fathom clone (messages[:23], discovered rows + latch stripped) on the
RESTARTED :5050 (one listener): live judge proposed 4 -> ask rendered
'..., recurring coffee subscriptions, or office coffee supply accounts';
yes/yes/no/no -> two rows, TWO LOBs each named for its label, primary
row untouched, receipts 'is its own line;' x2, no 'under'. Canary SKIP
(spot-check tier). Note: draft 8196d410 (0 messages, 18:12:28) is the
known vite/.env.local phantom from the backend restart, not a live
intake.

## DEAD RESTRUCTURE NET (Nick 08-16 ruling; 246a53d) - FIX 1 + FIX 2 landed, FIX 3 split off
FIX 1: searcher.synthesize_new_line_rows emits a contract-valid 'COGS %'
row on every synthesized new line WHEN the base draft carries per-line
COGS (single-line/blend drafts byte-identical). Value = _new_line_cogs_pct:
1 - executive-authored gross_margin_pct (what blended_cogs_ratio already
charges the new line), else the draft's revenue-weighted per-line blend;
never a constant. Row shape = finmo_bridge's real per-line row
(controller_write=False, derived_driver=per_line_cogs_source, lever_id
revenue::lob::product::COGS %, ratio/percent_of_line_revenue, constant
across the horizon incl. the stub so an overlay re-resolve keeps it).
THREE callers pass gross_margin_pct: searcher.apply_candidate,
joint_solver._prepare_restructure_model, AND the real re-run's grid
loader (post_intake_initial_grid/runner.py ~1960) - the third caller is
the one the approved design flows through; missing it would have killed
the rescue one stage later on the same contract.
FIX 2: joint_solver.RestructureNetDeadError (RuntimeError, to_dict) raised
by run_restructure_joint_solve when evals==0 AND every rung raised AND one
identical signature. Honest exhaustion (no updates) and mixed errors stay
quiet (trace 'dead_search_mixed'). intake_consult: catch at the search
call -> repair_guidance history gets a dead_net record, directive
cleared, planning_runs.run_status=failed (failure_reason = the violation),
RE-RAISE past the restructure block's swallow-all (explicit except
RestructureNetDeadError: raise ahead of it; the class is imported ABOVE
the try so the clause is always bound) -> handler RuntimeError path ->
FAILED diagnostics row + failure email + HTTP 500. Nothing ships.
PROOF: _rs_deadnet_repro.py (PRE evals=0 identical ContractViolation on
Nine Fathom 6d2823db from persisted model_input + bounds; POST contract
valid, evals=8, found=True), _rs_deadnet_failloud_proof.py A-E,
_rs_deadnet_class_sweep.py 8/8 (structural bounds via
validate_restructure_bounds where no executive bounds persisted),
LIVE Nine Fathom re-run: f44ff3f1 failed -> restructure evals=8 ->
review approved -> e8a03731 PASSED 18/18 (Q11 NI 12.05% vs 8%). Floor
R31/R32 digests identical pre/post (1d50e46ab8e6 / 24e38de4dc98 /
cbd764631e98).
OPEN: FIX 3 (one ruler in the cascade) = next VS turn, neighbor-check.
Observation: _prepare_restructure_model also flips EXISTING COGS % rows to
controller_write=True/derived_driver=None (pre-existing, harmless, not
the real-row shape) - triage.
