# Proactive Stream Discovery — design spec (CW-033 Tier 3, RESEARCH ONLY)

Status: **spec for Nick's review — nothing is built.** The build waits on
A-113 staying closed AND Nick approving this note.

## The mandate (Nick's framing, non-negotiable, restated as the spec's fence)

The app surfaces revenue streams the client's business type USUALLY has but
didn't mention, so real revenue is not left out of the plan.

1. **DISCOVERY, not upsell.** Capture streams the client ALREADY HAS but
   didn't mention ("a lot of garden centres also do design work — do you?").
   NEVER propose streams to ADD ("have you considered adding design?") —
   that fabricates revenue.
2. **Existence, not addition.** The ask is always about what the business
   does *today*. The client's actual business is the authority.
3. **Only the 2–3 streams genuinely common for that specific business
   type** — category knowledge, never a generic checklist.
4. **Ask ONCE per likely stream, believe the answer, no re-probing.**
5. **A discovered stream lands as a real LOB through the confidence gate**
   into the per-line machinery.

## Where the category knowledge comes from

Three sources already in the app, in order of authority:

- **The client's own words.** The first "what does the business do?" answer
  and the whole ops transcript. Discovery candidates must be checked
  against the lines already captured — a stream the client already named is
  not a discovery, and asking about it would be the ack-contradiction class
  in question form. The stemmed line resolver landed for A-113
  (`_resolve_ops_product_line`'s token matching) is the right dedup
  instrument: "landscaping install" must recognize "installation services".
- **The confirmed business type** (client-selected from the existing
  `/api/business-types` list) plus NAICS. This is the *key* the category
  knowledge is looked up by, not the knowledge itself.
- **A GPT category judgment, in the demand-judge pattern**
  (`intake_coherence/gpt_demand_judgment.py` is the template): GPT judges
  from data the app already holds (business type, the client's own line
  list, geography), the judgment returns through a forced tool call, and
  every fence is enforced in the **validator, not the prompt**:
  - at most 3 candidate streams, each a short client-plain label;
  - each candidate must carry a `commonality` band (e.g. "most", "many",
    "some") — anti-false-precision, same doctrine as `_MIN_BAND_WIDTH`;
  - candidates that resolve (stemmed) to an existing line are DROPPED in
    Python before anyone is asked;
  - a THIN result (unfamiliar/unlisted business type, or the model cannot
    name streams with genuine confidence) means **no ask at all**. Silence
    is free; a generic checklist is the disease. This mirrors the
    demand judge's Python-computed `evidence_level` — the model never gets
    to claim its own confidence.

  Why GPT and not a static table: the business-type list is open-ended and
  the demand judge already proved the judge-from-held-data pattern live.
  A hand-maintained streams-per-type table would be the hand-maintained
  allowed-fields list all over again (the A-110 root cause).

## Where in the flow it fires

**Recommended: END OF OPS, exactly once** — after every client-described
line is fully captured (unit, cadence, capacity, price, utilization
agreed) and before the ops wrap-up / competitive-advantage proposal.

Why not the confidence gate itself: at the gate the app has only the
client's first description — asking "do you also do X?" before the client's
own lines are even settled invites over-proposing and confuses the split
question with the discovery question. At end-of-ops the app knows exactly
what was captured, so the dedup is real and the ask can be specific.

Why not the financials wall: a discovered line needs the full ops capture
(unit/cadence/capacity/price/utilization); discovering it after ops closes
would re-open ops — the exact post-stage-correction class A-113 just
closed. Discover while the door is open.

Cadence: ONE turn, at most one ask, covering all (≤3) surviving
candidates in a single question. The ask template is **deterministic
text** with only the stream labels filled in — GPT never freestyles the
question, so "have you considered adding" is unrepresentable:

> "Before we wrap up operations: a lot of <business type>s also
> <stream A> or <stream B>. Is either of those part of your business
> today? If not, say so and we'll move on."

## How a yes lands (through the confidence gate, per the mandate)

A "yes, we also do design work" is treated exactly like the client having
named the line in their first description, arriving at the line-split
confidence gate (`intake_consultant.py` "THE LINE-SPLIT CONFIDENCE GATE"):

1. The consultant proposes the new line inside a restatement
   (`confident_multi` shape: "I'll set that up as its own line because it
   earns differently"), with the standing bidirectional invitation
   (group/split further).
2. The normal per-product capture runs for the discovered line — unit,
   cadence, capacity, price, utilization — all from the client's own
   answers. **No number is ever estimated for a discovered stream**; if
   the client cannot supply its numbers, the line does not model (same
   rule as any line).
3. Per-line COGS is proposed at the financials cogs stage like any other
   line; collapse/separation/corrections all work because the discovered
   stream is an ordinary product row. **Zero new write paths** — that is
   the point of landing through the gate.

A "no" (or an ignore) is believed, stored, and never re-asked.

## Storage / provenance (INSERT-once, auditable)

`operating_model_json.stream_discovery`:

```json
{
  "asked": true,
  "asked_turn_index": 41,
  "business_type": "garden centre",
  "candidates": [
    {"label": "garden design services", "answer": "yes"},
    {"label": "delivery service", "answer": "no"}
  ],
  "version": 1
}
```

- `asked: true` is the once-only latch (the no-re-probe fence is a data
  check, not a prompt hope).
- A product row created from a discovery carries
  `origin: "discovery_confirmed"` so every downstream auditor can see the
  stream was client-confirmed existence, never app-invented.
- A THIN judgment stores `{"asked": false, "reason": "thin"}` — the
  decision not to ask is itself auditable.

## Artifact verification shape (for mini, when built)

1. The ask fires at most once per draft, at end-of-ops, and its text is
   the deterministic template (existence wording; grep for the forbidden
   "consider adding" class must find nothing).
2. A candidate matching an existing line (stemmed) is never asked.
3. A declined stream never re-appears — in the ask, in proposals, or in
   the model.
4. A confirmed stream becomes a full product row through the standard
   capture: all five driver fields client-stated, per-line COGS proposed
   at the cogs stage, and `origin: "discovery_confirmed"` stamped.
5. A business whose type yields a THIN judgment gets NO ask, and the
   stored reason says so.
6. No revenue number for a discovered stream exists that is not derivable
   from the client's own answers (the CW-017(c) derivability rule applies
   unchanged).

## Open questions for Nick (the spec is not self-ratifying)

1. **Surface**: end-of-ops (recommended above) vs. inside the confidence
   gate's restatement. End-of-ops costs one extra turn; the gate risks
   asking before the client's own lines are settled.
2. **Knowledge source ceiling**: may the category judgment use the NAICS
   cohort/CBP data the demand model already holds, or only the model's own
   category knowledge keyed by business type? (The demand judge precedent
   says held-data-plus-judgment is fine; the fence is the validator.)
3. **Candidate cap**: 2 or 3? The mandate says "2-3"; the template reads
   best with 2.
4. **Operating vs pre-revenue**: discovery for a pre-revenue business is
   necessarily "will you also...", which drifts toward addition/upsell.
   Recommendation: discovery fires only for `operating` (and possibly
   `early-stage`) businesses; pre-revenue is out of scope v1.
5. **Re-runs**: if a draft re-enters ops after discovery was asked, the
   latch holds (never re-ask). Confirm that is the intended UX even when
   the business type itself was corrected after the ask.
