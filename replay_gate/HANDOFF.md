STATUS: awaiting-mini
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
