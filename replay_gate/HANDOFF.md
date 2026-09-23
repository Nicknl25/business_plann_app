STATUS: awaiting-mini

TURN: 1/16

TASK:
  YOUR TURN A, and Nick has ruled on your needs-ruling - the write-time bounds guard is approved and shipped (be2574a4), your provenance finding is fixed, and your U01 concern was well founded: the engine gate caught my first attempt at it as a regression and I rebuilt it your way round. Nick's words: "the first time an instrument stopped a fix from becoming the next defect." He has now made TURN C the priority, so I am taking Turn C - OPS_DRIVER_WRITE_ROUTED_BY_THE_QUESTION at intake_consult.py:17057-17070 - and you take TURN A, which is the one thing standing between us and knowing why her stated annual count vanished. TURN A, exactly as you scoped it: on draft bf731ee486254923986eb049688aed29, NAME THE TWO UNNAMED SITES. (1) the site that wrote operating_periods_per_year=110 after the patch door in turn 13 - you proved ANNUAL_PAIR_HOMED cannot be it, because it needs a ceiling that was never emitted and it would have popped annual_completed_units and set utilization_rate, and the store shows both untouched at end of turn 13; your replay of the stored turn-11 ops plus the exact turn-13 patch yields periods=None, so something between the patch door and the end of that turn wrote it. (2) the site that dropped annual_completed_units=1100 between end of turn 13 and end of turn 15, given _apply_ops_product_overrides had stored it on BOTH rows at turn 13 and the store and your replay agree on that. Do not fix either - name them, with function and line, and say which one is the deal breaker. Your replay harness and replay_gate/_audit_ashgrove_write_path_20260922.md already have the inputs. ONE MORE THING WORTH YOUR EYE WHILE YOU ARE IN THERE: at turn 14 the app told her she finishes about 1,100 SHORT-RUN PRINT JOBS a year, a figure she never gave for a line she had not discussed, and the print row holds nothing - so the receipt invented a number for a second line. If that falls out of the same site as (2), say so; if it is its own writer, name it and I will take it after Turn C. No app-code changes in this turn, audit only, and read the STORE.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
