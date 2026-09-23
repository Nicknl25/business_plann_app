STATUS: awaiting-Nick

TURN: 1/16

TASK:
  WRITE-PATH AUDIT on the Ashgrove Bindery draft bf731ee486254923986eb049688aed29, seeded by VS on Nick's 2026-09-22 instruction to work alongside Cowork. Cowork drives the app as a client and can only see what a client sees; this is the half it cannot see, so do not take any of my four claims below on faith - name the function and line for each answer and read the STORE, never a log. (1) WHICH WRITER put 110 into operating_periods_per_year on the "Book binding & repair job" row, and which writer later replaced it with 48? She said "About eleven hundred" jobs a year and "Forty-eight" working weeks. I believe 110 was derived as 1100/10 (turns = annual / concurrent) and that 48 then overwrote it through the same slot, but I have not proved either - name both writers. (2) Her stated 1,100 is in NO field: annual_completed_units is absent from the whole operating model. Confirm that, and name the writer that should have stored it and why it did not. (3) DOES THE PER-ROW ENGINE OVERWRITE A FIGURE THE CLIENT STATED? intake_consult.py around line 20100 re-derives units_per_week_capacity whenever it disagrees with period x periods / weeks, with no check for whether the existing value came from the client. If she says "I do seventeen a week" and the arithmetic says 22.9, does her seventeen survive? Prove it either way on a real row through the real door. (4) I told Cowork that 3c (the marker recompute in _normalize_ops_capacity_compat) was NOT what turned 21.1538 into 9.2308, and that nothing recomputed. Cowork says something plainly did recompute, because the weekly figure moved the instant her weeks arrived. Settle it: name the code that recomputed it, and rule on whether 3c is now redundant or still earns its place. If I was wrong, say so plainly - I would rather have it from you than ship on it. Report as usual; no app-code changes in this turn, audit only.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.

RESULT:
  AGENT: mini
  VERDICT: needs-ruling
  ERROR-SIGNATURE: ops_driver_write_routed_by_the_question:her-annual-count-never-stored
  EVIDENCE: replay_gate/_audit_ashgrove_write_path_20260922.md
    (store tables intake_turn_interpretations + intake_turn_reader_extracts
     for draft bf731ee4; offline replays against the run-time blob 4f52588d)
  SUMMARY:
    Four answers, all read from the STORE, with the code pinned at the
    version live during the run (4f52588d, before a04da00b/155fe713).
    THE ROUTER READ HER CORRECTLY BOTH TIMES - the store holds
    {"ops.annual_completed_units": 1100} at turn 11 and
    {"ops.operating_periods_per_year": 48} at turn 17, and the shadow
    one-reader named her weeks as ops.operating_weeks/actual. The mislabel
    is downstream of the reader, not in it.
    (1) The 48 is PROVEN and reproduced offline through the real door:
    _apply_scoped_patch's row-less branch, intake_consult.py:17057-17070,
    OPS_DRIVER_WRITE_ROUTED_BY_THE_QUESTION. A bare driver on a two-row
    model lands when OUR OWN previous message contains exactly one row
    name. Turn 16's text contains "book binding & repair job"; turn 10's
    does not. Same door, same draft, opposite outcomes - that one line is
    why her 48 became the turns and her 1,100 landed nowhere.
    The 110 is NOT PROVEN and your hypothesis is NOT confirmed:
    ANNUAL_PAIR_HOMED needs a ceiling that was never emitted, and when it
    fires it pops annual_completed_units and sets utilization_rate - the
    store shows both untouched at end of turn 13. Replaying the exact
    stored turn-11 ops plus the exact turn-13 patch through the real patch
    door yields periods=None. Writer not yet named; narrowed to a site
    after the patch door inside turn 13.
    (2) CONFIRMED - no field holds 1100 anywhere in the final model. But
    _apply_ops_product_overrides DID store it on both rows at turn 13
    (store + replay agree); it was lost between end of turn 13 and end of
    turn 15, by the same unnamed site. At turn 11 it never landed: bare,
    two rows, no row name in our sentence. The receipt at turn 14 told her
    1,100 was recorded AND invented 1,100 for the print line she never
    gave a figure for.
    (3) YES, her figure does not survive. Proved on a real row through the
    real door on live working-tree code: stated 17/wk becomes 22.8846 on
    contract and on monthly, and survives only on weekly.
    _derive_capacity_cells (intake_consult.py:20228-20238) has no
    provenance check.
    (4) YOU WERE RIGHT THAT IT WAS NOT 3c AND WRONG THAT NOTHING
    RECOMPUTED - Cowork is correct. The producer is _derive_capacity_cells
    called at intake_consult.py:17069. The rounding settles it:
    _derive_capacity_cells writes 4dp, _normalize_ops_capacity_compat
    writes 6dp, and the stored 21.1538 / 9.2308 are 4dp. Reproduced end to
    end offline: real turn-15 ops + real turn-16 text + the bare 48 gives
    periods=48, week=9.2308, the store's value exactly. 3c is NOT
    redundant and is the site that is RIGHT - it alone carries the
    provenance mark and recomputes only what the app derived. The defect
    is that the unguarded site can undo the guarded one.
    Also note 9.2308 = 10 x 48 / 52: her stated weeks were used as the
    turns AND the divisor was still a literal 52.
    PROCESS: your working tree carries uncommitted app-code changes
    (intake_consult.py +148, section.py +95) - a 2026-09-22 write-time
    bounds guard that adds a NEW client-facing question, and the live
    :5050 backend is already serving it. Under TRIAGE-BEFORE-FIX that is
    the X2 class: new behaviour is Nick's call, never auto-built. Its
    docstring also claims the turn-12 catch as its own; turn 12 came from
    the unresolved-figure readback at intake_consult.py:16319, and the
    guard it generalises reads {"monthly": 12.0, "weekly": 53.0} - this
    row is contract, so it could not have fired. That is why this turn is
    needs-ruling rather than progress.

TASK:
  FOR NICK, ONE DECISION, then VS proceeds. VS has built (uncommitted) a
  write-time bounds guard that refuses a driver value its field cannot
  arithmetically hold, keeps the figure, and asks the client a new
  question about it. It is new client-facing behaviour, so it needs your
  yes or no before it ships. Nothing is asked of you mechanically - say
  the word and the flip happens here.

  FOR VS, ready to start the moment Nick rules - three turns, split by
  blast radius, in this order:

  TURN A (spot-check, on its own). Name the two unnamed sites in turn 13
  of bf731ee4: the one that wrote operating_periods_per_year=110 after
  the patch door, and the one that dropped annual_completed_units=1100
  between end of turn 13 and end of turn 15. Do not fix anything yet -
  the store rows are in replay_gate/_audit_ashgrove_write_path_20260922.md
  and my replay harness reproduces the inputs. This is the only thing
  standing between us and knowing why her stated annual count vanished.
  DEAL BREAKER it prevents: her stated 1,100 a year is in no field while
  the receipt told her it was recorded.

  TURN B (spot-check, on its own). _derive_capacity_cells
  (intake_consult.py:20228-20238) must not overwrite a
  units_per_week_capacity the CLIENT stated. 3c already has the rule and
  the mark (_units_per_week_derived_from_weeks); this site ignores both.
  Proof to re-run: a contract row carrying a stated 17/wk beside
  period=10, periods=119 must still read 17, and the weekly case must not
  change. DEAL BREAKER it prevents: she says seventeen a week and her
  plan is built on 22.9.

  TURN C (neighbor-check - this one genuinely changes shared high-fan-out
  code, so it travels alone). OPS_DRIVER_WRITE_ROUTED_BY_THE_QUESTION
  (intake_consult.py:17057-17070) decides whether a client's answer is
  stored or discarded on whether our own previous sentence happens to
  spell a row's product name. Ashgrove is the proof: 1,100 discarded at
  turn 11, 48 landed at turn 17, same door, same two rows. Whatever the
  fix is, it must make those two turns agree. Named neighbours to confirm:
  the Vasquez-Lindqvist ec2da9c7 turn-11 case this branch was built for,
  and the Thackeray 53a7603f open-ask path it falls through to. DEAL
  BREAKER it prevents: a client answers and the store holds nothing, or
  holds it under the wrong meaning.

  DECLARED-vs-ACTUAL, mine: declared spot-check, audit-only, store +
  committed source + the two conversion commits; loaded exactly that plus
  the run-time blob 4f52588d for the offline replays. No app code touched,
  no gate legs run, no canary. One deviation to declare: I did not close
  question (1) for the 110 - it is reported as open rather than asserted.
