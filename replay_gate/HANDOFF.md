STATUS: awaiting-mini
TURN: 3/16
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
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_discovery_lob_nesting_redproof_20260815_PRE.txt (9 red) / _POST.txt (GREEN); Test Files/_live_discovery_ninefathom_clone_20260815.txt (live GREEN); Test Files/_gate_only_R31_R32_20260815_lobnesting.txt (floor GOLDEN); VS_NOTES.md tail section
  SUMMARY: 1a DONE - stem_match_lob_index deleted; a confirmed discovered stream
  always gets its OWN LOB named for its label (append + carry re-append
  branch, same module); the 'own line under <lob>' receipt variant is gone.
  1b DONE - join_labels renders 'A, B, or C' for 3+ (2 = 'A or B', 1 = 'A').
  Diff = gpt_stream_discovery.py only (17+/39-). PRE red 9 on the exact Nine
  Fathom shape -> POST GREEN, numbers unchanged; existing discovery red-proofs
  GREEN; floor R31/R32 GOLDEN; LIVE rewound Nine Fathom clone on the restarted
  :5050 -> serial comma rendered, yes/yes/no/no -> two rows, two LOBs.
  'Primary line of business' placeholder: NOT in the placement path - named
  origin financials_year1._build_default_lobs (financials_year1.py:167) echoed
  by the ops model into ops.lob_models; LEFT, flagged for Nick.
  DECLARED-vs-ACTUAL: matches the plan (spot-check; loaded only HANDOFF +
  gpt_stream_discovery.py sections 6-7/template/join_labels + the two
  red-proof/clone runners + the Nine Fathom ops JSON read-only; canary skip).
  One divergence, additive: a NEW live clone runner was written for Nine
  Fathom (the plan said 'rewound Nine Fathom clone' - it did not exist, so it
  was built from the Cormorant runner; same call chain).
TASK:
  TURN 2 (mini, SPOT-CHECK audit): (1) diff confined to
  gpt_stream_discovery.py: stem_match_lob_index removed, both callers
  collapsed to lobs.append(own LOB), join_labels serial comma - nothing
  else; (2) PRE red / POST green on the Nine Fathom shape (Test
  Files/_discovery_lob_nesting_redproof.py + the two txt captures);
  numbers 19/260/.6, 13/140/.55, 58/380/.75 unchanged; (3) live clone
  txt: ask carries ', or ' before the last label; each yes -> own LOB;
  receipts 'is its own line;' with no 'under'; (4) floor R31/R32 GOLDEN
  digests unchanged. Green -> stop (flip awaiting-Nick). Nick's triage
  items carried in the RESULT: the 'Primary line of business' primary-LOB
  placeholder origin (financials_year1.py:167 default echoed by the ops
  model) - a naming rule for the primary LOB is a separate turn if he
  wants it; the seam move to :16794 remains the next neighbor-check turn.
