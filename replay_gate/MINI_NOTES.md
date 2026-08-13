# mini's audit notes

Mini-owned, under the ownership law (replay_gate/* is mini's except HANDOFF.md,
VS_NOTES.md, and the generated fixture module). VS should read this file the way
mini reads VS_NOTES.md.

---

## Round 11 - CW-031 round 9 audited at the artifact level; R38/R39 pinned

Full report: `_mini_cw031_r9_audit_20260813.txt`. Prove:
`_prove_20260813_mini_round9.txt` (57 legs).

Two legs pinned this turn, both fix 56717dd / baseline 858987b, both PROVEN
BEHAVIOURALLY (red at 858987b on their own checks, green at HEAD, no
crash-reds):

- **R38 `inference-never-stored-as-structure`** - the round-9 ruling as a
  permanent leg: the uniform write ASKS and stores nothing, the declared
  partial stamp survives a coinciding write byte-identical, an echo neither
  stores nor re-asks, and the gate fails an inferred-basis group while
  passing a declared one (positive controls both directions). The gate half
  runs through a cursor stub (`_OpsOnlyCursor`) so a leg never writes the
  drafts table to prove a rule about writes.
- **R39 `separation-clears-the-group`** - the remover and the coherence pass:
  the separated row clears group AND basis, the abandoned member's stale
  label retires and is NAMED and spoken, a regroup that leaves a member out
  retires the leftover, and a DISJOINT declared group must survive
  byte-identical (a pass that clears everything fails as loudly as one that
  clears nothing).

Known limit, deliberate: R39 pins '+'-free names only. The coherence pass
parses membership out of the label with split('+'), so a product named like
'Business Plan + Financial Model' (7 real drafts) makes a just-declared group
retire itself in the same call. That is VS's fix (store membership as data,
not label-parse); pinning today's parse would pin the bug. Leg follows the
fix.

Instruments-of-record note: with R38 in the gate,
`Test Files/_mini_cw031_r8_net_attack.py` (as re-pointed by VS, verified 9/9
this turn) and the round-8 ablation script are historical records, not
instruments. The gate is the instrument.

---

## Round 10 - the durable freeze audited from a fresh session

Prove: `_prove_20260813.txt` (build 867cd48 vs baselines; exit 0, ~4 minutes).

    43 PROVEN behaviourally
     5 STRUCTURAL-ABSENCE (declared, justified)
     2 GOLDEN-MASTER      (R31, R32 - both sides identical)
     0 DRIFT   0 UNEARNED   0 other failures   0 baseline incomplete
    50 legs

R32 is out of quarantine. The round-7 scoping fix landed and the assertion it
now makes is a real one, not a weakened one: *FINMO carries exactly one 'Cost of
Goods Sold' row - 21 per-period cells of the legacy `=<revenue>*'Model Inputs'!
<row 12>` shape plus 5 annual `=SUM` rollups, zero per-line rows*, over 4,185
formulas across 7 sheets.

### 1. Nothing here is taken on VS's word

Every claim below was re-derived in this session against the committed
artifacts. Where VS's round-8 claim and my measurement disagree, the
measurement is written down.

### 2. "No database query anywhere in the hashing path" - PROVEN, harder than claimed

VS counted connections. Counting can only find what it thought to count, so I
made a DB touch *impossible* instead: after `GateContext(conn, read_conn)` was
constructed I replaced `mysql.connector.connect`, `socket.socket.connect`, and
`cursor()` on **both** gate connections with functions that raise, then ran the
real golden paths.

    single_line_payloads()      -> 72dfcb81 / 9650f148 / c21a05c9
    _r_workbook_formula_grid()  -> 72dfcb81 / cbd76463  (ok=True, 4185 formulas)
    connect attempts 0 | cursor attempts 0 | socket connects 0

All four digests are byte-identical to the ones the prove printed. Any read
would have raised rather than gone unnoticed. The honest scope from round 9 is
unchanged and worth keeping in the docstring: the *gate* still needs a live DB
to construct `GateContext` (importing the app package reads MySQL at module
level), but the *hashing path* does not touch it.

### 3. The frozen constants are the real payloads - re-queried, not asserted

Re-read live from MySQL and compared by sha256:

    payroll_headcount   draft 6feac758              live == frozen
    debt_schedule       draft 6feac758              live == frozen
    planning_run_id     ddb61397                    live == frozen
    planning_run_json   stage post_intake_finalize_validation_completed
                                                    live == frozen
    single-line row     draft 89e5a622, 97 columns  0 columns differ
    single_line_input   recomputed from the committed bytes with surface.py's
                        own recipe -> 72dfcb81..., == PROVENANCE

`PAYROLL_HEADCOUNT`, `DEBT_SCHEDULE`, `PLANNING_RUN_JSON` and `LOOKUP_REPLAY`
each hash to their own recorded `PROVENANCE` entry (8 loaders, 74 keys,
0e8f5c71). The fixture is what it says it is.

### 4. The freeze is load-bearing - red-proofed twice

Mutating 68 recorded float fields in the industry-baseline replay moved
`model_input` **9650f148 -> d1d80748**, and restoring the recorded values
returned it to 9650f148 exactly. The committed bytes are the input.

### 5. FrozenLookupMiss really fires, and a mutated input refuses rather than reads live

`prime_frozen_lookups()` patched 10 bindings for 8 loaders. An unrecorded
argument raises `FrozenLookupMiss` with the re-capture instruction; `restore()`
puts the live binding back.

Worth knowing, because it will bite whoever next tries to "vary the input":
changing any driver in the frozen draft (I tried `cash_on_hand` and a thinned
product list) makes the build ask the reference tables a question nobody
recorded, so it **refuses** with FrozenLookupMiss instead of moving the digest.
That is the design working - a live fall-through is exactly the defect the
fixture removed - but it means input-sensitivity can only be tested by mutating
the recorded lookup data, as in section 4.

### 6. Refuse-to-hash, both golden legs

    R32 with PAYROLL_HEADCOUNT = {}   -> ok=False, no digest printed, gap named:
      "the frozen payroll_headcount fixture is empty ... a hollow payload
       hashes stably and proves nothing"
    R31 with the product lines emptied -> mij/finmo None, draft_input_sha stays
      empty, refusal names the reason

Neither leg hashes a thin artifact. The SETUP strings name their own gap.

### 7. Round 7 -> 8 digests: VS's claim CONFIRMED

    prove7 / prove7b   72dfcb81  cbd76463  9650f148  c21a05c9
    prove8             72dfcb81  cbd76463  9650f148  c21a05c9
    prove 20260813     72dfcb81  cbd76463  9650f148  c21a05c9

Three prove runs and one out-of-band reproduction with the DB poisoned. The
freeze captured exactly the draft the ladder was already resolving to, so
round 8 is comparable to round 7 and identical to it.

### 8. VS's open question, answered: the workbook does NOT read planning_run_json

`PLANNING_RUN_JSON` is 359,636 bytes of the fixture file (28%), not the ~2.8 MB
of 2.9 MB the round-6 task estimated - `LOOKUP_REPLAY` is the big one at 703,101
bytes (55%). Building the grid with `PLANNING_RUN_JSON = {}` returns
**ok=True with grid sha cbd76463, unchanged**. It is passed to the boundary gate
and never read into the formulas. VS can drop it in one deliberate re-freeze
without moving a digest; a `--prove --tier full` afterwards is still owed
because the claim "no digest moves" is the thing being asserted.

### 9. Two corrections to VS_NOTES, neither a defect

- Round 9's line "8 loaders / 74 keys / 0e8f5c71 == claimed, **none empty**" is
  not quite right: 6 of the 18 recorded `_query_cohort_rows` results are empty
  lists. They are legitimate - each empty is a narrow `revenue_window` paired
  with a wider one that returns rows, i.e. the band-widening ladder recorded
  faithfully. An empty result is a real recorded answer and freezing it is
  correct; the claim to make is "no loader recorded nothing", not "no key".
- Behaviour 10 is **settled and passing**. The first Bash call of this turn
  printed `HANDOFF_ALLOW_COMMIT=1`. The watcher's env fix does survive into the
  agent's tool shells; round 9 could not exercise it only because the running
  watcher predated the fix. The explicit override is no longer needed.

### 10. Still open, carried forward (neither blocks green)

- **The lru_cache blind spot.** Two frozen loaders are warmed by a live read at
  app-import time, before priming can run; patching a binding cannot undo a
  memo. Red-proofed as inert *today* (mutating all 26 driver-target rows moved
  nothing), but it is a pattern trap: a future loader that memoizes at import
  and feeds the build would be frozen in name only, silently. The cheap durable
  fix is still the right one - record which loaders were SERVED during capture
  and have `prime_frozen_lookups()` report the served count, so a leg can refuse
  when a loader that used to serve goes silent.
- **The two GOLDEN-SHAs are not equally sharp.** Mutating the industry baselines
  moves `model_input` and leaves `finmo` unmoved. Probably benign - finmo is a
  projection over fields those baselines do not touch - but nobody has checked,
  and a negative control that cannot move is not a control.
