STATUS: awaiting-Nick
TURN: 2/16
TASK:
  STREAM DISCOVERY BUILD — Nick APPROVED docs/STREAM_DISCOVERY_SPEC.md
  (2026-08-15, HEAD carries the approved text). Build it exactly as the
  spec says. Deal-breaker board is CLEAN; this is the only work item.
  TURN-TIMEOUT-MINUTES: 150
  TURN 1 (VS, NEIGHBOR-CHECK tier — the insertion is the shared ops
  wrap-up path; NO engine math, NO canary, NO full prove):
    Build proactive stream discovery per the spec:
    - stream_discovery_evidence_level (Python-gated: thin ⇒ no GPT call,
      no ask; thin = no business_type / NAICS unresolved / pre-revenue /
      empty client line list). Operating + early-stage only.
    - ONE fenced GPT category judgment per draft in the demand-judge
      pattern (forced tool call, seed, validator not prompt): inputs =
      business_type, business_naics_6 + NAICS title, stage, geography,
      the client's own lob_models/products + description. Returns
      candidates[] of {label, commonality in most|many|some} — LABELS
      ONLY, never a number. NO cohort/CBP data in the inputs.
    - Validator: drop commonality=some; drop labels stem-resolving to an
      existing line (_resolve_ops_product_line); drop labels carrying
      addition verbs (add/expand/consider/start/launch/new); NO COUNT CAP
      ANYWHERE (Nick's correction: the band IS the gate; the number
      surfaced is a judgment). Empty ⇒ asked:false reason stored.
    - The ask = ONE deterministic template constant, existence-framed
      ("...a lot of <type>s also <A>, <B> or <C>. Is any of that part of
      your business today? If not, just say so and we'll move on."),
      fired ONCE at the end-of-ops seam intake_consult.py ~:20116 (after
      _ops_ready_for_wrap_from_gate_obj is True, BEFORE the
      competitive-advantage proposal) AND at the follow-up mirror ~:19080.
      Holds the turn the established way (finalize_ready=False + return).
    - Answer handling: yes per candidate ⇒ PYTHON appends the product row
      deterministically (product_name=label, drivers null, origin=
      discovery_confirmed) under the stem-matched LOB or a new LOB, with a
      receipt that says exactly that; the existing cascade then captures
      its five fields (never estimate a number for a discovered stream).
      no ⇒ stored, never re-asked. unclear ⇒ NOT confirmed (ruled), stored
      as unclear, never re-asked.
    - Storage: operating_model_json.stream_discovery latch (asked,
      asked_turn_index, business_type, naics_6, candidates w/ commonality
      + answer, dropped w/ reason, version) — CARRIED FORWARD through
      consultant_finalize at both ops_json=final_obj sites (the way
      competitive_advantage / business_naics_6 are rescued) and `origin`
      added to BOTH strict schemas (finalize + turn) so finalize keeps it.
    Verify (declare in your TURN PLAN): SPOT-CHECK the discovery logic
    (red-proof: thin ⇒ no ask; band-gate drops some; stem dedup drops a
    paraphrase; addition-verb lint; forbidden-phrase grep on the emitted
    ask; yes appends a row with origin that SURVIVES finalize; no/unclear
    never re-asked) + NEIGHBOR-CHECK the named neighbors: consultant_
    finalize latch-carry at both sites, both cascade hooks, the strict
    schemas, competitive-advantage proposal still fires once after the
    ask resolves, milestone question unchanged, a thin single-line draft
    byte-identical to today (floor R31/R32 via --only). Live: one rewound
    multi-line clone through propose -> yes -> cascade captures the new
    line -> wrap clean; one thin clone with NO ask. Then flip to mini.
  TURN 2 (mini, NEIGHBOR-CHECK audit): artifact-audit the finalize
    latch-carry (origin + stream_discovery present AFTER ops finalize),
    both hooks (main cascade + follow-up mirror both fire), the schemas,
    the validator fences (grep: no count cap constant exists), the
    template constant + forbidden phrases, VS's tier call. On a clean
    table: VERDICT green -> the watcher stops and pings Nick, who then
    drives the TWO confirming Cowork runs (garden centre that omits
    design/consultation -> propose/yes/capture/wrap-clean; thin single-line
    niche -> silence, byte-identical). Discovery is DONE only when both
    runs prove out; new findings are triaged for Nick, never auto-fixed.
  Standing laws every turn: TURN PLAN first, context scoped, spot-check
  default / neighbor-check here, floor every turn, declared-vs-actual.
RESULT:
  AGENT: VS
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_live_stream_discovery_clones_20260815.txt (LIVE, both clones GREEN);
    Test Files/_stream_discovery_redproof_20260815.txt (95/95 offline red-proofs);
    Test Files/_gate_only_R31_R32_20260815_streamdiscovery.txt (floor 2/2 clear);
    Test Files/_live_stream_discovery_util_probe_20260815.txt (utilization null-until-asked)
  SUMMARY: STREAM DISCOVERY BUILT per docs/STREAM_DISCOVERY_SPEC.md. New module
    python/client_intake_and_finmo/intake_coherence/gpt_stream_discovery.py
    (evidence gate thin=>no call/no ask; ONE forced-tool seeded judge, labels+
    commonality only; validator drops some/stem-dup/addition-verb/number/dup,
    NO count cap; ONE template constant; deterministic per-candidate reader;
    Python appends origin=discovery_confirmed rows; carry helper re-attaches the
    latch + re-stamps origin after every wholesale lob_models replace and
    SCRUBS any model-invented origin). intake_consult.py: ask hook at the
    gate-cascade seam (after _ops_ready_for_wrap_from_gate_obj, before the
    competitive-advantage proposal) + the follow-up mirror; answer handler
    (persists first, receipt LEADS even after the cascade replaces the text,
    controller note to the consultant, router skipped); carry at BOTH
    ops_json=final_obj sites + after BOTH model-patch applications. origin
    added to BOTH strict schemas + prompt lines. LIVE (Thornfield clones,
    rewound to the growth-lever turn): rich => template ask fired listing the 2
    band-gated survivors (dropped list w/ reasons latched), yes/no per item
    read correctly, row appended (5 rows), receipt led, cascade asked its
    capacity, price, utilization (proposed 60% -> client said 70% -> 0.7),
    competitive advantage fired ONCE after, milestone once, wrap CLEAN to
    market, latch + origin SURVIVED finalize. thin (pre-revenue) => no ask,
    latch asked:false reason thin (stage_not_discoverable), competitive
    advantage fired exactly as today. Floor R31/R32 clear.
  DECLARED-vs-ACTUAL: matches the TURN PLAN (neighbor-check tier; canary
    skipped; legs R31,R32 --only; both live clones ran). One addition beyond
    the plan text, inside the declared files: the origin SCRUB in the carry
    helper (found live: the strict-schema model wrote invented origin values
    on ordinary rows on the very first thin clone) - a guard on the same
    changed path, no new file, spot-check red-proofed.
  WATCH (for mini/Nick, not built): (1) utilization on ANY late-added row is
    proposed-then-agreed by the existing ops prompt law; runs 1-2 stored 0.6
    on the discovered row after a $400-only reply to a bundled price+util
    question (my responder never countered) - the probe run shows the row is
    null-until-asked and run 3 captured the client's 70%; whether a bundled
    proposal + non-countering reply should count as agreement is a pre-existing
    class for every row (CW-017c exempts first captures) - flagged for triage,
    not touched. (2) the stem resolver drops labels sharing a common word with
    an existing line ('...sales' vs 'Plant and nursery sale' => ambiguous) -
    conservative by design (silence is free); recorded in the latch dropped[]
    with reason matches_existing_line_ambiguous. (3) the ops-turn GPT sometimes
    asks its own last question before declaring finalize-ready, so the seam is
    reached one turn later - the live scripts loop up to 3 turns for it.
TASK:
  TURN 2 (mini, NEIGHBOR-CHECK audit of the stream-discovery build; do NOT
  re-derive VS reasoning - audit ARTIFACTS):
  TURN-TIMEOUT-MINUTES: 90
    1. Finalize latch-carry: in Test Files/_live_stream_discovery_clones_20260815.txt
       the RICH clone's post-finalize dump shows stream_discovery (asked:true,
       answers) AND exactly one row with origin=discovery_confirmed after the
       draft reached market. Cross-check the code: intake_consult.py has
       _sdisc.carry_stream_discovery(ops_json, final_obj) at BOTH
       ops_json = final_obj sites (grep count == 2) and after BOTH model-patch
       applications (_ops_before / _ops_before_fu).
    2. Both hooks: grep STREAM DISCOVERY (spec Q4) [main cascade seam] and
       STREAM DISCOVERY mirror [follow-up path]; the seam is AFTER
       _ops_ready_for_wrap_from_gate_obj and BEFORE the competitive-advantage
       injection; the ask sets finalize_ready False + ops_ready_for_wrap False.
    3. Schemas: intake_consultant.py carries origin in BOTH strict product
       schemas (properties + required, count 2 each) + the two prompt lines.
    4. Validator fences: gpt_stream_discovery.py - COMMONALITY_SURVIVES ==
       (most, many); ADDITION_VERBS lint; stem dedup via the caller's
       _resolve_ops_product_line (unique OR ambiguous => dropped); assert NO
       count-cap constant exists (the red-proof greps for it; re-grep yourself).
    5. Template + forbidden phrases: STREAM_DISCOVERY_ASK_TEMPLATE is the one
       constant; the emitted live ask (artifact line 1 of section A) contains
       none of consider / add / expand / could you also / would you.
    6. Reader: read_stream_discovery_answer cases in _stream_discovery_redproof.py
       (yes/no per item, bare yes w/ several candidates => unclear, never guess
       WHICH; the others no => no).
    7. VS's tier call: neighbor-check - the change inserts into the shared ops
       wrap-up path; no engine math, no workbook builder, no golden change;
       floor R31/R32 clear on the final code. Confirm or flag.
    8. Triage the WATCH items above for Nick (utilization first-capture class is
       pre-existing; do not build).
  On a clean table: VERDICT green -> the watcher stops and pings Nick, who
  drives the TWO confirming Cowork runs per the spec ((a) garden centre that
  omits a common stream -> propose/yes/capture/wrap-clean; (b) thin single-line
  niche -> silence, byte-identical). New findings are triaged for Nick, never
  auto-fixed.
RESULT:
  AGENT: mini
  VERDICT: green
  ERROR-SIGNATURE: none
  EVIDENCE: Test Files/_gate_only_R31_R32_20260815_mini_audit.txt (floor re-run by
    mini on HEAD 8315341/7744a26: 2/2 clear, SHAs identical to VS's run:
    model_input 1d50e46a.. finmo 24e38de4.. workbook cbd76463..);
    Test Files/_live_stream_discovery_clones_20260815.txt (rich + thin clones);
    Test Files/_stream_discovery_redproof_20260815.txt (95/95)
  SUMMARY: NEIGHBOR-CHECK audit of the stream-discovery build (8315341), all 8
    items CONFIRMED against artifacts + source, no VS reasoning reused:
    (1) latch-carry: rich clone post-finalize dump shows stream_discovery
    asked:true w/ answers AND exactly one origin=discovery_confirmed row after
    the draft reached market; intake_consult.py: `ops_json = final_obj` count
    == 2 and `carry_stream_discovery(ops_json, final_obj)` count == 2 (:19435,
    :20787), carry after both patch applications (:19265 _ops_before_fu,
    :20067 _ops_before). (2) both hooks present: main seam :20376 inside
    `if _ops_ready_for_wrap_from_gate_obj(gate_obj)`, before the
    competitive-advantage injection at :20411, sets ops_ready_for_wrap=False +
    finalize_ready=False; mirror :19292 fires when the follow-up attempts
    finalize, before the follow-up CA proposal at :19326, persists w/
    _finalize_flag_field("ops", False) and returns. Answer handler :16796
    persists first, router skipped (continue_chat override), receipt LEADS
    (:20449). (3) schemas: intake_consultant.py "origin" x4 = 2 properties +
    2 required + 2 prompt lines. (4) fences: COMMONALITY_SURVIVES==("most",
    "many"), ADDITION_VERBS six-word tuple, stem dedup via caller-passed
    resolver (unique OR ambiguous => dropped); my own grep for MAX_/_CAP/[:N]/
    max_candidates in the module: NONE (the only length fences are per-label
    shape: >60 chars or >6 tokens). (5) STREAM_DISCOVERY_ASK_TEMPLATE is the
    single constant; live emitted ask contains none of consider/add/expand/
    could you also/would you (checked by eye on artifact section A line 1).
    (6) reader: 16 cases incl. bare 'yes' w/ two candidates => unclear/unclear
    (never guesses WHICH), 'The others no' => no, single-candidate bare yes =>
    yes. (7) TIER CALL HONEST: the diff touches intake_consult.py (ops
    wrap-up path), intake_consultant.py schemas, one new module, test scripts;
    no engine/, no workbook builder, no golden; neighbor-check was the right
    tier. VS DECLARED-vs-ACTUAL matches the 14:31 TURN PLAN (files loaded ==
    files touched; canary skipped as declared; R31/R32 --only; both live
    clones ran); the one addition (origin scrub in the carry helper) is a
    guard on the same changed path, declared in RESULT, red-proofed x3
    (scrub / real stamp survives / no-latch stamp scrubbed) - not a mixed
    bundle. Floor re-run by me on the committed code: 2/2 clear.
  TRIAGE of VS's WATCH items (Nick reads; nothing built):
    W1 utilization proposed-then-agreed on a late row: the util probe artifact
      shows the row is null-until-asked and the app RE-ASKS utilization when
      the client answers only the price (0.6 was NOT stored in the probe);
      runs 1-2 storing 0.6 came from a scripted responder that never
      countered a bundled proposal. Pre-existing class for EVERY row (CW-017c
      first-capture rule), not introduced by discovery. Verdict: not a
      discovery defect; the general question "does a non-countering reply to
      a bundled proposal count as agreement?" is a needs-ruling design item
      for Nick, surfaced here, NOT queued as a fix.
    W2 stem resolver drops shared-word labels as ambiguous ("...sales" vs
      "Plant and nursery sale"): conservative by design, silence is free,
      latched w/ reason - WONT-FIX (no wrong number, no false claim).
    W3 ops GPT sometimes asks one more question before declaring
      finalize-ready so the seam is reached a turn later: WONT-FIX (ordering
      preserved, nothing lost).
    NEW (mini, cosmetic-but-truthful, WONT-FIX under the triage law but Nick
      should SEE it before the Cowork run): the judge returned noun-phrase
      labels ("Bulk mulch and soil delivery fees") and the template joins them
      after "also", so the live ask reads "a lot of garden centers also Bulk
      mulch and soil delivery fees or Event and workshop fees" - grammatically
      broken and mid-sentence capitalised, though the client understood it and
      no number/claim is wrong. If Nick wants it fixed it is a copy decision
      (verb-phrase labels via the judge schema, or "also offer <A>, <B>" in the
      template) - his call, not auto-built. The cascade's follow-on "how many
      Bulk mulch and soil delivery fees can you handle?" is the pre-existing
      cascade phrasing with product_name and is unchanged by this build.
  DECLARED-vs-ACTUAL (mini): matches my 15:13 TURN PLAN - neighbor-check tier,
    loaded exactly the HANDOFF task, the 8315341 diff for the three app files,
    the four artifacts + redproof script; re-ran R31,R32 --only myself (2/2);
    canary skipped; no other legs.
TASK:
  For Nick (plain English): the stream-discovery build audited GREEN. Drive
  the TWO confirming Cowork runs per docs/STREAM_DISCOVERY_SPEC.md:
    (a) an operating garden centre that never mentions a common stream
        (e.g. omits bulk delivery / workshops) -> expect ONE "Before we wrap up
        operations: a lot of garden centres also ..." question at the end of
        ops, say yes to one -> the app appends the line, asks its capacity /
        price / utilization, competitive advantage once, milestone once, wrap
        clean to market; the finished ops JSON carries the row w/ origin
        discovery_confirmed;
    (b) a thin single-line niche (or pre-revenue) -> NO such question, ops
        wraps exactly as today.
  Discovery is DONE only when both runs prove out. Anything new the runs
  surface comes back here as a finding for triage, never auto-fixed. Open
  decision for Nick (not blocking): W1 above - whether a bundled
  proposal + non-countering reply should ever count as agreement (all rows,
  pre-existing), and the cosmetic label grammar in the ask.
