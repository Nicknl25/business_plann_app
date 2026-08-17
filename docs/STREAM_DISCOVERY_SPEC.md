# Proactive Stream Discovery — APPROVED design spec (Nick 2026-08-15, build authorized)

Status: **APPROVED by Nick 2026-08-15 with ONE correction — NO HARDCODED
CAP (see Q3): the commonality band IS the gate; the number surfaced is a
judgment, never a constant.** The five open questions are resolved below
with code citations. Blast-radius when built: the insertion point is the
shared ops wrap-up path (`intake_consult.py` gate cascade), so the build
turn is **NEIGHBOR-CHECK** tier under the verification law (neighbors:
competitive-advantage proposal, milestone question, ops-finalize
carry-forward, `_ops_ready_for_wrap_from_gate_obj`) — no engine math, no
canary, no full prove.

## The mandate (Nick's fence, unchanged)

Surface revenue streams the client's business type USUALLY has but the
client didn't mention, so real revenue is not left out of the plan.
DISCOVERY not upsell; EXISTENCE not addition; only the streams
genuinely common for THIS business type (band-judged, never a count); ask ONCE and believe the answer;
a yes lands as a real LOB through the confidence gate.

---

## Q1 — WHERE the category knowledge comes from (resolved)

**Finding first: the app holds NO data about stream composition.** Every
NAICS-keyed store is financial ratios, counts, or wages —
`post_intake_industry_baseline_lookup` (ratios; `scripts/load_industry_baseline_lookup.py:45-76`),
`post_intake_cohort_bands` / `industry_metrics_raw` (cogs %, margins, DSO…; `post_intake_solver/cohort_band_resolver.py:113+`),
`cbp_2022_raw` (establishment/employment counts; `intake_consult.py:4547-4599`),
`naics_master` (codes, titles, business-type labels; `data_pull/naics_master_list.py:60-76`),
EDGAR/SOI/BLS/SBA (statement lines, wages, loans). A grep for
`revenue_stream` / `product_mix` / "product line" hits only the
post-intake restructure designer's `new_lines` (`post_intake_restructure/designer.py:195-228`)
— which is the ADDITION class the mandate forbids, cited here as the
contrast, not the precedent.

**Therefore the source is a GPT CATEGORY JUDGMENT in the proven
judge-from-held-data pattern**, exactly as the app already does for
per-line COGS on uncovered NAICS (`financials_consultant.py:578-720`
`fit_cogs_percent_from_evidence`, called from `intake_consult.py:1400-1450`),
for essentials (`intake_coherence/gpt_essentials_judgment.py`) and for
demand (`intake_coherence/gpt_demand_judgment.py`). The knowledge is the
model's category sense; **the grounding is everything around it**:

1. **Keyed by held facts, never free-floating**: the judge receives
   `business_type` (client-selected from `naics_master.business_types`,
   `api_handlers/business_types.py:75`), `business_naics_6` + NAICS title
   (`ops_json["business_naics_6"]` via `business_type_naics.py:14-41`),
   `business_stage`, geography, and — critically — **the client's own
   line list and business description** (`lob_models[].products[]`,
   `business_description_summary`), which the demand judge's compact
   already carries (`post_intake_amalgamated/mirror.py:255-264, 403-441`).
   Note: NAICS is NOT in today's compact for B2C drafts — the discovery
   judge must add it explicitly.
2. **Python decides evidence, not the model** (the demand judge's rule,
   `demand_evidence_level` :45-68): `stream_discovery_evidence_level(ops_json)`
   is THIN — meaning **no GPT call at all, no ask, zero spend** — when
   business_type is missing, when NAICS did not resolve, when the
   business is pre-revenue (see Q4), or when the client's own line list
   is empty. Silence is free; the generic checklist is the disease.
3. **The judge may only choose LABELS.** Its tool schema returns
   `candidates[]` of `{label, commonality}` (no fixed count) where `commonality ∈
   {"most","many","some"}` and `label` is a short client-plain noun
   phrase. It never returns a number, a price, a volume, or a sentence.
   The one GPT call per draft cannot fabricate revenue because it has no
   channel to.
4. **The validator is the fence, not the prompt** (`validate_demand_response`
   :267-334 pattern): drop `commonality == "some"` (only genuinely common
   streams survive — this is the "genuinely common, not a checklist"
   rule made mechanical); drop any label that stem-resolves to an
   existing line via `_resolve_ops_product_line` (`intake_consult.py:6787-6837`,
   bidirectional stem match on product/unit/lob tokens, refuses on tie);
   drop labels containing addition verbs (add / expand / consider / start
   / launch / new) — a lint that makes the upsell shape unrepresentable
   even before the template does; NO count cap — the band is the gate (Q3).
   Empty after railing ⇒
   `{"asked": false, "reason": "no_common_candidates"}`.
5. **The client is the authority.** The judge produces a QUESTION, never
   a fact; nothing enters the model until the client says yes, and even
   then every number comes from the client (Q5).

**Answer to open question 2 (knowledge ceiling)**: the cohort/CBP data is
NOT fed to the discovery judge — it carries nothing about streams and
would be false grounding. Inputs are exactly: business type, NAICS +
title, stage, geography, the client's own lines and description.

**Why not a static streams-per-type table**: the type list is open-ended
(DB-backed, `naics_master`), and a hand-maintained table is the A-110
root cause (hand-maintained allowed-fields list) all over again.

## Q2 — HOW it asks without over-proposing (resolved)

The ask is **deterministic template text**; GPT never composes it. Only
the labels are interpolated:

> "Before we wrap up operations: a lot of <business type>s also offer
> <label A>, <label B> or <label C> - is any of that part of your
> business today? (If so I'll include it as a revenue line.) If not,
> just say so and we'll move on."

- **F4 (Nick, 2026-08-15): the client is told WHY they are asked** - a
  yes ADDS A REVENUE LINE to their plan - in ONE clause, so they answer
  knowingly. No back-and-forth, no lecture: one question, context
  included, move on.
- **Template verb "also offer"** so the noun-phrase labels read
  naturally ("coffee roasters also offer retail coffee bags ..."; the
  earlier "coffee roasters also <noun phrase>" read verb-less - the
  label-grammar WATCH item is closed by the template, not by the labels).
- "part of your business TODAY" is the existence frame; "have you
  considered adding" is unrepresentable because no model output reaches
  the sentence except a noun phrase that already passed the
  addition-verb lint.
- **The ONE clarify (F4, see Q5)** is a second template constant of the
  same shape - "Just so I record it right: is <label(s)> part of your
  business today? A yes means I'll include it as a revenue line in your
  plan; if not, just say no and we'll move on." - only the still-open
  labels interpolate; it renders at most once per draft.
- Exactly ONE ask per draft, covering all surviving candidates in one
  sentence, holding the turn the established way (`finalize_ready =
  False` + return, `intake_consult.py:20148, 20161`).
- Verification shape (mini): grep the emitted ask against a forbidden
  phrase list (consider / add / expand / could you also / would you) —
  must find nothing on every draft; the template lives in one constant.

## Q3b — Validator fixes after confirming run #1 (Nick 2026-08-15)

Cormorant Coffee Roasters: judge fired (rich, 8 labels), validator
dropped all 8. Ruled fixes, validator-only:
- **F1** dedup requires a DISTINGUISHING match — a shared token that is
  not the business-type/category noun, or >=2 shared tokens; one shared
  category noun ("coffee") is not a duplicate. SHIPPED (VS turn 1): the
  dedup lives inside discovery (`discovery_dedup_reason`), the
  corrections resolver is untouched; category nouns = business_type +
  NAICS-title stems (+ the LOB name's category word); a candidate whose
  distinguishing tokens are what the client already described (the
  confirmed description / unit descriptions) is dropped as
  `mentioned_by_client` — the primary ("wholesale coffee beans") and
  the mentioned ("online coffee bean sales") stay deduped that way.
- **F2** the number-lint stops fabricated FINANCIAL numbers only; a size
  qualifier ("12 oz") is stripped from the label, never a drop.
- **F3 PROPOSAL CAP OF 4** — a UX/cognitive-load limit on the QUESTION,
  not a business heuristic (a presentation constant): the band-gate may
  surface any number; the ASK proposes at most 4 — all `most` first,
  then `many`; <=4 survivors -> all; one ask; the client may still
  volunteer more (never capped). Latch stores `survivors` and
  `proposed`.

## Q3 — "Genuinely common for THIS business" (resolved)

Three mechanisms, all in Python:
1. **Commonality floor**: only `most` / `many` survive; `some` is dropped.
   The judge is told the enum meanings ("most" = the majority of
   businesses of this type do it; "many" = a substantial minority; "some"
   = occasionally) — and it does not get to argue, the validator drops.
2. **Specificity from the client's own lines**: because the judge sees
   what the client already does, a garden centre that already listed
   design gets delivery/maintenance candidates, not design; dedup is
   enforced again in Python by the stem resolver so a paraphrase of an
   existing line never reaches the client (the ack-contradiction class in
   question form).
3. **NO HARDCODED CAP — the band IS the gate (Nick's correction, ruled
   2026-08-15).** No "at most 3", no "2 unless ≤2 lines". The judge rates
   each candidate's commonality for THIS business; every candidate that
   clears the genuine-commonality bar (`most` / `many`) is surfaced, in
   ONE ask; if none clear it, nothing is asked. A garden centre may
   genuinely have several adjacent streams; a niche consultancy may have
   zero — the band-gate scales to the business, a constant does not.
   Same doctrine as no-NAICS-hardcoding and verdicts-from-judgment-not-
   constants: we do not ship heuristics. The template lists all
   survivors ("also <A>, <B> or <C>") — one turn, one ask, band-gated
   survivors.

## Q4 — WHERE it fires — RE-RULED 2026-08-15: MOVE TO THE PRE-CAPTURE SEAM

**Nick's seam ruling (2026-08-15, after confirming run #1):** research
established the ops flow is DESCRIBE-ALL-LINES-THEN-CAPTURE-LINE-BY-LINE
(prompt: the restatement is a hard barrier naming every line before any
driver; "one product at a time" after; Kestrelbrook msgs 2/3/8 and
Cormorant 2/3/8 confirm it empirically). So a clean "all lines named,
nothing captured" seam exists at **`intake_consult.py:16794`** — the end
of the `restatement_confirmed_this_turn` block, where `ops_json` already
holds the locked `business_type`, the fresh `business_naics_6` (:16774),
and `lob_models` with every product NAMED and all five drivers null.
All four judge GATING inputs (type, NAICS, stage, >=1 named line) are
present there; geography + description summary are non-gating and
empty at that point — the judge proposes on type + NAICS title + stage
+ the client's line names. RULED: MOVE the ask to :16794 so stated AND
discovered lines flow through capture together, in order, once — no
backtrack, no append-during-wrap. SEQUENCE: (1) F1/F2/F3 validator fix
lands + mini audit + Cormorant re-run at the CURRENT seam (validator
verified alone); (2) THEN the seam move as a SEPARATE neighbor-check
turn (neighbors: business-type lock, NAICS attach,
persist_ops_from_restatement, the first capture question) + re-run
(seam verified alone). Never confound the two in one re-run.

The original end-of-ops analysis follows for the record:

### (superseded) END OF OPS, exact seam

**Confirmed end-of-ops**, and the code has exactly one right seam:
`intake_consult.py:20116-20118` — the moment `_ops_ready_for_wrap_from_gate_obj(gate_obj)`
returns True (every product passed `_product_complete`, `:11595-11613`:
unit, cadence, price, capacity, utilization, contract periods) and
BEFORE the competitive-advantage proposal at `:20128-20148`. The client
has fully described their business; nothing is built yet.

- Why not the confidence gate: at the gate only the first description
  exists — asking "do you also do X?" there confuses the split question
  with the discovery question and invites over-proposing.
- Why not the financials wall: a discovered line needs the full ops
  capture; discovering after ops closes re-opens ops — the off-path
  A-113 class the guided-flow law forbids. Discover while the door is
  open.
- **Two code paths, both must carry the hook**: the main gate cascade
  (`:20116` → insert before `:20128`) and the follow-up mirror
  (`:19080`). Missing one silently skips discovery on that path.
- **Latch-persistence hazard (found in research)**: `consultant_finalize`
  returns a strict `additionalProperties:false` object and
  `ops_json = final_obj` at `:19188` / `:20494` **wholesale replaces the
  blob** — a `stream_discovery` latch written at the ask would be erased
  at finalize unless carried forward the way `competitive_advantage`
  is rescued (`:19161-19167`, `:20365-20371`) and `business_naics_6` is
  re-attached (`:19176`, `:20416`). The build must do the same for
  `stream_discovery`, and the product-row `origin` field (Q5) must be
  added to BOTH strict schemas (`intake_consultant.py:94-117` finalize,
  `:505-531` turn) or finalize strips it.
- **Operating vs pre-revenue (open question 4)**: fires only for
  `operating` / `early-stage`; a pre-revenue business has no "today" to
  ask about and the question drifts to "will you also…" = upsell. Out of
  scope v1; the evidence-level rule enforces it (thin ⇒ no ask).
- **Re-runs (open question 5)**: the `asked: true` latch holds for the
  life of the draft; even if the business type is later corrected, v1
  does not re-ask (logged as `re-ask_suppressed_after_type_change`).
  Nothing in the guided flow revisits ops after wrap, so this is a
  belt-and-braces data check, not a UX path.
- Cost: one extra ops turn on drafts that get an ask; ≤1 GPT call per
  draft; zero on thin.

## Q5 — HOW a yes lands as a real LOB (resolved: through the gate, zero new write paths — with one honesty guard)

Research confirmed the landing machinery already exists:
- New product rows arrive by **wholesale `lob_models` replacement**
  through the consultant patch (`_apply_model_ops_patch`,
  `intake_consult.py:928-990`, `:964`); the ops prompt requires the model
  to carry all known products forward (`intake_consultant.py:424`).
- The gate cascade **iterates every product every turn**: a new row with
  null drivers blocks wrap-up and is asked capacity
  (`_final_obj_missing_capacity` :19986-19992) → utilization
  (`_first_product_missing_utilization` :20070-20084, names the product)
  → contract periods (`:20099`); price + unit are enforced by
  `_product_complete` and the prompt's finalize rules. **A discovered
  row is asked its five fields automatically, by the same code that
  asks every other row.**

The flow after the ask — **RE-RULED 2026-08-17 (Nick, Option A: CONVERGE
ONTO THE SHARED READER; the per-candidate reader below is DELETED)**.
Corvid Press (e3af1f24): "Digital printing is already part of our
commercial print line ... not a separate thing" is TRUE under the
existence proposition the per-candidate door asked, so ACCEPT was the
right verdict for the wrong question -> a phantom own-LOB line with a
false "is its own line" receipt; "drop that line" had no door at all and
the carry-forward re-attached the row from `answer == "yes"` every turn
until the boundary killed the run. The question was the defect. Now:
1. **The reply is read by the SHARED reader, `consultant_chat_turn`** -
   the one reader every ops-window reply already flows through. On the
   answer turn (the ask or its ONE clarify was literally the last
   assistant message; `intake_consult._open_stream_discovery_window`
   decides that and nothing else) it receives the full conversation, the
   latch (in `operating_model_json.stream_discovery`) and a controller
   note (`gpt_stream_discovery.stream_discovery_controller_note`) that
   says in plain terms: these labels were just proposed as POSSIBLE
   revenue lines; a genuine yes = a new product row (label as its own
   line, drivers null); "already inside my X line" = add nothing, keep it
   inside X; decline = nothing; unclear = nothing. Its `lob_models`
   snapshot is authoritative; it also reports what it did per label in
   `patch.stream_discovery_outcomes` (added | merged_into <line> |
   declined | unclear). Its prompt now carries the discovery section and
   the removal rule (an explicit client retraction of ANY line = omit the
   row from the snapshot on that turn - the ONE exception to "carry
   forward, do not drop"; the parent law).
2. **Python does bookkeeping only, from the STATE**
   (`gpt_stream_discovery.record_stream_discovery_outcomes`, after the
   patch lands): a NEW row the shared reading added for a label gets
   `origin: discovery_confirmed` stamped (provenance is ours) and the
   latch records `added` (+ `row_product_name`); a `merged_into` report
   records `merged_into:<the client's line>`; `unclear` on the first
   round holds the label for the ONE clarify (unchanged template);
   everything else records `declined`. A model that SAYS added but wrote
   no row is not believed (`answer_reason:
   model_reported_added_but_wrote_no_row`, recorded declined). The
   receipt is composed from what landed and LEADS the reply: "Noted -
   <row> is its own line; a few quick numbers for it next." / "Noted -
   <label> stays inside <line>, not a separate line." / "Understood -
   none of those, we'll move on." Then the cascade asks the added row's
   numbers like any row. **No number is ever estimated for a discovered
   stream.**
3. **On no** - `declined`, never re-asked, never proposed, never modelled.
4. **On unclear - ONE clarify** (template unchanged, `action:
   confirm_clarify`, latch `clarify_asked/clarify_labels/first_read`);
   the clarify reply is read by the same shared reader; still unclear =>
   `answer: unclear`, `answer_reason: unclear_after_clarify`, no further
   ask ever.
4b. **Removal ("drop that line") - honored, never resurrected.** The
   shared reader omits the row; `carry_stream_discovery` on an ordinary
   ops turn NEVER re-appends (the shared snapshot is the model);
   `note_stream_discovery_removals` records `answer: removed`
   (+ `removed_from`) and the receipt says "Noted - <row> is dropped as a
   separate line." At the two finalize seams `carry_stream_discovery(...,
   restore_dropped=True)` carries a discovery row ONLY from the shared
   model's own before-row and ONLY when that row carries client-given
   drivers - never minted from the latch, never a null-driver row; the
   latch (outside every GPT schema) is re-attached across the wholesale
   replace as the auditable record. **The wrap gate evaluates the same
   discovery row set that gets persisted**
   (`align_gate_rows_with_persisted`): a persisted null-driver discovery
   row is forced into the gate snapshot (so wrap cannot fire past it) and
   a discovery row the persisted model lacks is removed from it (so a
   re-derivation cannot resurrect it) - the gate and the persisted state
   can never disagree; the phantom-line-at-the-boundary class is dead by
   construction. Latch vocabulary: `added | merged_into:<line> |
   declined | unclear | removed` (drafts latched before 2026-08-17 carry
   `yes|no`; `yes` is read as `added`, never written again).
   Proof: `Test Files/_discovery_reader_convergence_redproof.py`
   (offline), `_live_discovery_corvid_clone.py` (A merged / B removed
   through finalize, PRE red -> POST green), `_live_discovery_ninefathom_
   answer_clone.py` (the genuine-yes case still works, cascade captures).
5. Per-line COGS proposes for the discovered row at the cogs stage like
   any row (it is an ordinary product row); collapse/separation/
   corrections all work unchanged.

## Storage / provenance (INSERT-once, auditable)

`operating_model_json.stream_discovery` (carried forward across finalize):

```json
{"asked": true, "asked_turn_index": 41, "business_type": "garden centre",
 "naics_6": "444240",
 "candidates": [{"label": "garden design services", "commonality": "most", "answer": "yes"},
                {"label": "delivery service", "commonality": "many", "answer": "no"}],
 "dropped": [{"label": "landscape installation", "reason": "matches_existing_line"}],
 "version": 1}
```
THIN or no survivors ⇒ `{"asked": false, "reason": "thin" | "no_common_candidates"}`
— the decision not to ask is itself auditable. Product rows from a yes
carry `origin: "discovery_confirmed"` (schemas updated in both places).

## Artifact verification shape (mini, when built — neighbor-check tier)

1. Ask fires at most once per draft, at the `:20116` seam (and mirror),
   text == the template constant listing exactly the band-gated survivors
   (no count cap anywhere in code); forbidden-phrase grep finds nothing.
2. A candidate matching an existing line (stemmed) is never asked.
3. A declined/unclear stream never reappears (ask, proposals, model).
4. A confirmed stream is a full product row: five fields client-stated,
   COGS proposed at the cogs stage, `origin: "discovery_confirmed"`
   survives finalize (assert on `operating_model_json` AFTER `:20494`).
5. Thin business (no type / pre-revenue / no lines) ⇒ no ask, reason stored.
6. No revenue number for a discovered stream exists that isn't derivable
   from the client's answers.
7. Neighbors: competitive-advantage proposal still fires once after the
   ask resolves; milestone question unchanged; single-line drafts with a
   thin judgment are byte-identical to today (floor legs R31/R32).

## Decisions requested from Nick (the spec is not self-ratifying)

RULED 2026-08-15: (1) architecture APPROVED as designed, with the
no-hardcoded-cap correction above; (2) "unclear ⇒ not confirmed, no
re-ask" YES — existence needs a yes, we never INFER a stream from an
ambiguous answer; (3) one extra turn on drafts that get an ask YES (zero
cost where nothing is genuinely common). BUILD authorized at
NEIGHBOR-CHECK tier → mini audit (finalize latch-carry + both hooks) →
TWO confirming Cowork runs: (a) a business with genuinely-common adjacent
streams the client did not mention — propose → yes → the cascade
captures the new line's five fields → wrap CLEAN (first-class check: the
append-during-wrap-up-and-re-enter-capture sequence); (b) a thin
single-line niche business — discovery asks NOTHING, draft byte-identical
to no-discovery. Triage law applies to anything new. Discovery is DONE
when (a) proves propose→yes→capture→wrap-clean and (b) proves silence.
