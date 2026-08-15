STATUS: awaiting-VS
TURN: 0/16
TASK:
  DISCOVERY F4 — Nick's ruling: DEAL BREAKER, fix it — but NOT with the
  token/keyword heuristic mini sketched. "Scrap the keyword/affirmative-
  phrase approach — that's a string-matching heuristic and we don't do
  those." Two things, both consistent with how the rest of the app works.
  Discovery-path only, SPOT-CHECK tier. Judge, seam, gate, capture,
  validator (F1/F2/F3, already green) untouched. Floor R31/R32.
  TURN-TIMEOUT-MINUTES: 90
  TURN 1 (VS, SPOT-CHECK): DEAL BREAKER prevented: a phantom
  discovery_confirmed row + a false "is its own line" receipt on an
  explicit no (the guided-path reply shape to the ask). Two parts:
   (1) ROUTE THE ANSWER THROUGH INTENT, don't keyword-match. The client's
       reply to the discovery proposal goes through the SAME intent
       classifier the app already uses for every other client answer
       (the router / the yes-no-per-item reading the stage answers use —
       find the existing door and use it; do NOT write a new matcher).
       The answer is INFERRED per proposed candidate, never pattern-
       matched:
         intent affirmative ("yeah we've got a little cafe") -> confirm
           that stream -> the existing append + receipt + capture.
         intent negative ("no, we don't do a cafe" — even though "cafe"
           is in the sentence) -> NOT confirmed, nothing appended, no
           receipt claiming otherwise. A word appearing inside a decline
           is NOT a yes.
         intent ambiguous/unclear ("sort of, on weekends") -> CLARIFY
           with ONE question, don't guess either way (this supersedes the
           earlier "unclear => not confirmed" — record in the spec Q5).
           Exactly one clarify; the clarify answer is read the same way;
           still-unclear after that -> not confirmed, no re-ask.
       Zero keyword-presence logic, zero exact-phrase requirements in
       read_stream_discovery_answer — delete the token scoring; if the
       classifier cannot understand the answer, it asks.
   (2) TELL THE CLIENT WHY THEY'RE ASKED — briefly. The proposal must
       make clear a yes ADDS A REVENUE LINE to their plan, so they answer
       knowingly. ONE clause, not a lecture, e.g.:
         "A lot of <type>s also offer <A>, <B> or <C> — is any of that
          part of your business today? (If so I'll include it as a
          revenue line.) If not, just say so and we'll move on."
       Still the deterministic template constant; only labels
       interpolate. Use a template verb ("also offer ...") so the
       noun-phrase labels read naturally (closes the label-grammar WATCH
       item: "coffee roasters also <noun phrase>" read verb-less). No
       back-and-forth, no long explanation: one question, context
       included, move on.
   RED-PROOF BOTH WAYS on the reader (offline, the classifier door
   stubbed/real): "No, none of those. We just do the five pound
   wholesale bags." -> all NO, nothing appended (the bug, PRE red);
   "No. Retail bags no, subscriptions no. Just wholesale to cafes." ->
   all NO; "yeah we have a small cafe" -> affirmative -> appended;
   "no retail bags, but yes subscriptions" -> mixed, only subscriptions
   appended; "sort of, sometimes" -> ONE clarify rendered, nothing
   appended; a second unclear -> not confirmed, no further ask. The
   rendered proposal text contains the revenue-line clause and the
   forbidden-phrase grep stays clean. Rerun _stream_discovery_f123_
   redproof.py + _stream_discovery_redproof.py answer-path checks GREEN;
   the live Cormorant clone answer path (the 2 FAILs in _live_discovery_
   cormorant_clone_20260815.txt) turns GREEN. Floor R31/R32 via --only.
   Canary skip. Update docs/STREAM_DISCOVERY_SPEC.md Q2 (template) + Q5
   (intent-routed reader; unclear => one clarify). Flip to mini.
  TURN 2 (mini, SPOT-CHECK audit): diff confined to the reader + the
  template constant (+ spec); NO keyword/token matching remains in the
  reader (grep); PRE red / POST green on the six replies; the classifier
  used IS the app's existing intent door (name it); receipt law holds
  (no receipt without an append); floor. Green -> stop -> Nick re-runs
  Cormorant to verify the validator fix + reader live at the CURRENT
  seam (the seam move is a later, separate turn).
RESULT:
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
