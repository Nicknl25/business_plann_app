# WRITING PHASE — refinement against Nick's six requirements (2026-08-18)

Status: RESEARCH ONLY. NOTHING BUILT. Extends `docs/WRITING_PHASE_RESEARCH.md`
(the base doc; area/W-item numbers below refer to it). Lead-with-answer format.

---

## 1. SECTION-BY-SECTION MODULARITY

**Answer: one Python module per plan section, all sharing one contract
(`brief → generate → verify → render`); the document is composed from a
`plan_manifest` (ordered list of enabled section ids); cross-references go
through a `PlanContext` registry so an omitted section degrades to "not
present" instead of a broken reference; the Executive Summary is generated
LAST from the other sections' verified outputs.**

- **Package** `python/writing_phase/`: `contract.py` (the section ABC),
  `sections/s02_business.py … s10_appendix.py`, `manifest.py`, `compose.py`,
  `render_docx.py`, `charts.py`, `verify.py`, `brief/` (fact assemblers).
- **Section contract** (every module implements exactly this):
  `id`, `title`, `depends_on: [fact-brief ids]`, `charts: [series ids]`,
  `brief(ctx) -> SectionBrief` (typed facts with ids + provenance; deterministic),
  `generate(brief) -> SectionDraft` (GPT rework, §3 rules),
  `verify(draft, brief) -> VerifiedSection | Failure`,
  `render(section, doc, ctx)` (docx paragraphs/tables/figures),
  `exports() -> {key: value}` (numbers/phrases other sections may cite —
  e.g. §8 exports `y1_revenue`, `break_even_quarter`; §3 exports
  `market_size_sentence`).
- **Composition** (`compose.py`): read `plan_manifest` (config: default order
  + `enabled` flag per section, per-request override on the
  `writing_phase_requests` row), run enabled sections in dependency order,
  collect `exports()` into `PlanContext.exports`, THEN run the Exec Summary
  (`s01_exec_summary`, `depends_on = ["*"]`), then title/TOC/appendix.
- **Turning a section off without breaking cross-references:** references
  are never literal — a section asks `ctx.ref("s08", "break_even_quarter")`;
  if the section is disabled the registry returns `Absent`, and the
  generation brief for the citing section carries the fact as
  "not available in this edition" → the writer omits the sentence (the
  verifier rejects any sentence citing an `Absent` id). Section numbering,
  TOC, figure numbers, and "see Section n" phrases are resolved at
  compose-time from the manifest, never authored by GPT.
- **Editable/swappable:** because each module owns its own brief, prompt,
  and verifier, Nick can replace `s06_marketing.py` or add `s11_risks.py`
  by registering it in the manifest; no other module changes. Per-section
  regeneration (`--sections s03,s08`) re-runs only those modules and
  re-composes.
- **W-impact:** W4 grows the contract/manifest/compose skeleton (with a
  stub section proving the pattern); W5 lands the sections one module at a
  time (each its own turn is possible).

## 2. CHARTS EMBEDDED IN THE WORD DOC

**Answer: yes, matplotlib is the right tool — render PNGs from ONE shared
series layer (`writing_phase/charts.py: series_from(finmo_json)`) that the
workbook Dashboard also uses for its `Reference` rows, so doc and workbook
plot identical numbers; each section module declares the charts it embeds
and places them via `render()`.**

- **Why not alternatives:** python-docx cannot embed live Excel charts (no
  OLE/chart part support); Word-native charts need raw OOXML chart parts +
  embedded workbook (fragile, unsupported); Excel-COM screenshotting is
  slow and non-deterministic. matplotlib (`Agg` backend, headless; not
  installed today — new dependency alongside python-docx) gives
  print-quality PNG/SVG at 200–300 dpi. numpy is already installed.
- **Single source of truth:** `series_from(finmo_json)` yields named series
  (`revenue_total_q[20]`, `revenue_by_line_q` (recomputed from model_input
  drivers, same formula as the Revenue Drivers sheet), `gm_pct_q`,
  `ebitda_margin_q`, `ending_cash_q`, `debt_balance_q`, `be_revenue_q`,
  `planned_revenue_q`, `cost_structure_y1`, `headcount_q`, `market_size`
  (from marketing_model_json/ACS/CBP)). The workbook Dashboard maps each
  series id → the FINMO/schedule rows it references; a tie-out test asserts
  the persisted `finmo_json` values behind those rows equal the series the
  doc plotted (values, not bytes — the workbook is formulas that recalc to
  the same numbers).
- **Which sections get which charts** (each a `Figure n` with caption and
  an in-text reference):
  §3 Market — market-size funnel (reachable market → expected customers),
  optional industry-growth trend; §4 Org — headcount ramp; §5 Products —
  revenue mix by line (multi-line only); §7 Capital — sources & uses,
  debt balance vs cash; §8 Financial — revenue projection (stacked by
  line), GM%/EBITDA% with the industry band shaded, ending cash with the
  trough marked, **break-even chart** (BE revenue vs planned; CVP for Q1),
  cost structure; §9 Disclosures — optional stated-vs-modeled bar per
  disclosed lever.
- **Mechanism:** section `render()` calls `ctx.figure(series_id, style)` →
  charts.py renders to bytes (fixed rcParams, brand palette, no metadata →
  deterministic PNG for goldens) → `doc.add_picture(io.BytesIO)` +
  caption paragraph; the figure counter lives in PlanContext (manifest-
  order numbering). Style guide (fonts, palette, axis units, source line
  under each chart "Source: model run <id>") in one place.
- **W-impact:** W2 gains `charts.py` series layer (workbook Dashboard
  consumes it); W5 embeds.

## 3. GPT'S OWN KNOWLEDGE vs THE DATABASE — THE BOUNDARY

**Answer: split every sentence into two lanes. LANE A (grounded) — any
number, statistic, comparative, or claim about THIS business, its market,
its people, its plan: must cite a brief fact id and survive the verbatim-
figure check. LANE B (expertise) — framing, industry practice, how a lender
reads it, strategic interpretation, standard terminology: allowed and
encouraged, but must be (i) general (no specific figures, dates, named
studies, or named competitors unless in the brief), (ii) tagged as
expertise, and (iii) hedged as context, never presented as data about this
client. The verifier enforces the split mechanically: untagged factual
sentences fail; tagged expertise sentences containing numbers fail.**

**What GPT may contribute (Lane B, encouraged):**
- Professional framing and structure of the argument (why this section
  matters to a lender; what the reader should take away).
- Industry-standard context stated generically: how the business type
  operates, typical cost drivers and seasonality *as concepts*, common
  risks and mitigations, regulatory/licensing categories that apply to the
  business type, standard KPIs a lender uses (DSCR, GM, break-even).
- Strategic interpretation OF the grounded facts: "a 24-hour turnaround
  positions the shop against larger printers that batch work" is allowed
  because the fact (turnaround, competitive_advantage) is cited and the
  interpretation is labeled as positioning insight.
- Terminology, transitions, plain-language explanation of model mechanics
  ("break-even is the revenue at which contribution covers fixed costs").
- Recommendations phrased as considerations, not as facts about the client.

**What must stay strictly grounded (Lane A):**
- Every number, %, $, count, date, growth rate, market size, wage, rate.
- Every statement about this client (what they sell, where, who, prices,
  capacity, staff, history, goal, funding).
- Every market/industry statistic (must trace to a warehouse table +
  vintage in the brief; GPT's memory of "the US printing market is $X" is
  forbidden — if the brief lacks it, the plan says nothing numeric).
- Named competitors, named lenders, named regulations/statutes, named
  studies — only if in the brief.
- Anything about the model's overrides (§9) — from the registry only.

**How generation enforces it:** the brief hands GPT the fact list plus a
Lane-B "expertise licence" per section (what kinds of context are welcome
here). GPT must emit sentences with markers: `[F12]` cites, `[E]` marks an
expertise sentence, `[F12|E]` an interpretation of a fact. Prompt rules:
no unmarked sentence; `[E]` sentences may not contain digits, currency,
percentages, proper nouns not in the brief, or the words "in <state/city>",
"this business" + a predicate of fact; `[E]` sentences use generic
subjects ("print shops of this kind", "lenders typically"); no superlatives
about the client ("the best", "leading") unless cited.

**How the verifier distinguishes framing from fabricated fact:**
1. Marker completeness — every sentence carries `[F..]`, `[E]`, or both.
2. Lane-A check — every numeric/currency/percent token in a `[F]` sentence
   appears in the cited facts (existing `_MONEY_RE` survival check,
   `intake_coherence/section.py:2639`, extended to counts/percents/dates).
3. Lane-B check — `[E]` sentences: zero numeric tokens; no proper nouns
   outside the brief's allow-list (business name, city, state, NAICS
   title, product names); no client-predicate patterns ("<business> has/
   employs/earns/serves…"); banned-vocabulary lint.
4. Interpretation check — `[F|E]` sentences must contain the cited fact's
   value or a permitted paraphrase and may add only evaluative language.
5. Density guard — per section, Lane-A ≥ N% of factual sentences and
   Lane-B ≤ M% (configurable) so the document stays a plan, not an essay.
6. Failure → one regeneration with violations listed → fail-loud (no plan
   ships on substituted judgment). The machine copy keeps the markers; the
   rendered doc strips them (optionally footnotes cited data sources).
This is a mechanical split, so Cowork/mini can audit "framing vs fact" per
sentence without reading intent.

**W-impact:** W5's prompt/verifier design; no new data.

## 4. PREMIUM QUALITY BAR

**Answer: premium = (1) argument, not readout — each section makes a
claim, supports it with cited facts, and tells the reader what it means;
(2) expert context (Lane B) woven into every section; (3) numbers that
reconcile everywhere (one engine, one number, cross-references resolved by
the composer); (4) honest disclosure as a feature (§9 + inline notes) —
nothing on the market does this; (5) design: real typography, tables,
captioned figures, running headers, TOC, appendix; (6) zero template
smell (no boilerplate sentences, no repeated phrasing across sections, no
field-name jargon).** No page limit; length follows the business.

What generation must include to hit it:
- Per-section "reader's question" in the brief (what a lender wants
  answered here) and a required "so-what" closing paragraph.
- Section-specific Lane-B licences (e.g. §3 may explain industry structure
  and seasonality; §7 may explain how DSCR is read; §8 may explain
  assumptions in lender language).
- Style constants: one serif/sans pairing, 11pt body, heading hierarchy,
  numbered figures/tables with sources, consistent rounding ($ thousands
  in prose, exact in tables), callout boxes for headline numbers, a
  one-page "Plan at a glance" after the Exec Summary.
- Cross-section consistency pass (composer): every number that appears in
  ≥2 sections is the same export value; a repeated-phrase detector across
  sections; a reading-level check (plain business English).
- Editorial pass: a second GPT call per section acting as a lender-side
  reviewer ("what is unsupported, unclear, or template-like?") whose
  findings feed one revision under the same verifier (bounded cost: 2
  calls/section + Exec Summary).
- Optional appendices that read premium: methodology & data sources with
  vintages, intake fact sheet, full 20-quarter statements in landscape.
- **W-impact:** W5 (editorial pass, style constants); W4 brief adds
  reader's-question + licence fields.

## 5. BREAK-EVEN — COMPUTED IN THE MODEL, RENDERED BELOW THE P&L WITH A CHART

**Answer: confirmed. Compute = post-process in
`finmo_bridge.build_python_finmo_json` → `finmo_json["break_even"]`
(spot-check, not engine math). Render = a "Break-Even Analysis" block on
the FINMO sheet directly beneath the Income Statement, live formulas
referencing the P&L and Model Inputs rows, plus a native break-even chart
anchored beside it; the persisted block ties out to the formulas on the
Checks sheet.**

- **Compute/persist path (unchanged from Area 4c):** `finmo_bridge.py:657-
  941` post-process; block per quarter `{fixed_costs{payroll, lease,
  depreciation, interest}, variable_ratio{cogs, marketing, r_and_d,
  g_and_a}, cm_ratio, be_revenue, planned_revenue, margin_of_safety,
  per_line[{slot, price, cogs_pct, cm_per_unit, mix_share, be_units}]}` +
  summary `{first_ebitda_positive_quarter, q1, y1, y5, cash_be_revenue}`;
  persists via the existing `UPDATE intake_consult_drafts SET finmo_json`
  (`orchestrator.py:4642`); declare `break_even` optional in
  `FinmoOutputContract` so `DraftWorkbookData.from_contract` keeps it.
- **Workbook placement:** `finmo_sheet.py:186` writes the Income Statement
  block via `_write_statement_rows`; insert a fourth statement
  `"Break-Even Analysis"` immediately after it (before Balance Sheet) with
  rows: Fixed Costs (=Payroll+Lease/Rent+Depreciation+Interest, P&L refs),
  Variable Cost Ratio (=COGS%+Mkt%+R&D%+G&A% from Model Inputs),
  Contribution Margin Ratio (=1−ratio), Break-Even Revenue (=Fixed/CM),
  Planned Revenue (=P&L Revenue), Margin of Safety (=(Rev−BE)/Rev),
  Break-Even Quarter flag (=EBITDA≥0), Cash Break-Even Revenue (adds
  scheduled principal from Debt Schedule), then per-line rows "<line> —
  Break-Even Units" (=BE Revenue×mix/price, Revenue Drivers refs). Rows are
  registered through `ctx.add_finmo_row("Break-Even Analysis", label)` so
  Checks/Audit Source resolve by key, not number.
- **Chart:** openpyxl `LineChart` (BE Revenue vs Planned Revenue, Q1..Q20;
  categories = period header row 5) anchored right of the annual columns
  (col AD) beside the block, plus a Q1 CVP `ScatterChart` (fixed / total
  cost / revenue vs units) — both `Reference` the block's rows → live.
- **Tie-out:** Checks sheet gets "Break-Even Q1 (formula vs persisted)"
  and "Break-Even Quarter" rows against `finmo_json.break_even` written to
  Audit Source (hidden) — same pattern as the P&L tie-outs
  (`checks_sheet.py:833`).
- **R32 consequence (fact, not a blocker):** the R32 golden hashes
  formulas keyed by ROW LABEL (`replay_gate/surface.py:611-631`), so
  inserting the block between P&L and Balance Sheet shifts BS/CF row
  numbers → every BS/CF formula string changes → one R32 re-bless with a
  sheet-wide diff. Appending the block after Cash Flow instead would make
  the diff additive-only. Recommendation: **below the P&L per spec**;
  accept the one re-bless (mini verifies the diff is pure row-shift + new
  rows). Ruling item.
- **W-impact:** W1 unchanged; W2 = Break-Even block on FINMO + chart +
  Checks tie-out (+ Dashboard sheet if still wanted); one planned R32
  re-bless.

## 6. TIERED DELIVERY — ARCHITECTURE SHAPE (no entitlements built)

**Answer: make the request row tier-aware and the runner artifact-driven:
`writing_phase_requests.requested_tier ∈ {standard, premium}` (+ a
`deliverables_json` list derived from tier: standard = docx+pdf; premium =
docx+pdf+workbook); the runner produces every artifact into a per-run
delivery folder and records them in a `writing_phase_artifacts` table
(request_id, kind ∈ {docx, pdf, xlsx, machine_copy}, path, sha256,
tier_min); client-facing delivery is a SEPARATE future consumer of that
table — the internal email fence is not touched.**

- **PDF:** Word COM is available on this host (probed: Word 16.0 via
  pywin32, same mechanism as `assert_workbook_model_status_ok`) → docx →
  PDF via `ExportAsFixedFormat`; deterministic enough for delivery, not for
  byte goldens (golden the docx machine copy instead).
- **Workbook as a paid deliverable:** already produced by post-intake and
  recorded in `workbook_deliveries` (source_path, delivered_path); the
  writing runner just references/copies the authoritative workbook into
  the artifacts table when `premium`. No change to the workbook build or
  its internal email.
- **Fence preserved:** today's `send_workbook_alert` (`workbook_email.py`,
  `EMAIL_ALERTS_ADDRESS` only) stays as-is; the writing runner sends its
  own INTERNAL notice through the same helper or writes to the delivery
  dir only (ruling Q6.4 in the base doc). Client-facing delivery later =
  a new consumer that reads `writing_phase_artifacts` filtered by
  `tier_min ≤ purchased_tier` and hands files over via whatever channel
  #21 rules (portal download, signed link, human send) — it never reuses
  the internal alert path.
- **Entitlement hook (not built):** `requested_tier` is set by whoever
  enqueues (auto-pass default `standard`, operator, or later the payment
  system); `paid_update` requests re-run writing on a re-priced model with
  the same tier attribute. Nothing else in the architecture knows about
  money.
- **W-impact:** W4 request table gains `requested_tier`, `deliverables_
  json`, and the artifacts table; W5 renderer emits pdf; W6 unchanged.

---

## Revised W-sequence (deltas only)

| W | Change |
|---|---|
| W1 | unchanged — `finmo_json["break_even"]` + contract field |
| W2 | Break-Even block **below the P&L on FINMO** + native chart + Checks tie-out; shared `charts.py` series layer; Dashboard sheet consumes the same series; ONE R32 re-bless (sheet-wide row-shift diff) |
| W3 | unchanged — override registry (feeds §9 Lane-A facts) |
| W4 | skeleton = section contract + manifest + compose + PlanContext refs; request table gains `requested_tier`/`deliverables_json`; `writing_phase_artifacts` table; brief adds reader's-question + Lane-B licence |
| W5 | sections as modules (one at a time), Lane-A/Lane-B prompt + verifier, matplotlib figures via section `render()`, editorial pass, docx + Word-COM PDF, style constants; new deps python-docx + matplotlib |
| W6 | unchanged — enable auto-enqueue (tier default `standard`), first Cowork run |

## For ruling
- R1 Manifest-driven modular sections with Exec Summary last and `Absent`-safe references — confirm.
- R2 matplotlib PNGs from the shared series layer (new dependency) — confirm; chart-per-section list above.
- R3 Lane-A/Lane-B boundary + marker-based verifier as specified — confirm, and set the density guard defaults.
- R4 Premium bar incl. the second editorial GPT pass per section (≈2 calls/section) — confirm the cost.
- R5 Break-Even block directly below the P&L on FINMO (one sheet-wide R32 re-bless) vs appended after Cash Flow (additive diff) — pick; chart beside the block — confirm.
- R6 `requested_tier` on the request row + `writing_phase_artifacts` table; internal email fence untouched; PDF via Word COM — confirm.

Nothing built.
