# Proactive Stream Discovery — RESOLVED design spec (research complete, NOTHING BUILT)

Status: **refined spec for Nick's review, 2026-08-15.** The five open
questions are resolved below with code citations. Build starts only on
Nick's approval. Blast-radius when built: the insertion point is the
shared ops wrap-up path (`intake_consult.py` gate cascade), so the build
turn is **NEIGHBOR-CHECK** tier under the verification law (neighbors:
competitive-advantage proposal, milestone question, ops-finalize
carry-forward, `_ops_ready_for_wrap_from_gate_obj`) — no engine math, no
canary, no full prove.

## The mandate (Nick's fence, unchanged)

Surface revenue streams the client's business type USUALLY has but the
client didn't mention, so real revenue is not left out of the plan.
DISCOVERY not upsell; EXISTENCE not addition; only the 2–3 streams
genuinely common for THIS business type; ask ONCE and believe the answer;
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
   `candidates[≤3]` of `{label, commonality}` where `commonality ∈
   {"most","many","some"}` and `label` is a short client-plain noun
   phrase. It never returns a number, a price, a volume, or a sentence.
   The one GPT call per draft cannot fabricate revenue because it has no
   channel to.
4. **The validator is the fence, not the prompt** (`validate_demand_response`
   :267-334 pattern): drop `commonality == "some"` (only genuinely common
   streams survive — this is the "2–3 genuinely common, not a checklist"
   rule made mechanical); drop any label that stem-resolves to an
   existing line via `_resolve_ops_product_line` (`intake_consult.py:6787-6837`,
   bidirectional stem match on product/unit/lob tokens, refuses on tie);
   drop labels containing addition verbs (add / expand / consider / start
   / launch / new) — a lint that makes the upsell shape unrepresentable
   even before the template does; cap at 2 (Q3). Empty after railing ⇒
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

> "Before we wrap up operations: a lot of <business type>s also
> <label A> or <label B>. Is either of those part of your business
> today? If not, just say so and we'll move on."

- "part of your business TODAY" is the existence frame; "have you
  considered adding" is unrepresentable because no model output reaches
  the sentence except a noun phrase that already passed the
  addition-verb lint.
- Exactly ONE ask per draft, covering all surviving candidates in one
  sentence, holding the turn the established way (`finalize_ready =
  False` + return, `intake_consult.py:20148, 20161`).
- Verification shape (mini): grep the emitted ask against a forbidden
  phrase list (consider / add / expand / could you also / would you) —
  must find nothing on every draft; the template lives in one constant.

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
3. **Cap = 2** (resolves open question 3). The template reads as one
   natural sentence with two; three reads as a checklist. A third
   candidate is kept only if all three are `most` AND the client has ≤2
   lines (a thin single-line business is where discovery earns the most).

## Q4 — WHERE it fires (resolved: END OF OPS, confirmed, exact seam)

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

The flow after the ask:
1. Client answers in their own words. The reply is classified per
   candidate as yes / no / unclear by the same deterministic
   yes-no-per-item reading the app uses elsewhere (a "yes to design, no
   to delivery" splits cleanly).
2. **On yes — Python appends the row deterministically** (receipt law:
   the app's words match the app's state). Do NOT rely on the GPT patch
   to have added it: append `{product_name: <label>, all drivers null,
   origin: "discovery_confirmed"}` under the best-matching existing LOB
   (stem resolver) or a new LOB named for the label. The receipt says
   exactly that ("Noted — <label> is its own line; a few quick numbers
   for it next."). Then the cascade asks its capacity/utilization/price
   like any line. **No number is ever estimated for a discovered stream**;
   if the client can't supply its numbers, the line does not model (same
   rule as any line, CW-017(c) derivability unchanged).
3. **On no** — stored, never re-asked, never proposed, never modelled.
4. **On unclear** — treated as NOT confirmed (existence needs a yes;
   silence is not a yes), stored `answer: "unclear"`, never re-asked. The
   client can still name the line any time in ops through the normal
   path — that is the guided flow working, not a re-probe.
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
   text == the template constant; forbidden-phrase grep finds nothing.
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

1. Approve the resolved answers above (source = fenced GPT category
   judgment; end-of-ops seam; cap 2; operating/early-stage only; Python
   appends the row on yes).
2. Confirm "unclear ⇒ not confirmed, no re-ask" is the intended UX.
3. Approve the one-extra-turn cost on drafts that get an ask.
On approval: build turn (VS, neighbor-check tier) → mini audit at the
shape above → one confirming Cowork run on a thin single-line business
(must be byte-identical) and one on a multi-line business that gets an
ask.
