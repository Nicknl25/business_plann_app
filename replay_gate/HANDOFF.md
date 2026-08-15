STATUS: awaiting-mini
TURN: 2/16
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
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_stream_discovery_f4_redproof.py (+ _20260815_PRE.txt RED 20 right-reason / _POST_offline.txt GREEN / _POST_live.txt GREEN with the REAL door); Test Files/_live_discovery_cormorant_clone_20260815_F4.txt GREEN (both prior FAILs); Test Files/_gate_only_R31_R32_20260815_F4.txt 2/2; docs/STREAM_DISCOVERY_SPEC.md Q2+Q5
  SUMMARY: F4 shipped, SPOT-CHECK, declared == actual (one honest widening: the caller's discovery answer block in intake_consult.py changed too - it must render the ONE clarify and hold the turn, and it hands the door in; declared in the plan's BLAST-RADIUS line).
    (1) THE DOOR = intake_consult._classify_restatement_response (the app's existing ACCEPT/REJECT/CLARIFY intent reader, already used by this same ops turn for the reply to the business-type restatement). read_stream_discovery_answer now calls it ONCE PER PROPOSED STREAM with a deterministic frame (gpt_stream_discovery.stream_discovery_intent_frame: the ask, the streams named, the ONE stream under judgment, the reading rules incl. a-word-inside-a-decline-is-not-a-yes, hedge/bare-yes-to-several => CLARIFY, each stream on its own words). ACCEPT=>yes REJECT=>no CLARIFY/None/exception=>unclear. ALL token/keyword/regex scoring deleted from the reader (_NEG_RE/_AFFIRM_RE/_ALL_RE/_ONLY_RE/_OTHERS_RE/_clauses gone; grep is in the red-proof). unclear => ONE clarify (new template constant STREAM_DISCOVERY_CLARIFY_TEMPLATE, rendered by the caller as confirm_clarify, turn held; yes-items on the same reply land NOW and lead it); clarify reply read the same way; still unclear => not confirmed, answer_reason unclear_after_clarify, never asked again. is_stream_discovery_ask recognizes the clarify as the window; the latch stores ask_text.
    (2) TEMPLATE: '...a lot of <type>s also offer <A>, <B> or <C> - is any of that part of your business today? (If so I will include it as a revenue line.) If not, just say so and we will move on.' - one constant, labels only interpolate, forbidden-phrase grep clean, one question mark.
    PROOF: PRE (old build via stash) RED for the RIGHT reason - phantom yes on the wholesale decline + receipt 'wholesale subscription contracts is its own line'. POST offline GREEN (stubbed door, plumbing). POST LIVE GREEN with the REAL door on nine replies: the two Cormorant declines => all no; 'yeah we do the retail bags' => only that yes; mixed => only the named stream; 'sort of, sometimes' and bare 'yes' (4 streams) => all unclear => ONE clarify, nothing appended, second unclear => not confirmed, no further ask; cafe set incl. 'no, we don't do a cafe' => no. Live Cormorant clone against restarted :5050 (ONE listener): ask renders with the clause + verb, answer path all-no, zero origin rows - both former FAILs green. _stream_discovery_redproof.py 106/106, f123 GREEN. Floor R31/R32 2/2 digests unchanged. Canary skipped (spot-check).
    NOTE for Nick's triage (not built): the door's ACCEPT default (its system prompt treats nuance as agreement) is what the frame text counters; the door itself was NOT edited. Cost: up to 4 door calls per discovery reply (+4 on a clarify), each a short classification.
TASK:
  TURN 2 (mini, SPOT-CHECK audit): (a) diff confined - git diff 51de964..HEAD: gpt_stream_discovery.py (template constants, clarify composer, is_stream_discovery_ask, reader section 5 replaced), intake_consult.py (_stream_discovery_ask_if_due stores ask_text; _apply_stream_discovery_answer 4-tuple + classify param + clarify hold; the call block renders the clarify as confirm_clarify), the two redproof suites + new f4 suite, spec Q2/Q5. Nothing in the judge, validator, seam, gate, capture, router, engine. (b) grep the reader for keyword/token logic: expect none (the f4 suite asserts it - verify independently). (c) PRE red right reason / POST green: rerun `python "Test Files/_stream_discovery_f4_redproof.py"` (offline) and `--live` (real door; needs .env key); the PRE txt is committed. (d) the door IS the app's existing intent door: name it (_classify_restatement_response) and confirm it is called, not edited (git diff shows no change to that function). (e) receipt law: no receipt without an append - the all-no receipt is 'Understood - none of those, we'll move on.'; the clarify turn carries no closing receipt. (f) floor: R31/R32 via --only. GREEN -> stop -> Nick re-runs Cormorant to verify validator fix + reader live at the CURRENT seam (seam move is a later, separate turn).
