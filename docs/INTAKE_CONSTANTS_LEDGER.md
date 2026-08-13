# Intake-Path Constants Ledger

**Purpose**: the intake-path counterpart of `VERDICT_CONSTANTS_LEDGER.md`,
produced by the CW-016 fragility-class sweep (2026-08-07). Two intake
absolutes fired in two consecutive runs (the marketing 0.2%-of-revenue floor,
CW-015; the capital-lease flat $1 term-end tolerance, CW-016) — the same
disease the verdict-path workstream killed in 2026-07. This ledger lists
every absolute numeric threshold, tolerance, floor, ceiling, or plausibility
bound in the intake path with its ruling and reason.

**Status: RULED AND BUILT.** All four section-1 conversions were approved by
Nick (2026-08-07) and are now shipped, each with red→green at the scales
that matter. Everything in sections 2-3 is ruled KEEP with its written
reason.

**The governing principle**: an intake threshold must be a **true
invariant**, a **scale-relative ratio**, a **derived bound** (computed from
rounding units, speech granularity, or float arithmetic — the mathematically
maximum legitimate residue, not a guess), or a **declared policy/model
parameter**. Absolute dollar amounts and absolute count cutoffs are never
plausibility bounds.

---

## 1. CONVERTED — approved 2026-08-07, all shipped with red→green

### 1a. Accounting-equation tolerance — `max($1, scale × 1e-8)` (was flat $1; fatal check)

**THE APPROVED FRAMING (Nick, verbatim requirement)**: *$1 balance-rounding
invariant preserved; the scale term is a float-noise allowance active only
at extreme magnitude, NOT a business-relative loosening of the equation.*
A == L + E is a TRUE INVARIANT and $1 remains the exact tolerance at every
realistic scale — the relative term exceeds the floor only above ~$100M
single-quarter magnitude, where float64 summation residue on a *balanced*
book can itself cross a dollar. Verified: tolerance is exactly $1.00 at
$2M, $50M, and $100M quarters; a $3 real imbalance at $2M still fails; a
$50 imbalance at $500M still fails; only the $500M balanced-book $3
float residue (previously fatal) now passes. Implemented as the shared
`accounting_equation_tolerance()` in fail_fast.py, used by the fatal
equation check, the stored-totals companion, the convergence-runtime gate,
and the workbook OK/FAIL status row (kept consistent with the checks).

**Mechanism** (for the record): A − (L+E) is computed from ~15 float
components summed per side. Float64 residue scales with magnitude — the
codebase observed **1.7e-9 relative residue at $50M quarters** and fixed the
identical disease at the revenue-formula seam
(`REVENUE_DRIVER_FORMULA_TOLERANCE`: `max(0.015, |ref| * 1e-8)`). At
~$500M-quarter scale the residue crosses $1 and the fatal check fired on
arithmetic noise — dormant at today's client scale, structurally guaranteed
at large scale.

### 1b. Triplet-landing count ceiling — CONVERTED (was `f <= 2000` absolute)

`intake_consult.py` no-touch and anchor-missing landing sites. A count
candidate is now any integral figure strictly below the dollar target it
would explain (`f < target`) — the 2% three-way coherence is the real
fingerprint and is already scale-free. Verified: a "5,000 deliveries a year
at $180 = $900,000" correction, invisible before, lands capacity 5000/12
with dollar narration.

### 1c. Dollar-figure floor — CONVERTED (was `f >= 1000` absolute)

Dollar-shaped = figure ≥ the product's own stored unit price (a stream
total cannot be below one unit) — derived, per-product, no constant to
tune. Verified: a $800/year micro-stream at $4/unit, invisible before,
lands. The coverage-backstop floors (5851/5855 family) stay as-is per the
watch-list — their failure mode is a missing nag, never a wrong number.

### 1d. Completion-tripwire and standalone-checker `maintenance_rate` — CONVERTED (was hardcoded 0.05)

Both the completion tripwire (`intake_consult.py`) and
`scripts/check_draft_buildable.py` now call the SAME Python derivation
production uses (`_derive_maintenance_capex_percent_from_naics`, NAICS
cascade with conservative default). Verified: Ironbridge's GC NAICS
(236220) derives 0.02 — a real divergence from the old hardcode — and the
draft builds clean with it. Checker-vs-production drift was the CW-014
lesson shape; this closes the seam.

---

## 2. KEEP — deliberate, permanently, with reasons

### 2a. True invariants (zero/one/sign are real boundaries)

| Constant | Sites | Reason |
|---|---|---|
| utilization ∈ (0, 1] clamps | intake_consult 5681, 5759, 5813; finmo_bridge 1388-1392 | a rate above 1 is not a business-relative question |
| ratio clamps [0, 1] (COGS percent, capture rate) | intake_consult 6719, 3867 | same |
| non-negativity floors (marketing ≥ 0, opening ≥ 0, asset_dep ≥ 0, oox ≥ 0) | throughout; schedule.py contract | negative dollars are a sign bug, not a scale question |
| horizon/dep quarters ≥ 1 | schedule.py | degenerate-input contract |
| funding split ∈ (0, 1) after normalization | intake_consult 4648 | share semantics |

### 2b. Scale-relative by construction (dimensionless ratios and shares)

| Constant | Sites | Note |
|---|---|---|
| basis fingerprint 0.15; agreement band [0.87, 1.15]; probe gates 1.15 / 1.5 / 0.6 | 4839-4919 | all ratios of implied/stated |
| stage-amount shares 0.5% annual / 1% monthly | 4993 | shares of the business's own revenue — this IS the CW-015 conversion |
| percent plausibility [0.005, 1.0]; reverse band [0.005, 0.5] | 5021, 5140 | percent semantics, dimensionless |
| divergence ≥ 3x (both directions) | 5056, 5144 | ratio of the two readings |
| derivability tolerances 0.5%; no-change bands 0.1% | 5395-5483, 12768 | relative to the value; 0.5% chosen after 2% let 873,000 pass as 216,000x4 (recorded at 5475) |
| disposition gaps: pre 8%, post 1%, factor 0.5%, reconcile 5% | 5537-5540 | relative revenue gaps; post≤1% added by CW-016 (i2) |
| lever derivability 2%; triplet coherence 2%; stream anchor 5%; stream neighborhood 40% | group E | relative to the client's own figures |
| near-price band 50% of stored price | 5720 | deliberately relative (CW-016 (g)): $4,300 lands on $4,000 agreements, never on $385,000 projects |
| marketing percent clamp [0.025, 0.18] | 3820 | percent-of-revenue |
| maintenance-rate band [0.02, 0.15] | finmo_bridge x3 | ratio band, cohort-grounded (fitted-band doctrine) |
| SBA rate ≤ 50 (percent) | finmo_bridge 1146+ | data-cleaning bound on a percent |

### 2c. Derived bounds (computed, not guessed)

| Constant | Sites | Derivation |
|---|---|---|
| `term_end_residual_tolerance(q) = unit/2 × q + unit` | schedule.py 35-50 | max accumulated whole-dollar rounding drift; converted THIS sweep (CW-016) |
| lease per-row tolerance = 1 (checks #3/#4/#5, FINMO cross-check) | schedule.py | PROVEN exact: each is a single-row comparison of ints rounded from the same float chain; the integer difference is bounded by 1.5 → max 1. Only check #9 accumulates across quarters, and it now uses the derived form |
| `max(0.015, |ref| × 1e-8)` revenue-formula tolerance | finmo_bridge 1882-1899 | the exemplar hybrid — absolute floor at float-rounding-mode noise + relative term for enterprise scale; 1a proposes copying it |
| $0.01 staleness drifts (price/capacity/periods), $0.01 wage-change marker | 7392-7405, 12327 | money granularity: one cent |
| 0.51 verbatim-figure match bands | 5027, 5047, 6513 | speech granularity: clients state whole numbers; half-unit catches float repr |
| number-word compounding (tens ≥ 20 + unit < 10) | 5096 | English grammar of compound numbers |

### 2d. Unit/calendar facts and format invariants

12 / 52 / 4 period conversions (everywhere; excluded by definition); k=1,000
/ m=1,000,000 shorthand; founder-shorthand ×1000 ("twelve" → $12,000 — a
speech convention the fingerprint check anchors to the client's own words);
percent-points ÷100 ladders (`_coerce_ratio_units`, `_safe_ratio` — the
CW-013 one-ladder-one-seam, and both are MACHINE-source normalizers: cohort
table seeds and GPT-authored bands, where no client words exist to declare a
unit). `_normalize_ratio_like` was the same ladder on a CLIENT statement and
is DELETED (CW-031 round 8): a client saying "COGS is 1% of revenue" stored
100%. Client-stated rates now carry a unit declared by the router and are
converted unconditionally by `_declared_percent_rate`, which refuses rather
than guesses. No threshold may separate 71 from 0.71. ZIP=5 digits;
NAICS=6 digits (+5,4,3,2 prefix cascade); 365-day stage inference; 0-12
months-until-hire proration; 90 days-in-quarter (convention shared with the
engine's day-count basis — flag only if the engine's basis ever changes).

### 2e. Declared policy / model parameters (the number IS the policy)

| Constant | Sites | Class |
|---|---|---|
| marketing-intensity model coefficients (~30 values: stage/basis/modality/scope adders, price-band nudges, reachable-market ratios) | 3725-3883 | a deterministic fallback MODEL — its coefficients are the model, reviewed as a model, not thresholds on client values; post-CW-015 guards prevent its output overwriting client statements |
| funding-split menu {0.70, 0.50, 0.30} | 4611-4690 | product menu, mirrored by the post-intake reader |
| capacity utilization ceiling 0.85 / post-expansion 0.70 | finmo_bridge 1097-1098 | named policy `utilization_first_structural_capacity_capex_v2` |
| tax_rate_forecast floor 0.21 | finmo_bridge 3466 | statutory (TCJA) doctrinal floor |
| capex useful life 5 years; lease depreciation 20 quarters | finmo_bridge 1095; schedule.py 31 | contract-versioned schedule policy |
| stub scale = stated_annual/4 quarterly anchor | finmo_bridge 3141 | the basis-capture stub ruling (eff7521) |

### 2f. Infrastructure budgets and UX shape (not business thresholds)

OpenAI timeout/attempt/deadline constants (473, 7623-7677); 12-message
window; 200-event ring; receipt line cap 4; uncovered-figure list cap 2
("avoid interrogation"); 20-char substantive-message floor; ≥2 sentence
marks; 6-char milestone floor. These gate the pipe and the conversation
shape, not client numbers.

---

## 3. Parked open member — logged firmly, with its resume trigger

| Item | State | Trigger to resume |
|---|---|---|
| **Lease check #9 under-payment blind spot** (`post_intake_capital_lease/schedule.py`, precondition `total_principal >= intake_seed`): a schedule whose principal stream NEVER covers the seed skips the term-end check entirely, and no other validator owns the un-closed-by-underpayment class — a lease that structurally never pays off sails through finalize today. Pre-existing, not introduced by the CW-016 tolerance work. | Open, un-built by decision (Nick, 2026-08-07: "don't fix now, but don't let it evaporate") | An under-paying lease schedule appearing in a real run — then it gets its own validator (e.g. horizon-end obligation must be on a trajectory to zero, tolerance from the same derived rounding math) |

## 4. Watch-list — kept, revisit on a real business harmed

| Item | Risk shape |
|---|---|
| percent-shaped floor 0.5 (`_percent_shaped_figures`) | a genuine "0.3" percent answer is invisible to percent-vs-dollar detection; no observed case |
| stage-amount monthly-share ≥ 1% "ordinariness" | a very-low-cost line on a huge business could suppress a real month-vs-year ask; the annual-share arm still guards |
| coverage-figure floors (2.0, sub-$1000 non-integral, ≤2000 count-shaped in the uncovered-figures nag) | worst case is a missing coverage nag, never a wrong number |

---

*Produced by the CW-016 sweep. Companion: `VERDICT_CONSTANTS_LEDGER.md`
(2026-07). Inventory method: exhaustive constant enumeration of
intake_consult.py, basis_gate.py, finmo_bridge.py (intake seams),
post_intake_capital_lease/schedule.py, capture_receipt.py, field_basis.py,
plus the fatal accounting-equation twins the display row led to.*
