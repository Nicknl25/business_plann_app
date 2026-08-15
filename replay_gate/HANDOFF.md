STATUS: awaiting-VS
TURN: 0/16
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
  AGENT: none
  VERDICT: progress
  ERROR-SIGNATURE: none
  EVIDENCE: (superseded — new instruction seeded)
  SUMMARY: The previous turn's RESULT was superseded by a new
  instruction; it remains in git history.
