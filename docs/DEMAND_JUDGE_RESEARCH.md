# THE DEMAND JUDGE — research (NO BUILD; Nick rules before design)

Nick's assignment (2026-08-10): demand is the common dependency under price /
marketing / volume. Constraints: the client is NEVER asked about elasticity; no
hardcoded elasticity constant (ruled a heretic in CW-022); GPT judges a
business-SPECIFIC demand response from data the app already has (the margin-band
pattern); the judgment ripples through the Recalc as a first-class driver. The
load-bearing question: is the evidence rich enough for an HONEST judgment?

**Answer up front: YES for conversational drafts — proven by running the
dormant machinery live on the real Fetch & Fluff draft — and the dormant
machinery is the right shape to revive, not replace. The fleet-wide dormancy
since 7/22 is a one-line NameError swallowed silently, not a design failure.**

---

## 1. Why the demand machinery has been empty fleet-wide (the autopsy)

- The every-turn refresh (`_refresh_marketing_model`, intake_consult.py ~11873)
  references `estimate_marketing_baseline_from_context` at its call site — but
  that name is **never bound in the main handler's scope**. The estimator
  imports were refactored into `_financials_baseline_estimators()` (commit
  ba7b9cb, 2026-04-02) which binds them only inside
  `_build_financials_stage_message` and `_financials_stage_default_patch`. The
  main handler's closure was missed.
- Every call therefore raises `NameError` — and the enclosing
  `except Exception: marketing_model_json = dict(marketing_model_json or {})`
  swallows it **silently, every turn, every draft**. The model stays `{}`
  forever. (A fail-loud violation of exactly the class the recovery design
  removed elsewhere.)
- Secondary kills on the bypass/canary path (relevant to harness drafts only):
  `consumer_type` arrives as `"b2c"` but every branch expects
  `"consumer"|"mixed"|"b2b"` — `"b2c"` matches nothing and even the fallback
  branches skip; and bypass-seeded `financials_year1_json` carries no
  `company_revenue_total_year1`, which the estimator requires.
- Real conversational drafts (F&F, Sparrow) carry `"consumer"`, rich
  selections, and y1 revenue — for them the ONLY kill is the NameError.

## 2. Data inventory (what the app actually holds)

**Loaded and real (verified by row count):**
- **ACS census 2022**: 33,774 ZCTAs × 2 tables — education, household
  structure, income, age/gender columns. Consumed via the client's own segment
  selections (`market_json.selections[].acs_codes`), weighted and
  geography-normalized (ZIP → county → state) into `segment_basis_counts`.
- **CBP 2022**: 92,927 rows — B2B firm counts by NAICS × geography + size/age
  signals.

**Per draft (conversational):**
- `market_json`: consumer_type, selections (segments + ACS codes),
  gender_age_intent (age bands), income_intent (income bands), confidence,
  marketing_plan_summary.
- `ops_json`: business type + NAICS, unit price, capacity/utilization/cadence,
  geographic coverage, sales modality, competitive advantage.
- `financials/year1`: required revenue + required units (the demand
  denominator).
- **Already-judged demand-adjacent values in bounds** (the walk consumes them
  today): `price_multiplier_max` = "the highest price this line's real
  customers demonstrably pay" (dollar-absolute); `volume_multiplier_max` =
  believable volume ceiling; new-line market caps.
- **The client's own volunteered demand truth**: the CW-022 #4 price clarifier
  answer ("do you expect your current customers to stay?") — lived knowledge,
  never an exam.

**The dormant machinery's outputs when alive** (see §3): reachable_market
(reasoned, narrowed), capture_rate_year1, expected_units/customers_year1,
marketing_intensity, baseline_marketing_percent,
`demand_supports_required_units` (a boolean demand verdict!), full rationale.

## 3. Proof the evidence supports an honest judgment

`_compute_marketing_model_json` + the real GPT estimator, run OFFLINE against
the real F&F draft, produced (verbatim highlights):

- Reachable market **~3,500 dog-owning households**, narrowed from the ~540k
  ACS ceiling with the narrowing path SHOWN (named neighborhoods → dog
  ownership ~30-40% → income/convenience fit → one groomer's radius), labeled
  "planning only, not a literal TAM".
- **~140 active households supporting 1,456 units** through repeat-visit
  arithmetic (10-12 grooms/client/year) — units vs reach vs required units.
- `demand_supports_required_units: true`; marketing_intensity "medium";
  baseline 8% with channel-level reasoning tied to the business's actual
  stage, modality, and capacity.

That is precisely the "reasoned judgment with a basis" shape — not a fabricated
"you'll lose 14.3%". The evidence (census-grounded reach + client-chosen
segments + price point + capacity + required units) is RICH ENOUGH for banded,
reasoned demand judgments on conversational US drafts.

**Honesty limits (must be designed in, not papered over):**
- Reachable-market numbers are planning-level framings — the judge must keep
  saying so.
- The judgment can honestly support a DIRECTIONAL/BANDED demand response
  ("holds most", "meaningful loss", "unsupported") with a stated basis — never
  a numeric elasticity point.
- US-only quantified basis (the machinery already declares
  `us_only_quantified_market` otherwise): non-US or thin drafts must carry an
  explicit lower `evidence_level`, widening bands or withholding the verdict —
  a thin-evidence judgment that says it's thin is honest; one that doesn't is
  the CW-022 disease.
- Bypass-seeded drafts (no selections) are thin by construction.

## 4. Mechanism — GPT as the demand judge (the margin-band pattern)

**Evidence in** (all existing): the revived demand model (reach, capture,
expected units, intensity), price vs the bounds' judged market ceiling,
business type/NAICS, capacity/utilization, required units, plus any volunteered
clarifier answer.

**Judgment out** — a DEMAND RESPONSE stamp, authored once at F-core, same
fence discipline as the band (viability-blind: judges the business type's
demand character, never the plan's needs), identity-keyed and re-judged on
correction like every judged artifact:

```
demand_response: {
  evidence_level: "rich" | "thin",
  price_response:  { verdict: holds_most | meaningful_loss | unsupported,
                     retained_fraction_band: [lo, hi], basis: "..." },
  marketing_response: { verdict: insensitive | coupled | dependent,
                        demand_at_reduced_spend_band: [lo, hi], basis: "..." },
  volume_headroom: { supported_units_max, basis: "..." },
}
```

Bands, not points; the walk consumes the **conservative edge**; thin evidence
widens bands or withholds verdicts. The client's volunteered clarifier answer
**overrides** the judge (client truth > judged estimate — the judge fills
silence, never argues).

**Ripple through the Recalc** (rule 4 — first-class driver, not a bolt-on):
- Pricing round: projected revenue = new price × units × retained-fraction
  (conservative edge) — the "raise price, hold customers" fantasy dies; the
  accepted option lands the retained units on the ops truth and the existing
  Recalc recomputes everything downstream (already proven for price/volume
  landings).
- Volume round: effective ceiling = min(ops vmax, demand
  volume_headroom.supported_units_max) — "do more" only where demand supports.
- Marketing move REVIVES (Nick queued it on exactly this): a cut is priced
  WITH its judged demand consequence — never pure savings again.
- The wall/verdict layer gains `demand_supports_required_units` as an honest
  disclosure input (it already exists in the model).

Plug-in points are all existing seams: `_pricing_round`/`_volume_round`
projection math, the costs-round marketing move, option-landing in
`apply_router_patch`, and the F-core stamp block in `_ensure_margin_band`'s
neighborhood. No new persistence shape needed beyond the stamp.

## 5. Dormant machinery: revive, don't replace

It is the right shape (evidence → reasoned judgment → first-class values) and
already computes half of what the demand judge needs, including the
`demand_supports_required_units` verdict. Revival is small and is the first
step of any approved design:
1. Bind the estimator in the main handler (the one-line NameError).
2. Handle the `"b2c"`/`"b2p"` consumer_type vocabulary (normalize to the
   machinery's vocabulary at one seam).
3. Kill the silent `except` per fail-loud doctrine (a dead demand model must
   be visible, never `{}` forever).
4. THEN author the demand-response judgment on top of the revived model.

## 6. Open decisions for Nick (rule before build)

1. Revive the machinery (the three fixes above) — approve as the first build?
2. The demand-response stamp shape (§4) — approve the banded/directional form
   and the conservative-edge consumption rule?
3. Clarifier precedence — confirm: client's volunteered answer overrides the
   judge, and the judge never triggers new client questions?
4. Thin-evidence doctrine — widen bands vs withhold verdict (and therefore
   keep the affected lever un-revived for that draft)?
5. Where the judge authors: ride the F-core gate entry with band/growth (one
   more judgment at the same seam) — approve?
