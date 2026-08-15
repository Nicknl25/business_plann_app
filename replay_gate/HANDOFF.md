STATUS: awaiting-Nick
TURN: 2/16
TASK:
  DISCOVERY FIX F1+F2+F3 (RE-SEEDED: the first launch was killed at 4 min to fold in F3 — start fresh; a partial edit was discarded) — Nick's ruling after confirming run #1 (Cormorant
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
    F3 PROPOSAL CAP OF 4 (Nick, 2026-08-15 — a UX/cognitive-load limit on
       the QUESTION, NOT a business heuristic: a client cannot meaningfully
       answer a laundry-list ask in one breath). The judge/band-gate may
       surface however many genuinely-common streams it finds; the ASK
       proposes AT MOST 4. If MORE than 4 survive the band-gate, propose
       the 4 STRONGEST by band — ALL `most` first, then fill remaining
       slots with `many` (so the 4 asked-about are the 4 most likely to
       apply, never an arbitrary 4). If 4 or fewer survive, propose all,
       no padding. Still ONE ask, one turn. The cap applies to the
       PROPOSAL ONLY — never block what the client can volunteer through
       the normal flow (do not build/test a >4-volunteered path; just do
       not block it). Store the full survivor list AND the proposed slice
       in the latch (auditable: `survivors` vs `proposed`). It is a slice
       of the survivor list in the validator — same surface, same
       spot-check radius as F1/F2. Red-proof: 6 synthetic survivors
       (2 most, 4 many) -> proposed = the 2 most + first 2 many, ask names
       exactly 4; 3 survivors -> all 3.
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
  path (F1 dedup, F2 size-strip, F3 most-first slice of <=4); red-proof PRE red / POST green on the Cormorant latch; the other
  _resolve_ops_product_line callers unchanged (grep + one correction leg
  via --only); ask text existence-framed, forbidden-phrase grep clean;
  floor. Green -> stop -> Nick re-runs the confirming run.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: read_stream_discovery_answer:single_token_mention_flips_explicit_no_to_yes
  EVIDENCE: 800c855; Test Files/_stream_discovery_f123_redproof.py (+ _20260815_PRE.txt RED 7 fails = the exact Cormorant latch reproduced, all 8 dropped / _20260815_POST.txt GREEN 55 checks); Test Files/_stream_discovery_redproof_20260815_postF123.txt (original red-proof still GREEN 96); Test Files/_live_discovery_cormorant_clone_20260815.txt (live ask verbatim + latch); Test Files/_gate_only_R31_R32_20260815_F123.txt (floor GREEN 2/2); Test Files/_discovery_reader_F4_repro_20260815.txt
  SUMMARY: F1+F2+F3 SHIPPED validator-only (gpt_stream_discovery.py section 3 + the ONE call site in _stream_discovery_ask_if_due; judge prompt, seam, gate, engine, capture, _resolve_ops_product_line untouched - discovery no longer calls the resolver; its correction callers unchanged, verified). F1: discovery_dedup_reason - category nouns = business_type + NAICS-title stems (+ the LOB name's category word); matches_existing_line needs a NON-category shared token or >=2 shared with one row; NEW ground mentioned_by_client (distinguishing tokens covered by the client-confirmed description / unit descriptions) is what keeps 'wholesale coffee beans' + 'online coffee bean sales' deduped on Cormorant (row-name tokens alone are {roasted, coffee} - the task's expected outcome is unreachable without it; flag if Nick disagrees). F2: strip_size_qualifiers ('12 oz'/'5 lb'/'500ml'/'2-pack') -> label kept, judge_label recorded on the candidate; $/per-week/count figures still label_carries_number. F3: STREAM_DISCOVERY_PROPOSAL_CAP=4, propose_from_survivors most-first then many; latch = candidates(asked) + proposed + survivors + proposal_cap + dropped. Offline: exact Cormorant latch PRE red -> POST green (retail coffee bags / office coffee supply accounts / private label coffee roasting asked; wholesale/online deduped; 3 some dropped); 6 survivors -> 4 asked, 3 -> 3. LIVE (rewound clone of ec1e22ef, real judge): the ask RENDERED at the seam on the growth-lever turn: 'Before we wrap up operations: a lot of coffee roasters also wholesale subscription contracts, retail coffee bags, single-origin limited release coffees or direct-to-consumer coffee subscriptions. Is any of that part of your business today? If not, just say so and we'll move on.' - 16 judged, 10 survivors, 4 proposed (the one most first), '12 oz retail coffee bags' stripped -> duplicate of the judge's own 'retail coffee bags'. LABEL GRAMMAR WATCH: 'coffee roasters also <noun phrase>' reads verb-less; template untouched (not in task). DECLARED-vs-ACTUAL: matches - spot-check tier, files as declared, canary skipped, floor R31/R32 via --only GREEN. VERDICT progress not green because the live clone SURFACED F4 (out of scope, NOT built): the ANSWER READER (section 5) read 'No, none of those. We just do the five pound wholesale bags.' as YES for 'wholesale subscription contracts' on the single shared token 'wholesale' (clause 'we just do the ... wholesale bags' names it, no negation in that clause) -> receipt 'Noted - wholesale subscription contracts is its own line' + a discovery_confirmed row appended ON AN EXPLICIT NO. Repro in _discovery_reader_F4_repro_20260815.txt ('No. Retail bags no, subscriptions no. Just wholesale to cafes.' -> yes as well). Same class as F1 (one-token over-match) in the reader; the 2 FAILs in the live file are this. Deal-breaker candidate: a false receipt + phantom line on the guided path (row is null-driver; the cascade then asks its numbers). Fix shape if ruled: a clause names a candidate only on a distinguishing token or >=half its tokens, and a leading whole-reply 'no/none of those' settles all NO. Nick's call.
TASK:
  TURN 2 (mini, SPOT-CHECK audit of 800c855):
  - diff confined to the validator/dedup path: gpt_stream_discovery.py section 3 (+ docstring/constants) and the one validate_stream_candidates call in _stream_discovery_ask_if_due; the judge prompt/_SUBMIT_TOOL, the seam, the reader, carry, resolver unchanged (git diff 4fcbdee..800c855 -- python/).
  - red-proof: run Test Files/_stream_discovery_f123_redproof.py (GREEN); confirm the PRE file is red for the RIGHT reason (the exact 8-drop latch reproduced, then AttributeError on the new helpers).
  - _resolve_ops_product_line callers unchanged: grep + one correction leg via --only (your pick from the correction legs).
  - ask text existence-framed, forbidden-phrase grep clean (live file has it verbatim); floor R31/R32 GREEN (file attached).
  - classify F4 (the reader defect) for Nick's triage: deal breaker or not; it is NOT built. Recommend: if deal breaker, one spot-check turn for VS on read_stream_discovery_answer only.
  - the mentioned_by_client dedup ground was VS's design call to reach the task's expected outcome (wholesale/online stay deduped) - flag it to Nick as a check, not a finding, unless you see a hole.
  Green -> STATUS awaiting-Nick (Nick re-runs the confirming run once F4 is ruled).
RESULT:
  AGENT: mini
  VERDICT: needs-ruling
  ERROR-SIGNATURE: read_stream_discovery_answer:single_token_mention_flips_explicit_no_to_yes
  EVIDENCE: Test Files/_mini_gate_only_R31_R32_R11_R37_20260815_F123audit.txt (4/4 GREEN); Test Files/_stream_discovery_f123_redproof.py rerun by mini GREEN; _stream_discovery_f123_redproof_20260815_PRE.txt (RED for the right reason); git diff 4fcbdee..800c855 -- python/ (2 files: gpt_stream_discovery.py section 3 + docstring/constants; intake_consult.py hunks ONLY inside _stream_discovery_ask_if_due @11728/@11747); _live_discovery_cormorant_clone_20260815.txt line 120 (ask verbatim); _discovery_reader_F4_repro_20260815.txt
  SUMMARY: SPOT-CHECK AUDIT OF 800c855 (F1+F2+F3) = GREEN. (1) diff confined as declared: gpt_stream_discovery.py (validator section 3, new helpers strip_size_qualifiers / discovery_category_tokens / discovery_dedup_reason / propose_from_survivors, STREAM_DISCOVERY_PROPOSAL_CAP=4) + the ONE call site in _stream_discovery_ask_if_due (resolve_line arg -> naics_title, latch adds proposed/survivors/proposal_cap). Judge prompt, _SUBMIT_TOOL, seam, reader (section 5), carry, _resolve_ops_product_line def (6787) untouched; its 3 correction callers (6902 cross-section driver correction, 10084 forward move, 17952 handler) unchanged - resolver name appears in the diff only inside comments/removed discovery call. (2) red-proof: PRE red for the RIGHT reason - the exact Cormorant 8-drop latch reproduced through the real _stream_discovery_ask_if_due (12 oz -> label_carries_number, wholesale/office/private/online -> matches_existing_line, 3 some), then AttributeError on discovery_category_tokens; POST rerun by me GREEN incl. resolver-behaviour-unchanged check. (3) VS TIER CALL honest: no shared high-fan-out code changed - spot-check stands. VS DECLARED-vs-ACTUAL (watcher.log 15:52:44) matches files/verify/canary-skip. (4) floor: --only R31,R32 + correction legs R11 (production turn path) + R37 (scoped correction path) = 4/4 clear. (5) live ask existence-framed, forbidden-phrase grep PASS, no digit, proposed = 4-slice most-first of 10 survivors. Label-grammar WATCH stands ("coffee roasters also <noun phrase>" verb-less; template not in task).
    F4 TRIAGE (mini classification, NOT built): DEAL BREAKER. Mechanism independently confirmed in read_stream_discovery_answer: the clause "we just do the five pound wholesale bags" scores 1 hit on 'wholesale', is the sole winner => named, clause not negated => YES; receipt "Noted - wholesale subscription contracts is its own line" + a discovery_confirmed row appended on an EXPLICIT "No, none of those". Guided path (the natural reply shape to the ask), false receipt + phantom line the cascade then asks numbers for => wrong line stored / receipt lies. Passes the triage test. Recommend ONE spot-check turn for VS on read_stream_discovery_answer only (fix shape: a clause names a candidate only on a distinguishing token or >=half its tokens; a leading whole-reply no/none-of-those settles all NO before clause scan; positive controls: "yes, we do wholesale subscription contracts" -> yes; "no retail bags, but yes subscriptions" -> mixed). No new behavior - a reader fence tightening.
    mentioned_by_client CHECK for Nick (not a finding, no hole found in the rule itself): it is the ground that keeps wholesale/online deduped on Cormorant, as the task expected. Design note: "mentioned" != "captured" - a stream the client DESCRIBED but never captured as a line is now silently deduped rather than asked; if Nick wants discovery to prompt on described-but-uncaptured streams, that is a ruling, not a bug. Thresholds (all of <=2 distinguishing tokens; >=2 and majority otherwise) look sound on the live 10-survivor set. Also noted (not a finding): tok_hit prefix rule leaves roaster/roasted/roasting mutually non-matching - inherited from the resolver rule, harmless here.
    DECLARED-vs-ACTUAL (mini): matches - spot-check tier, files as declared, canary skipped, legs R31/R32 + R11/R37 via --only.
TASK:
  FOR NICK (plain English): F1+F2+F3 audited GREEN - the validator fix is good. Before you re-run the confirming run, one ruling: F4 - when the client answers the discovery ask with "No, none of those, we just do wholesale bags", the reader hears YES for "wholesale subscription contracts" and writes a phantom line with a receipt saying so. mini classifies this a DEAL BREAKER (false receipt + phantom line on the guided path). Say "fix F4" and VS gets the turn below; say "run as is" and the confirming run proceeds with the reader unchanged (the phantom will recur on any 'no' that names an existing product word).
  TURN 3 (VS, SPOT-CHECK, only if Nick rules "fix F4"): read_stream_discovery_answer (gpt_stream_discovery.py section 5) ONLY. Deal breaker prevented: phantom discovery_confirmed row + false "is its own line" receipt on an explicit no. (a) a whole-reply leading negation ("no", "none of those", "neither", "nothing like that") settles ALL candidates NO before the clause scan unless a later clause AFFIRMS a candidate by name (>=half its tokens or a distinguishing token); (b) a clause names a candidate only when it hits a DISTINGUISHING token (not shared with the client's own captured product/unit names or the category noun) or >=half of the candidate's tokens. Red-proof PRE red / POST green on the 4 replies in _discovery_reader_F4_repro_20260815.txt plus positive controls (plain yes by name; mixed yes/no; "just X" others-no; unclear stays unclear). Rerun _stream_discovery_f123_redproof.py + _stream_discovery_redproof.py (answer-path checks) GREEN; the live clone answer path (the 2 FAILs) turns green. Floor R31/R32 via --only. Canary skip. Flip to mini.
