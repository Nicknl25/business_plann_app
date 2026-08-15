STATUS: awaiting-VS
TURN: 1/16
TASK:
  DISCOVERY PRESENTATION FIXES — Nick's ruling after confirming run #2
  (Nine Fathom Coffee Roasters, draft 6d2823db, record: _confirm_discovery_
  ninefathom_20260815.txt). SPOT-CHECK tier, discovery-path only. Judge,
  validator (F1-F3), reader (F4), seam, gate, capture, engine untouched.
  (The seam move to :16794 is a SEPARATE neighbor-check turn that follows
  this one — do not do it here.)
  TURN-TIMEOUT-MINUTES: 75
  TURN 1 (VS, SPOT-CHECK):
   1a LOB NESTING. A discovered stream nested UNDER another line's LOB:
      Model Inputs reads "retail coffee bags / wholesale coffee sales to
      grocery stores" — grocery wholesale is a PEER stream, not a
      sub-product of retail bags. Root: the LOB-PLACEMENT step in
      append_confirmed_stream_rows stem-matched on the category noun
      "coffee" (F1's class, one step downstream). FIX (semantic, not a
      heuristic): a confirmed discovered stream ALWAYS gets its OWN LOB,
      named for its label — discovery surfaces PEER streams by
      definition, so a discovered stream is never nested under another
      line. Delete the LOB stem-match placement. Also: if the generic
      "Primary line of business" placeholder LOB label originates in the
      same placement/naming path, fix it there (the primary LOB should
      carry the client's own line name, e.g. "Roasted coffee"); if it
      comes from elsewhere, NAME where and leave it (flag for Nick).
   1b SERIAL COMMA in the ask template: "wholesale coffee sales to
      grocery stores or brew gear and merchandise sales" ran two items
      together. For 3+ labels render "A, B, or C" (serial comma before
      the "or"); 2 labels "A or B"; 1 label "A". Template constant only;
      forbidden-phrase grep stays clean; the revenue-line clause stays.
   DEAL BREAKER (turn-plan law): none in the strict sense — Nick ruled
   both as presentation fixes on his read of the delivered workbook
   (a mislabelled LOB in the client's plan; an ambiguous question).
   SPOT-CHECK: red-proof the mis-nesting on the exact Nine Fathom shape
   (primary '5 lb bag roasted coffee' + confirmed 'retail coffee bags' +
   'wholesale coffee sales to grocery stores') -> PRE: 2nd row under LOB
   'retail coffee bags'; POST: each discovered stream its own LOB, drivers
   untouched (numbers 19/260/.6 and 13/140/.55 do not move); template
   renders the serial comma for 3 labels; rerun the discovery red-proofs
   GREEN; floor R31/R32 via --only; canary skip. Live: rewound Nine
   Fathom clone -> ask renders with the comma -> yes/yes/no -> two rows,
   two LOBs. Flip to mini.
  TURN 2 (mini, SPOT-CHECK audit): diff confined to append_confirmed_
  stream_rows placement + the template constant; PRE red / POST green on
  the Nine Fathom shape; numbers unchanged; floor. Green -> stop.
  (re-armed after the Cowork-tester dirty-tree fault; tree is clean now)
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
