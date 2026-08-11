# VS → Cowork-mini

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
- **I13 owner-draw-clears**: `section._owner_draw_exit_tail` with
  cause {staffed 30000, phasable 0} + wall {payroll_to_clear 122500} →
  offers $7,708/mo (not $10,208); zero-case (staffed 130000) → NO
  "draw at or below" in the tail, revenue named. On ff1da19 the
  function doesn't exist → RED. The invariant in words: the offered
  draw ACTUALLY clears the wall, and an unreachable exit is never
  offered. (Q8/Q9)
