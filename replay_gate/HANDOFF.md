STATUS: awaiting-VS
TURN: 1/16
TASK:
  DISCOVERY FIX F1+F2 — Nick's ruling after confirming run #1 (Cormorant
  Coffee Roasters, draft ec1e22ef; record: _confirm_discovery_cormorant_
  20260815.txt). VALIDATOR-ONLY, SPOT-CHECK tier. Do NOT touch the judge,
  the seam, the gate, the engine, or capture. The seam question is a
  SEPARATE research item Nick rules on later — do not move the seam.
  TURN-TIMEOUT-MINUTES: 90
  TURN 1 (VS, SPOT-CHECK): two fences in the stream-discovery validator
  (client_intake_and_finmo/intake_coherence/gpt_stream_discovery.py +
  the dedup call in intake_consult.py) are too aggressive on category-
  noun-heavy business types:
    F1 STEM DEDUP OVER-MATCHES ON THE CATEGORY NOUN. Today a candidate is
       dropped as matches_existing_line when it shares ANY one stemmed
       token >=4 chars with an existing line — for a coffee roaster every
       adjacent stream contains "coffee", so "office coffee supply
       accounts" and "private label coffee roasting" were wrongly deduped.
       FIX: dedup requires a DISTINGUISHING match — a shared token that is
       NOT the business-type/category noun (tokens of business_type /
       NAICS title / the lob name's category word), OR >=2 shared tokens.
       One shared category noun is not a duplicate. Generalizes to any
       category-noun-heavy type (landscaping, dental, ...). Do this
       inside discovery's dedup path — do NOT change
       _resolve_ops_product_line's behaviour for its other callers
       (corrections rely on it).
    F2 NUMBER-LINT DROPS SIZE QUALIFIERS. label_carries_number killed
       "12 oz retail coffee bags" — a SIZE descriptor, not a revenue
       number. The fence exists to stop fabricated FINANCIAL numbers.
       FIX: strip the numeric size qualifier from the label ("retail
       coffee bags") — and/or instruct the judge to omit sizes — NEVER
       drop the candidate for a size descriptor. Keep dropping labels
       that carry a money/volume figure ($, per week, 40 units).
    DEAL BREAKER named (turn-plan law): none in the strict sense — Nick
    ruled this a feature-effectiveness fix (silence on a business with
    common adjacent streams defeats discovery); it ships on his ruling.
    SPOT-CHECK: red-proof on the EXACT Cormorant latch input (the 8
    labels + the single existing line "Roasted coffee / 5 lb bag of
    roasted coffee", business_type "Coffee Roaster") -> pre-fix all 8
    dropped; post-fix "retail coffee bags" (size stripped), "private
    label coffee roasting", "office coffee supply accounts" SURVIVE while
    "wholesale coffee beans" and "online coffee bean sales" STAY deduped
    (primary / mentioned) and the three commonality_some stay dropped.
    Live: rewind-clone Cormorant to the seam and show the ask renders
    with the survivors (record the ask text verbatim — label grammar is a
    WATCH item). Floor R31/R32 via --only. No canary, no full prove.
    Flip to mini.
  TURN 2 (mini, SPOT-CHECK audit): diff confined to the validator/dedup
  path; red-proof PRE red / POST green on the Cormorant latch; the other
  _resolve_ops_product_line callers unchanged (grep + one correction leg
  via --only); ask text existence-framed, forbidden-phrase grep clean;
  floor. Green -> stop -> Nick re-runs the confirming run.
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
