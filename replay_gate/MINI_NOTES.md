# mini's audit notes

Mini-owned, under the ownership law (replay_gate/* is mini's except HANDOFF.md,
VS_NOTES.md, and the generated fixture module). VS should read this file the way
mini reads VS_NOTES.md.

---

## Round 14 - CW-031 round 12 audited CLEAN; R43 pinned; both judgment calls ratified

Probe: `Test Files/_mini_cw031_r12_guard_attack.py` (7/7, output
`_mini_cw031_r12_guard_attack_20260813.txt`). Prove:
`_prove_20260813_mini_round12.txt` - 61 legs, 54 behavioural, 5
structural-absence, 2 golden, 0 DRIFT, 0 UNEARNED, CLEAN. My round-11
instrument `_mini_cw031_r11_legacy_order_attack.py` re-run UNMODIFIED on
HEAD: 4/4. App code byte-identical to HEAD this turn (only legs.py and
this file changed - both mine).

- **R43 `legacy-tier-is-a-law`** (fix e8d1f3b, baseline b0607e0, PROVEN
  BEHAVIOURAL): red at b0607e0 on exactly both teeth - the stale-FIRST
  ordering retired the coherent remainder (`ungrouped=['Main / Zed',
  'Main / A', 'Main / B']`) and the duplicate-name twin kept
  `shared:alpha+beta` - while both positive controls (stale-LAST retires
  alone; agreeing mixed attach lands) stayed green at baseline, so the
  red is for the right reasons. Green at HEAD. This is the promised R42
  extension, landed as its own leg (the R40 precedent): the tooth needs
  its own baseline, since R42's teeth are green at b0607e0. R42's
  KNOWN-LIMIT paragraph now points here.
- **Judgment call (a) RATIFIED - shape (a) over (b).** Deleting the
  pure-legacy tier would retire a coherent label-only group on its next
  unrelated write (G2 proves such a group survives today), which
  contradicts the ratified retire-only-failing-claims principle for a
  claim that holds when read. The remove-legacy law's real target - the
  order-dependent `elif not _parts` branch - is deleted, not routed
  around. If Nick ever rules the whole tier dies, it is still a
  three-line deletion.
- **Judgment call (b) RATIFIED - the any-row guard.** A frozenset key
  cannot claim one name twice, so a second same-named row can never be
  legitimately homed; the only attaches the broader guard additionally
  refuses are twin #2 shapes (G7: refused alone, group intact), and every
  legitimate attach still lands (G1 agreeing-mixed, G2 pure-legacy
  coherent pair). No legitimate attach is refused.
- **Residual order edge RULED: stands documented; do NOT refuse both.**
  G3 both orderings: exactly one twin keeps the label, the coherent
  remainder survives, partition outcome order-free. Refusing BOTH twins
  would drop the name from the surviving set and retire the whole
  partition - innocent bystanders included - violating
  retire-only-failing-claims. Which twin keeps the label follows document
  order between rows the data cannot distinguish; census reach 0.
- **Empty parse partition VERIFIED inert.** Code: the retire loop extends
  an empty row list (no-op); G4 all-off-claim retires exactly the stale
  rows by name, G5 degenerate `shared:` label retires cleanly, no crash.

---

## Round 13 - CW-031 round 11 audited; R41/R42 pinned; the legacy tier is order-dependent

Live transcripts: `_mini_cw031_r11_live_20260813.txt` (part A, question-form
+ groups/separation) and `_mini_cw031_r11_live_b_20260813.txt` (part B, the
deterministic no-write branch). Probes:
`Test Files/_mini_cw031_r11_{legacy_order_attack,census,live,live_b}.py`.

- **R41 `match-never-lies`** (fix b0607e0, baseline 55f0ae0, PROVEN
  BEHAVIOURAL): an ambiguous value matches with leaf None and speaks bare; a
  0.32% near-miss never claims a match. Positive controls: unique name still
  names, float dust still matches. Proven live: B1 spoke '$9,800 on file'
  bare on the rent==interest collision, B2 matched real stored dust
  (729909.9999999995 vs a stated 729,910 - the 0.5 absolute floor earning
  its keep), B3 unique kept its name. VS's round-10 live gap is closed.
- **R42 `identity-is-the-member-set`** (same commits, PROVEN BEHAVIOURAL):
  the 'shared:a+b+c' label collision survives as two partitions with member
  lists intact; a stale label-only twin retires ALONE while the fresh
  declaration survives; the O4b overlap retire still fires. This is the
  retire-coverage extension promised after D3.
- **VS's judgment call (pure-legacy off-claim retires alone): principle
  RATIFIED, implementation ORDER-DEPENDENT.** T1a (stale row last) retires
  it alone; T1b (same rows, stale row FIRST) retires ALL - the first legacy
  row creates the parse-fallback partition and JOINS it even when its own
  name is off-claim, poisoning the partition. Census: 0 real rows carry a
  label without a member list, so the whole legacy tier is dead code today;
  latent, not urgent. R42 deliberately does NOT pin the legacy tier so the
  fix can land without redding it.
- **Second latent hole: duplicate-name shadow.** A stale label-only twin
  whose NAME a fresh members partition claims (possible only via duplicate
  product names across LOBs) attaches to that partition and KEEPS the
  group/label it never earned - the name set dedups, so coherence cannot
  see the extra row. Census: 2 of 3,303 ops drafts carry duplicate names,
  0 of those carry any group. Latent.
- **Item 3 ruled (D1's honest cost): keep the bare-value sentence; do NOT
  build a mirror map now.** Measured on the real clone: 6 of 39 stored
  values >=1000 are collided (all derived twins plus rent==interest);
  live, the bare sentence reads fine ("That matches what I have - $9,800
  on file"), the client's own words carry the field identity one sentence
  earlier, and question-form confirmations already get the field named
  back via the answer path (L1-L3). A mirror map is standing machinery
  with drift risk to buy one word.
- **D2 live bonus:** the 1,548,000 near-miss now LANDS as a real write
  (stored 1548000.0000000002) instead of being swallowed as a match - the
  correction path took over exactly where the false match register left.
- Round-9 polish (separated[:3]) confirmed landed: the ack now joins all
  separated names.

---

## Round 12 - CW-031 round 10 audited; R40 pinned; the label is still the key

Full report: `_mini_cw031_r10_audit_20260813.txt`. Prove:
`_prove_20260813_mini_round10.txt` (58 legs).

- **R40 `membership-is-data`** (fix 1cb145d, baseline 5dcbca4, PROVEN
  BEHAVIOURAL): a '+'-named declared group survives its own declaring call
  with the member list stored as data beside the label; a real separation
  still retires the survivor by name; an agreeing mixed group (stored list +
  legacy label-only row the list covers) survives. A NEW leg rather than an
  R39 tooth because R39's baseline (858987b) predates the coherence pass -
  the '+' trap did not exist there, so a tooth would not red for its own
  reason. This closes the "known limit, deliberate" note in Round 11 below.
  Also proven LIVE this turn: 'Hard goods + Sundries' declared through the
  real router, members read back off the rows (W1/W2).

- **NOT pinned: the match-on-file sentence.** It has a live defect (a
  coincidence names the first-walked leaf - restating the interest payment
  got "monthly rent expense is $9,800", Ravenwood's own numbers) and a
  latent one (0.5% tolerance speaks a near-miss correction as a match).
  Pinning today's shape would pin the bug; the leg follows the fix (the
  Round-11 rule). R41 shape ready: "a match never names an ambiguous field,
  a near-miss never claims a match".

- **The retire's grouping KEY is still the label string** (membership became
  data; identity did not): a label collision (no-space '+' names) or a
  stale legacy same-label row still kills a fresh declaration in its own
  call. Low/nil reach today, but it is the founding-defect class; fix shape
  handed to VS (partition by stored member frozenset).

Instruments-of-record: `_mini_cw031_r9_coherence_attack.py` is the round-9
record now (VS re-ran it green rather than editing it - right call). This
turn's probes: `Test Files/_mini_cw031_r10_{match_attack,retire_attack,live,peek}.py`.

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
