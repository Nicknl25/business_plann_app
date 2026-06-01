# Fix #2 — Headcount Derivation: SPEC (capacity-as-bridge, revenue-driven)

**Status:** SPEC ONLY. No code changes. Nick reviews this doc before any implementation.
Direction is locked: **revenue → required capacity → headcount.** Capacity stays the
bridge; headcount responds to revenue. Builds on the trace in
[fix_2_headcount_derivation_trace.md](fix_2_headcount_derivation_trace.md).

**Scope:** Manager-side deterministic (Python) post-intake logic. Does not touch intake, the
Executive (GPT) layer, or contract-layer code. Every claim is grounded in `file:line`.

---

## 0. One-paragraph summary

Today the system runs `headcount → capacity → revenue-sanity-check`:
`apply_payroll_supported_capacity_to_model_input`
([schedule.py:2525](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2525))
takes the FTE grid, computes `supported_capacity = avg_FTE × productivity`, and **overwrites**
the revenue-authored `Capacity` rows with it. Fix #2 **stops that overwrite**, treats the
revenue-authored `Capacity` as the *required-capacity demand*, and derives supporting FTE by
the inverse: `required_supporting_FTE = required_capacity ÷ productivity`. Capacity is not
eliminated — it becomes the input instead of the output. Revenue is no longer recomputed from
FTE, so there is no loop: **single pass.**

---

## 1. Locked decisions (inputs to this spec)

| # | Decision | Spec treatment |
|---|---|---|
| 1 | Direction: revenue → required capacity → headcount | §3.1 |
| 2 | Core reversal: stop the FTE→capacity overwrite; derive FTE from revenue-authored Capacity | §3.1–3.2 |
| 3 | Binding: capacity-based, `supporting_FTE = required_capacity ÷ productivity` (NOT payroll-%-of-revenue) | §3.2 |
| 4 | Productivity is an adjustable lever, not a hardcode; needs starting value + adjust→recompute path | §3.4 + **OQ-1** |
| 5 | FTE derived by default but overridable, with downstream recompute | §3.5 |
| 6 | OEWS = supporting roles only; key people from intake stay separate/untouched | §3.6 |
| 7 | payroll-%-of-revenue (NAICS cohort): demoted to sanity check, with verified coverage + fallback | §3.7 (**verified**) |
| 8 | Flip doctrine flags; reverse the explicit FTE→capacity doctrine; no half-inverted state | §3.8 |
| 9 | Single-pass; no iteration | §3.9 |

**One premise correction (does not change direction).** Decision 4 cites "the existing tier
bounds at lookup.py:53-56" as a productivity starting value. Verification shows
[lookup.py:52-57](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L52-L57) is
`wage_positioning_multiplier_json` (a **wage** multiplier, not productivity). The actual
productivity bound columns (`capacity_units_per_supporting_fte_min/_max`,
`capacity_productivity_bounds_json`) are in a **DROP COLUMN legacy-removal** list
([lookup.py:336-338](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L336-L338))
with no replacement. **There is no current source for a productivity starting value** —
see §3.4 and **OQ-1**.

---

## 2. Verified mechanics (the spec is built on these)

### 2.1 Revenue is invertible — `Σ(Capacity × Unit Price × Utilization)`

Enforced as a hard contract for every live quarter by `_enforce_revenue_driver_formula_contract`
([finmo_bridge.py:601-641](../../python/client_intake_and_finmo/finmo_bridge.py#L601-L641),
formula string at [finmo_bridge.py:634](../../python/client_intake_and_finmo/finmo_bridge.py#L634)).
Capacity is one factor of a product; given Unit Price and Utilization, capacity demand is the
quantity the revenue plan requires.

### 2.2 The overwrite to remove — `apply_payroll_supported_capacity_to_model_input`

[schedule.py:2525-2642](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2525-L2642).
Today it:
- computes `supported_capacity[q] = avg_FTE[q] × productivity`
  ([schedule.py:2568-2571](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2568-L2571)),
- finds the revenue `Capacity` rows
  ([schedule.py:2574-2577](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2574-L2577)),
- **redistributes** the FTE-derived total across them by each row's existing weight and
  **writes `row["values"]`** ([schedule.py:2597-2610](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2597-L2610)),
  stamping `derived_driver="payroll_supported_capacity"`, `controller_write=False`.

Its mirror validator `_payroll_supported_capacity_model_input_violations`
([schedule.py:2645-2707](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2645-L2707))
asserts `capacity == avg_FTE × productivity` and that every Capacity row carries the
`payroll_supported_capacity` marker. **Both encode FTE→capacity and must reverse together** —
no half-inverted state (Decision 8).

### 2.3 Inverse arithmetic

Today: `supported_capacity = avg_FTE × productivity`. Inverse:
`required_supporting_FTE = required_capacity ÷ productivity`. The repair path **already
computes this inverse** as a corrective nudge
([schedule.py:2944-2961](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2944-L2961):
"payroll_supported_revenue scales linearly with capacity_units_per_supporting_fte when FTE,
unit price, and utilization are unchanged"). Fix #2 promotes this from repair hint to the
primary producer.

### 2.4 revenue.Capacity is intake-anchored (VERIFIED, with a caveat)

The revenue `Capacity` rows are seeded deterministically from intake `operating_model_json`,
not free-guessed:
- `_quarter_capacity_from_ops_product`
  ([finmo_bridge.py:2560-2589](../../python/client_intake_and_finmo/finmo_bridge.py#L2560-L2589))
  reads `units_per_period_capacity`, `units_per_week_capacity × 13`, `units_per_month_capacity × 3`,
  or `concurrent_capacity_units`.
- Seeded into model_input at [finmo_bridge.py:3107-3112](../../python/client_intake_and_finmo/finmo_bridge.py#L3107-L3112),
  per (LOB, product) — the per-product decomposition (Decision: §3.3).
- It is the **authoritative revenue ceiling**: `capacity_driven_annual_revenue =
  capacity × unit_price × periods × upper_bound_utilization`
  ([structural_feasibility_check.py:93-120](../../python/client_intake_and_finmo/structural_feasibility_check.py#L93-L120)),
  ranked first in `authoritative_annual_revenue`
  ([structural_feasibility_check.py:123-162](../../python/client_intake_and_finmo/structural_feasibility_check.py#L123-L162)).
- It is authored at sequence **Step 10** (`prepare_baseline_model_input`, pre_convergence,
  [post_intake_mapping.py:686-708](../../python/client_intake_and_finmo/post_intake_mapping.py#L686-L708)) —
  **before** payroll at Steps 62-67. So the demand exists before headcount derivation reads it.

**Caveat to flag (OQ-3):** if intake captured no capacity fields, Capacity initializes to 0
and `authoritative_annual_revenue` falls back to the operator's Year-1 projection
([structural_feasibility_check.py:153-157](../../python/client_intake_and_finmo/structural_feasibility_check.py#L153-L162)).
In that degraded case the "demand" we derive FTE from is a softer anchor. The spec must define
behavior when required_capacity is 0/absent (§3.3, OQ-3).

### 2.5 NAICS payroll-%-of-revenue coverage (VERIFIED — sanity check is real)

- Table `post_intake_industry_baseline_lookup`; metric `payroll_percent_of_revenue` seeded
  from Census CBP 2022 + IRS SOI, `benchmark_target = CBP.pay_ann*1000 / SOI.business_receipts`
  ([scripts/load_industry_baseline_lookup.py:1167-1278, registry row :2352](../../scripts/load_industry_baseline_lookup.py#L2352)),
  `governs_model_input_lever="expenses::Payroll"`, `fail_if_no_coverage=0`.
- Runtime resolver `post_intake_industry_baseline_for_naics`
  ([post_intake_industry_baseline/lookup.py:492-628](../../python/client_intake_and_finmo/post_intake_industry_baseline/lookup.py#L492-L628)):
  cascade L6 (CBP_SOI, high/med) → L5/L4/L3/L2 (downgraded) → L0 generic default
  (min 0.08 / target 0.20 / max 0.40).
- **Fallback when a NAICS lacks it:** resolver returns `trust_flag="no_coverage"` (no raise,
  since `fail_if_no_coverage=0`); the headcount policy tier bounds then apply —
  `payroll_revenue_sanity_bounds_json` low/med/high/expert in [0.06, 0.80]
  ([lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79)),
  selected by `labor_intensity_class`
  ([headcount_payroll_revenue_sanity_bounds, lookup.py:836-850](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L836-L850)).

**Verdict:** the demoted sanity check has both real cohort data and a defined two-level
fallback. Decision 7 is safe to implement as a *check*, not a driver.

---

## 3. The reversal design

### 3.1 Core inversion (Decisions 1, 2)

Replace `apply_payroll_supported_capacity_to_model_input` (the producer of capacity from FTE)
with a producer of **supporting FTE from capacity**. Concretely, the new step:

1. Reads revenue-authored `Capacity` rows from `model_input.sections.revenue` (the demand) —
   the same rows it currently overwrites
   ([schedule.py:2574-2577](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2574-L2577)),
   but now **read-only**.
2. Aggregates per-quarter required capacity across products (§3.3).
3. Derives `required_supporting_FTE[q] = required_capacity[q] ÷ productivity` (§3.2).
4. **Does not write `Capacity`.** Capacity keeps its intake-anchored values, so revenue is
   unchanged and the `Σ(Capacity × Price × Utilization)` contract still holds with no loop.

The `Capacity` object-control owner flips from `derive/rebuild` to `read_only/preserve` for
the payroll step (currently `derive` at
[post_intake_mapping.py:839-843](../../python/client_intake_and_finmo/post_intake_mapping.py#L839-L843);
note `quarter_grid_generation` already treats it `read_only/preserve` at
[post_intake_mapping.py:909-914](../../python/client_intake_and_finmo/post_intake_mapping.py#L909-L914)).

### 3.2 Binding (Decision 3)

`supporting_FTE[q] = required_capacity[q] ÷ productivity`. Capacity-based, never
payroll-%-of-revenue. The result is a **total supporting-FTE count per quarter**, which then
flows into the payroll grid (§3.6) and payroll dollars (`avg_FTE × wage`, unchanged math at
[schedule.py ~1946-1982](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py)).

### 3.3 Per-product aggregation (Decision / blast radius)

Capacity is authored per (LOB, product) with its own units
([finmo_bridge.py:2475-2484](../../python/client_intake_and_finmo/finmo_bridge.py#L2475-L2484);
per-product `product_rows` carrying capacity/unit_price/utilization in
`_revenue_driver_context_from_model_input`,
[schedule.py:2244-2316](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2244-L2316)).
Required supporting FTE is a **shared pool**, so the spec aggregates required capacity to a
quarter total before dividing by productivity:
`required_supporting_FTE[q] = (Σ_product required_capacity[q,product]) ÷ productivity`.

**Heterogeneous-units risk (OQ-2):** different products may express Capacity in
non-comparable units (e.g. seats vs transactions). A single global productivity scalar over a
raw sum is only valid if capacity units are commensurable, or if productivity is defined
per-product. The spec flags this; default starting position is global productivity over the
summed capacity, with per-product productivity as a documented extension.

### 3.4 Productivity lever — starting value + adjust→recompute (Decision 4)

**Productivity stays `capacity_units_per_supporting_fte`** (the existing field,
[post_intake_mapping.py:2139](../../python/client_intake_and_finmo/post_intake_mapping.py#L2139)),
now the **upstream lever** in headcount's place.

**Starting value — NO current source (OQ-1).** Verified: zero default
([empty stub = 0.0, lookup.py:925](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L925)),
bounds columns dropped as legacy with no replacement
([lookup.py:336-338](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L336-L338)),
no NAICS productivity baseline, and `productivity_assumptions` is a phantom context key
pointing at a non-existent column
([declared post_intake_mapping.py:1856](../../python/client_intake_and_finmo/post_intake_mapping.py#L1856),
no such column in the policy DDL/insert). The spec **cannot** assert a sensible default; it
must create one. Options (Nick's call, OQ-1):
- **(a)** New policy-lookup column `default_capacity_units_per_supporting_fte` (+ optional
  min/max) in `post_intake_headcount_policy_lookup`, seeded with an expert default.
- **(b)** Derive a starting value from the revenue-authored capacity and a key-people-implied
  staffing prior at intake (data-grounded but more work).
- **(c)** Per-NAICS productivity baseline metric (mirrors how wages are OEWS/NAICS-derived) —
  highest fidelity, largest build; no such dataset exists today.

**Adjust→recompute path.** Productivity is an input to §3.1 step 3. Changing it (or revenue /
unit price / utilization, which move required_capacity) re-runs the derivation:
`new required_supporting_FTE → new payroll grid → new payroll dollars → new finmo → re-run
feasibility + sanity check`. Because it is single-pass (§3.9), this is one forward recompute,
not an iteration.

### 3.5 FTE override + downstream recompute (Decision 5)

Headcount is derived **by default** but overridable. Two override surfaces, both
forward-recomputing:
- **Driver override (preferred):** Nick adjusts productivity (§3.4) or the revenue drivers
  (Capacity/Unit Price/Utilization). The derivation re-runs and FTE, payroll, and feasibility
  all move. This keeps the binding intact.
- **Direct FTE override:** Nick sets supporting FTE above/below the derived value. Capacity is
  *not* recomputed from it (the overwrite is gone), so the override creates an explicit
  **coverage delta**: `actual_FTE × productivity` vs `required_capacity`. The existing
  `min_capacity_coverage_ratio` (default 1.0,
  [lookup.py:37](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L37)) becomes
  the guardrail — under-staffing (coverage < ratio) is flagged; over-staffing is allowed but
  shows as slack and is caught by the payroll-%-of-revenue sanity check (§3.7).

The override must be a first-class, stored field so it survives recompute (not a transient).
**OQ-4:** where the override lives (a new `payroll_headcount` field vs a model-input
annotation) and whether a direct FTE override suppresses the derivation entirely for that
quarter or just shifts it.

### 3.6 OEWS = supporting roles only; key people untouched (Decision 6)

The derived count is **supporting FTE only**. The existing split is preserved: GPT/Executive
authors supporting OEWS-title rows; "Python injects key people from intake"
([post_intake_mapping.py:2133](../../python/client_intake_and_finmo/post_intake_mapping.py#L2133)).
The derivation produces a **total supporting-FTE-per-quarter** number; the **title mix**
(which OEWS titles, in what proportion) is business judgment → **deferred to Executive** (§5).
Until the Executive layer exists, a deterministic default mix (e.g. preserve the current
authored grid's proportional split, scaled to the derived total) keeps the payload shape valid
(§3.10). Key-people rows are never touched by the OEWS derivation.

### 3.7 payroll-%-of-revenue demoted to sanity check (Decision 7)

Keep `payroll_revenue_feasibility_violations` / `assert_payroll_revenue_feasibility`
([schedule.py:2855-2961](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2855-L2961))
as a **post-derivation check** on `payroll ÷ revenue` against the NAICS cohort band (§2.5),
falling back to the policy tier bounds. It must **not** feed back into FTE (no payroll-%
driver). On violation: surface a diagnostic (and, under override, a coverage/slack warning) —
do **not** silently re-solve productivity to satisfy it (that would resurrect payroll-% as a
hidden driver). **OQ-5:** is a sanity violation a hard fail or a warning, given headcount is
now capacity-derived and the band is descriptive?

### 3.8 Doctrine flag flips (Decision 8)

In `_DEFAULT_HEADCOUNT_POLICY_ROWS`
([lookup.py:82-88](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L82-L88)):
- `capacity_primary: True → False` (revenue/capacity-demand is primary; FTE responds).
- `use_revenue_as_sanity_not_driver`: revenue stays sanity for *payroll-%*, but capacity-demand
  (revenue-derived) is now the FTE driver — reword/retire to avoid implying FTE is free.
- Re-examine the monotonicity rules (`average_fte_cannot_decline_when_capacity_increases`,
  etc.): under derivation these become *consequences*, not *constraints* — keep as validators
  or drop (OQ-6).

Reverse the explicit FTE→capacity doctrine in the contract context note
([post_intake_mapping.py:2525-2526](../../python/client_intake_and_finmo/post_intake_mapping.py#L2525-L2526):
"payroll FTE is the causal source of supported Capacity"; "Python derives supported Capacity
from payroll FTE and does not validate FTE against a pre-existing capacity demand floor") and
the docstring at [schedule.py:2534](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2534)
("Use payroll FTE as the causal capacity envelope"). New doctrine: **capacity demand is the
causal source of required supporting FTE; FTE is validated against the capacity demand floor.**
No half-inverted state.

### 3.9 Single-pass (Decision 9)

Order: Step 10 authors Capacity (intake) → payroll step reads Capacity, derives supporting FTE,
derives payroll dollars → finmo build → revenue contract holds (Capacity unchanged) →
feasibility + sanity check. Because Capacity is no longer rewritten from FTE, revenue is not
recomputed from FTE — **no fixed-point loop.** The current `recompute_of_step_key` /
`payroll_headcount_changed` rebuild triggers on the Capacity object
([post_intake_mapping.py:797-801, 839-843](../../python/client_intake_and_finmo/post_intake_mapping.py#L797-L801))
are removed for Capacity (it no longer rebuilds from payroll).

### 3.10 Payload-shape preservation (Decision: don't break the schedule)

The `payroll_headcount` payload and `payroll_headcount_grid` shape are preserved so the
contract layer and validators hold (per the trace, validators require the schedule *present and
reconciling*, not *authored*). The derivation must still emit per-title, per-quarter rows
(`q`, `oews_occ_title`, `starting_fte`, `hires`, `ending_fte`, `payroll_tax_benefits_pct`,
[post_intake_mapping.py:2048-2054](../../python/client_intake_and_finmo/post_intake_mapping.py#L2048-L2054))
and `quarter_totals`, so that:
- `assert_payroll_headcount_payload_ready`
  ([schedule.py:2710](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2710)) passes,
- `assert_finmo_payroll_matches_headcount_schedule`
  ([schedule.py:2777](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2777)) reconciles,
- the ~13 `required_context_keys=["payroll_headcount", ...]` steps still receive the payload.

The change is the **producer** of `starting_fte/ending_fte` (now derived from capacity, then
distributed across titles), not the payload schema.

---

## 4. Blast radius

| Consumer | File:line | Today | After Fix #2 |
|---|---|---|---|
| **Capacity producer** `apply_payroll_supported_capacity_to_model_input` | [schedule.py:2525-2642](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2525-L2642) | writes Capacity from FTE | **inverted**: reads Capacity, derives FTE; stops writing Capacity |
| **Mirror validator** `_payroll_supported_capacity_model_input_violations` | [schedule.py:2645-2707](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2645-L2707) | asserts `capacity == FTE×prod` + marker | **inverted**: asserts `FTE == required_capacity ÷ prod`; drop the `payroll_supported_capacity` marker requirement on Capacity rows |
| **Capacity object-control** | [post_intake_mapping.py:839-843](../../python/client_intake_and_finmo/post_intake_mapping.py#L839-L843) | owner=python action=derive | `read_only/preserve` for payroll step; remove `payroll_headcount_changed` rebuild trigger on Capacity |
| **Sequence outputs** Step 62/65 produce `model_input.revenue.Capacity` | [post_intake_mapping.py:797-801](../../python/client_intake_and_finmo/post_intake_mapping.py#L797-L801) | Capacity is a payroll output | Capacity is a payroll **input**; payroll output is the FTE grid only |
| **Payroll dollars** `_build_payroll_headcount_payload_from_contract` | [schedule.py ~1946-1982](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py) | `avg_FTE × wage` from authored FTE | unchanged math; FTE now comes from derivation |
| **expenses::Payroll → finmo** | [post_intake_mapping.py:1325-1334](../../python/client_intake_and_finmo/post_intake_mapping.py#L1325-L1334) | derived schedule → finmo | unchanged |
| **Revenue contract** `Σ(Capacity×Price×Util)` | [finmo_bridge.py:601-641](../../python/client_intake_and_finmo/finmo_bridge.py#L601-L641) | holds | **still holds** (Capacity untouched) — key safety property |
| **Feasibility / sanity** | [schedule.py:2855-2961](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2855-L2961) | post-hoc check | demoted check only; never a driver (§3.7) |
| **Coverage ratio** `min_capacity_coverage_ratio` | [lookup.py:37](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L37) | unused-ish | becomes the FTE-override guardrail (§3.5) |
| **Contract layer (Contract 1 / model input)** | [finmo_bridge.py:680-704](../../python/client_intake_and_finmo/finmo_bridge.py#L680-L704) | validates model_input shape | **no schema change** — Capacity and Payroll fields unchanged; do not touch contract code |
| **Payroll schedule validators** | [schedule.py:2710, 2777](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2710) | require present+reconciling schedule | hold, given §3.10 |
| **Solver / quarter-grid** (~seq 70+) | [post_intake_mapping.py:1388-1508](../../python/client_intake_and_finmo/post_intake_mapping.py#L1388) | read payroll_headcount | unchanged inputs; Capacity now read_only throughout |
| **Doctrine flags + context notes** | [lookup.py:82-88](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L82-L88), [mapping.py:2525-2526](../../python/client_intake_and_finmo/post_intake_mapping.py#L2525-L2526) | capacity-primary, FTE-causal | flipped (§3.8) |

---

## 5. Python-derived vs deferred-to-Executive

| Concern | Owner | Notes |
|---|---|---|
| Required capacity per product/quarter | **Python (intake-anchored)** | from revenue-authored Capacity (§2.4) |
| Aggregate required capacity → total | **Python** | §3.3 |
| `supporting_FTE = required_capacity ÷ productivity` | **Python (the Fix #2 core)** | §3.2 |
| Payroll dollars (`avg_FTE × wage`), OEWS wage resolution | **Python** | unchanged |
| Feasibility + payroll-% sanity check | **Python** | §3.7 |
| **Productivity value (business judgment)** | **Executive (deferred)** | Python needs a starting default now — OQ-1 |
| **Title mix / which OEWS titles** | **Executive (deferred)** | Python uses a deterministic default split until then (§3.6, §3.10) |
| Key people | **Intake (untouched)** | §3.6 |

---

## 6. Implementation plan (ordered) + test strategy

**Phase 0 — Productivity starting value (blocks everything; resolve OQ-1 first).**
Add the chosen starting-value source (recommend option (a): a defaulted policy column). Seed
+ lookup + validation that productivity is positive before derivation.
*Test:* policy lookup returns a positive default; empty-stub no longer 0.0.

**Phase 1 — Invert the producer.** Rewrite `apply_payroll_supported_capacity_to_model_input`
into "derive supporting FTE from required capacity" (§3.1-3.3): read Capacity, aggregate,
divide by productivity, emit the FTE total; stop writing Capacity.
*Test:* given fixed revenue-authored Capacity + productivity, derived FTE = capacity ÷ prod
per quarter; Capacity rows are byte-identical before/after (no overwrite); revenue
`Σ(Capacity×Price×Util)` contract still passes.

**Phase 2 — Invert the validator.** Rewrite `_payroll_supported_capacity_model_input_violations`
to assert `FTE == required_capacity ÷ productivity` (within tolerance) and drop the Capacity
`payroll_supported_capacity` marker requirement.
*Test:* a correct derivation passes; a tampered FTE fails with the inverted error.

**Phase 3 — Payload shape + title distribution.** Distribute the derived total FTE across OEWS
titles (default proportional split, §3.6/3.10), preserve grid + quarter_totals shape.
*Test:* `assert_payroll_headcount_payload_ready` and
`assert_finmo_payroll_matches_headcount_schedule` pass; quarter_totals reconcile to finmo.

**Phase 4 — Override + coverage guardrail.** Implement the stored FTE/productivity override
(§3.5) and wire `min_capacity_coverage_ratio` as the under-staffing check.
*Test:* driver override (productivity↑) lowers FTE and payroll; direct FTE override below
derived trips coverage<1.0; above derived passes coverage but may trip the §3.7 sanity check.

**Phase 5 — Demote the sanity check + flip doctrine.** Make payroll-% a check-only path (§3.7),
flip the doctrine flags and reverse the context notes/docstrings (§3.8), remove the
Capacity rebuild triggers (§3.9).
*Test:* a NAICS with cohort coverage uses it; a NAICS without falls back to tier bounds
([0.06,0.80]); no code path lets payroll-% change FTE.

**Phase 6 — End-to-end.** Full post-intake run on a known fixture (e.g. NexGen): revenue →
capacity → FTE → payroll → finmo, single pass, all validators green; adjust productivity and
confirm headcount + payroll + feasibility move downstream.

Per the team norm, commit + push at each phase boundary so regressions isolate.

---

## 7. OPEN QUESTIONS (Nick's call)

- **OQ-1 (blocking): Productivity starting value has no current source.** Bounds columns are
  dropped as legacy with no replacement; `productivity_assumptions` is a phantom key; no NAICS
  productivity baseline exists. Pick the starting-value mechanism: (a) defaulted policy column
  [recommended], (b) intake-derived prior, or (c) a new per-NAICS productivity baseline.
- **OQ-2: Heterogeneous capacity units across products.** Is a single global productivity over
  the summed required capacity valid, or must productivity be per-product (or per-LOB)? Affects
  §3.3 aggregation.
- **OQ-3: Weak/absent capacity anchor.** When intake captured no capacity fields,
  `required_capacity` degrades to a Year-1-projection fallback (or 0). Define behavior: block,
  warn, or derive FTE from the fallback revenue target instead?
- **OQ-4: Override storage + semantics.** Where does a direct FTE/productivity override live,
  and does a direct FTE override suppress derivation for that quarter or just offset it?
- **OQ-5: Sanity violation severity.** Now that headcount is capacity-derived, is a
  payroll-%-of-revenue out-of-band a hard fail or a warning?
- **OQ-6: Monotonicity rules.** Keep `average_fte_cannot_decline_when_capacity_increases` etc.
  ([lookup.py:85-88](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L85-L88))
  as validators (now consequences of the derivation), or drop them?
- **OQ-7: Default title mix before Executive exists.** Confirm the interim deterministic split
  (preserve current authored proportions scaled to derived total) is acceptable until the
  Executive layer authors the title mix.

---

## 8. Hard-rule compliance

Spec only — no code changed. The three verification gates are resolved with file:line: cohort
`payroll_percent_of_revenue` coverage **confirmed real + fallback defined** (§2.5); revenue.Capacity
anchor **confirmed intake-grounded with a documented degraded-fallback caveat** (§2.4, OQ-3);
productivity starting value **confirmed to have no current source → flagged blocking OQ-1**
(§3.4). Executive layer, intake, and contract-layer code untouched.
