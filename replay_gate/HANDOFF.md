STATUS: awaiting-VS

TURN: 2/16

TASK:
  YOUR TURN A, and Nick has ruled on your needs-ruling - the write-time bounds guard is approved and shipped (be2574a4), your provenance finding is fixed, and your U01 concern was well founded: the engine gate caught my first attempt at it as a regression and I rebuilt it your way round. Nick's words: "the first time an instrument stopped a fix from becoming the next defect." He has now made TURN C the priority, so I am taking Turn C - OPS_DRIVER_WRITE_ROUTED_BY_THE_QUESTION at intake_consult.py:17057-17070 - and you take TURN A, which is the one thing standing between us and knowing why her stated annual count vanished. TURN A, exactly as you scoped it: on draft bf731ee486254923986eb049688aed29, NAME THE TWO UNNAMED SITES. (1) the site that wrote operating_periods_per_year=110 after the patch door in turn 13 - you proved ANNUAL_PAIR_HOMED cannot be it, because it needs a ceiling that was never emitted and it would have popped annual_completed_units and set utilization_rate, and the store shows both untouched at end of turn 13; your replay of the stored turn-11 ops plus the exact turn-13 patch yields periods=None, so something between the patch door and the end of that turn wrote it. (2) the site that dropped annual_completed_units=1100 between end of turn 13 and end of turn 15, given _apply_ops_product_overrides had stored it on BOTH rows at turn 13 and the store and your replay agree on that. Do not fix either - name them, with function and line, and say which one is the deal breaker. Your replay harness and replay_gate/_audit_ashgrove_write_path_20260922.md already have the inputs. ONE MORE THING WORTH YOUR EYE WHILE YOU ARE IN THERE: at turn 14 the app told her she finishes about 1,100 SHORT-RUN PRINT JOBS a year, a figure she never gave for a line she had not discussed, and the print row holds nothing - so the receipt invented a number for a second line. If that falls out of the same site as (2), say so; if it is its own writer, name it and I will take it after Turn C. No app-code changes in this turn, audit only, and read the STORE.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.

RESULT:
  AGENT: mini
  VERDICT: progress
  ERROR-SIGNATURE: apply_model_ops_patch:consultant_snapshot_erases_annual_completed_units
  EVIDENCE: replay_gate/_audit_ashgrove_two_sites_20260922.md
    (proof: replay_gate/_audit_ashgrove/prove_two_sites.py, re-runnable,
     output saved beside it; store tables intake_turn_reader_extracts +
     intake_turn_interpretations + intake_consult_drafts.messages_json +
     run_vitals_gpt_calls for draft bf731ee4)
  SUMMARY:
    BOTH SITES ARE ONE FUNCTION, and it is neither of the ones we were
    looking at: _apply_model_ops_patch, intake_consult.py:1334-1348. The
    OPS CONSULTANT returns a full lob_models snapshot every turn and this
    door assigns it wholesale.
    (1) THE 110 IS THE MODEL'S OWN ARITHMETIC. operating_periods_per_year
    is a REQUIRED key in the ops consultant's strict schema
    (intake_consultant.py:546-585); it had just said "10 at once" and
    "1,100 a year" and emitted 1,100/10. No code site in the live tree can
    produce it - I eliminated every periods writer, the alias fold, and
    ANNUAL_PAIR_HOMED (needs a ceiling; would have popped the actual and
    set utilisation - the store shows neither). Replayed on the real store
    row it reproduces the store to the rounding: per=10, periods=110,
    week=21.1538 (4 dp = _derive_capacity_cells, so periods was there
    first). run_vitals_gpt_calls puts that consultant call at 19:38:54,
    between the turn-11 extract (no 110) and turn 13 (110).
    (2) THE SAME ASSIGNMENT DROPPED HER 1,100. _carry_forward_per_line_drivers
    restores only the keys in _CARRIED_PER_LINE_KEYS
    (intake_consult.py:15628-15639) and annual_completed_units has never
    been in that tuple. Her figure landed at 19:39:38 and was gone by
    19:39:45. This is the Vasquez-Lindqvist "landed, for thirteen seconds"
    class recurring on the one driver name the list never picked up.
    (2) IS THE DEAL BREAKER. 10 x 110 still returns her 1,100, so (1) is
    survivable alone; it is the erasure that leaves the turns slot as the
    only home of her volume, so the 48 cut her year to 480 with nothing
    left to notice.
    STILL LIVE ON HEAD (1afb4d48), proven end to end in the same script:
    the keeper from fd1107f4 writes her 1,100 at the patch door and the
    same turn's consultant snapshot erases it again. So
    ANNUAL_COMPLETIONS_HOMED and the contradiction hold at
    intake_consult.py:892+ both read a field that is gone by the next turn
    - THE KEEPER IS NOT KEPT. Turn C's routing change saves Ashgrove
    specifically (the bare 48 is now refused as row-ambiguous on two
    rows); a single-line business still walks the whole path.
    (3) THE PRINT-LINE 1,100 WAS NOT A RECEIPT INVENTION. The turn-13
    ROUTER patch named both lines and _apply_ops_product_overrides
    (intake_consult.py:3446) wrote 1,100 to both rows; the turn-14 message
    read that write back truthfully. The invention is in the router's
    per-line patch when she named no line - your Turn C door, one turn
    apart - not a second erasure site.
    CORRECTION TO MY OWN LAST AUDIT: the run was on 592d2583, not
    4f52588d. The store's call_site (intake_consult.py:22727) is that
    commit's line; 4f52588d has it at 22750 and the backend was never
    restarted. Doors byte-identical across the two, so every diagnosis
    stands, but the "3c earns its place" ruling was about a block that was
    not running during this run.
    PROCESS: your TASK cites be2574a4 for the approved bounds guard -
    that commit is scripts/store_tick.py; the guard and keeper are
    fd1107f4 + 1ba47652. And there has been no TURN PLAN [VS] in the
    watcher log since 09-10, so your declared-vs-actual could only be
    audited against the TASK text and the commits.

TASK:
  TURN A2 (NEIGHBOR-CHECK, travels alone - _carry_forward_per_line_drivers
  is shared high-fan-out code: every ops-consultant restatement of every
  business goes through it). Make the carry-forward carry the annual pair:
  add annual_completed_units - and annual_capacity_units, which can sit at
  rest on a row before a concurrent figure arrives - to
  _CARRIED_PER_LINE_KEYS (intake_consult.py:15628). DEAL BREAKER it
  prevents: a figure the client stated is erased seconds after it lands,
  the turns slot becomes the only home of her annual volume, and one
  ordinary later answer cuts her year by 56% (Ashgrove: 1,100 -> 480) with
  no field left that could contradict it.
  NAMED NEIGHBOURS to confirm, not the 61-leg universe:
    - ANNUAL_PAIR_HOMED (intake_consult.py:679-704): a carried
      annual_completed_units beside a ceiling that arrives LATER must
      still home to utilisation and pop, exactly as today. The
      TheAnnualPairForAnyConcurrentBusiness pin is the guard on this.
    - the contradiction hold (intake_consult.py:892+, 1ba47652): with the
      figure now surviving, it must NOT fire on a correctly homed pair -
      re-run its own tests, they were written against a row that lost the
      field.
    - the per-line COGS carry rule in the same function (the "null means
      no statement" branch) must be unchanged.
  PROOF TO RE-RUN, and it is the one that matters:
  replay_gate/_audit_ashgrove/prove_two_sites.py must end with "her 1,100
  still on a row after the snapshot? True" on your fix, and the two
  592d2583 sections must be untouched (they are the historical record,
  they should still reproduce the store).
  PIN IT GENERAL, not on Ashgrove: a property over varied shapes - for any
  row carrying a client-stated per-line driver, an ops-consultant snapshot
  that does not mention that driver leaves it on the row.

  ALSO WORTH YOUR EYE (not a fix TASK):
    - In my HEAD replay the keeper did not home the turns at the per-line
      door: annual_completed_units=1100 sat beside period=10 with
      periods=None, because ANNUAL_COMPLETIONS_HOMED lives in
      _normalize_ops_capacity_compat and that path did not reach it.
      Confirm the keeper's site actually runs where her figure lands.
    - On HEAD the turn-13 replay logs IMPLAUSIBLE_WRITE_HELD
      field=units_per_week_capacity value=10.0 cadence=contract - the new
      guard asking her about a 10/week the app itself derived at turn 9.
      Observation, not a finding.
    - messages_json[10] carries asked_field=operating_periods_per_year on
      a sentence that plainly asks for annual completions, a field that
      was already askable. Prompt/model behaviour - surfaced for Nick,
      never auto-built.

  DECLARED-vs-ACTUAL, mine: declared spot-check tier, audit-only, no app
  code, no legs, no canary - and that is exactly what ran. Loaded: the
  store rows for turns 9-19, the committed sources at 592d2583 and HEAD,
  my prior audit, and the ops consultant's schema (added to the declared
  list mid-turn - it is where the 110 came from). One deviation: the
  turn-14 receipt composer named in my plan turned out not to be a writer
  at all, so I named the router patch instead. Nothing declared was
  skipped. The single-line floor: no app-code line changed this turn, so
  the floor is the proof script, and it runs green.
