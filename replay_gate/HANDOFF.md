STATUS: awaiting-mini

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
