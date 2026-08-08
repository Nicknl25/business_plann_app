# Pass-2 Design Specs — three class-closing designs (for Nick's review; NO code until ruled)

The shared shape: each class has been patched per-instance (janitorial =
degenerate-anchor softening; wages = title-token percentiles; splice = 17
renderer/regex patches) and keeps recurring because the structure underneath
is unaddressed. Each spec: mechanism, design, the decision points, rails,
verification.

---

## SPEC 1 — Labor-heavy basis reconciliation

**Mechanism (proven, CW-018 trace):** cohort COGS for labor-heavy NAICS is
labor-INCLUSIVE (public-company CostOfRevenue includes service labor:
561720 = 87.2% via industry_metrics_raw n=15, corroborated 87.7% via SEC
EDGAR; gross margin 12.8% confirms) while intake captures labor-EXCLUSIVE
(supplies-only COGS + separate payroll). The cohort's own rows prove the
overlap: cogs% + payroll% sums to 125-147% at NAICS 561. Every raw-band
consumer double-counts labor for cleaning/security/staffing/home
care/landscaping. Data check: `payroll_percent_of_revenue` (CBP/SOI-derived)
exists at 298 six-digit codes with a level cascade behind it — the
conversion has data.

**Detection (deterministic, no GPT):** the load-bearing signal is the
cohort's own self-contradiction — at the resolved NAICS level,
`cogs_target + payroll_target > 1.0` (a business cannot spend >100% of
revenue on those two lines unless the bases overlap). Corroborating
per-business signals, required as confirmation: `capacity_driver ==
"labor"` OR the margin-band `measured_basis` (client payroll share high,
client COGS low). Rule: convert only when the data signal AND ≥1 business
signal agree.

**Conversion:** `cogs_ex_labor_target = cohort_cogs_target −
cohort_payroll_target` (floored at a derived materials floor: keep the
band's P25→P75 spread shape, shift all three edges by the same
subtraction, floor min at 0.01). Payroll row resolved at the same NAICS
level as the COGS row, cascading 6→5→4→3; **no payroll coverage at any
level → NO conversion** — the band demotes to context (never guess a
subtraction). 561720 worked example: 87.2% − 60.4% (L3 payroll) ≈ 26.8%
target — the Ironclad/Bluff stated 6-8% then sits inside a materials band
instead of 10x below its floor.

**WHERE — the decision Nick rules on:**
- **Option A, population time** (write adjusted rows into the lookup table
  as `data_source="labor_basis_adjusted"`): one data seam, every consumer
  inherits. BUT it bakes interpretation into a measurements table, obscures
  SOI/EDGAR provenance, must re-run on every data refresh, and cannot use
  the per-business confirmation signals (population knows no client).
- **Option B, resolution time (RECOMMENDED)**: apply at the TWO code seams
  every consumer already flows through — the NAICS baseline reader
  (`post_intake_industry_baseline_for_naics` / `_resolve_naics_bound`) and
  the cohort-bands populator (`cohort_bands_table.populate`). Raw data
  stays raw; per-business signals available; provenance stamped on the
  resolved band (`basis: labor_adjusted`, payroll row + level used);
  band-fitting's operator rescale and the degenerate-anchor/arbitration
  machinery compose unchanged downstream (they receive a sane envelope, so
  the Luna-class guard mostly stops firing for these industries).
- **Option C, per-consumer**: rejected — that is the per-instance patching
  disease this pass exists to end.

**Rails:** never applies when the sum ≤ 1.0 at the resolved level (retail/
manufacturing unchanged — the negative control); client-stated COGS stays
the operator anchor exactly as today; every conversion emits a runtime
trace advisory (observability, informant-ledger style); the arbitration
seat keeps its authority.

**Verification:** unit E2E on the 561720 numbers (worked example above) +
a retail NAICS negative control; then rerun the real Bluff City draft
build and diff fitted bands + realism verdicts (the real-case rerun
standard).

---

## SPEC 2 — OEWS wage-mapping seniority

**Mechanism (traced, 4 live occurrences):** the percentile-spread fix
(#14: junior→pct25 / base→median / senior-owner→pct75) exists but has two
blind axes. (a) The tier tokens miss managerial titles entirely —
`manager`, `director`, `supervisor`, `vp`, `gm` are in NO tier list
("managing" ≠ "manager" under word-boundary matching) → tier None →
median. (b) Seniority is read from the TITLE only; the narrative ("18
years, certified installer, runs an entire division") never reaches the
percentile choice. The inversions are usually CROSS-OCCUPATION: the senior
title maps to the base worker occupation (its median) while a junior role
maps to a better-paid occupation — no within-row percentile can fix an
ordering across rows.

**Design, three layers:**
1. **Widen deterministic tier tokens**: managerial set (`manager`,
   `director`, `supervisor`, `superintendent`, `gm`, `vp`, `president`,
   `principal`, `foreman`) → senior tier. Cheap, closes the Catawba shape.
2. **Narrative-read tier from the EXISTING occ-match GPT call**: the call
   that already reads the role description to pick the OEWS occupation
   returns one more structured field, `seniority_tier`
   (junior/base/senior/owner), judged from years, credentials, and scope
   ("runs/oversees/leads", team size). Same call count, locked/replayable
   as today. Deterministic tokens compose as a one-way rail: they can only
   raise the tier, never lower it.
3. **Within-business monotonicity rail (deterministic, the class-closer)**:
   after defaults land, if a higher-tier role's default wage is BELOW any
   lower-tier role's default in the same business, raise it to that level
   (raise-only — conservative, never cheapens anyone). This is the
   cross-occupation ordering fix that percentiles alone cannot express.
   Client-stated wages are exempt and untouchable (fact-first, existing
   `client_override` marking).

**Verification:** replay the four live inversion narratives (Catawba
install-division manager verbatim + the CW-009 cases) — RED shows the
inversion, GREEN shows ordering; negative controls: stated wages
untouched; an actual junior role keeps pct25; single-role businesses
unaffected.

---

## SPEC 3 — Multi-product pricing summary placeholder

**Mechanism (17 occurrences; Oak City proves partial fixes can't close
it):** the fact vocabulary only has SCALAR `unit_price`/`unit_name` keys,
so multi-product businesses render as welded ranges/lists in whatever
idiom the GPT happens to emit — and the prompt itself TEACHES the scalar
idiom. Oak City post-fix: price-name pairs render correctly, but the
opening unit-list still welds ("per building-month of service, project,
and job") and a trailing clause hangs all prices on one product. The
placeholder must own the WHOLE pricing sentence.

**Design, three parts:**
1. **New fact key `ops.product_pricing_summary`** (added to FACT_GROUPS;
   resolver builds the complete pricing fragment from lob_models):
   per-product `"$<price> per <humanized name> (<cadence phrase>)"` joined
   and-style — e.g. *"$1,200 per building-month of bundled service,
   $19,500 per project, and $1,450 per on-call job"*. Humanizer:
   snake_case→spaces (fixes the internal-name leak as a shared formatter
   applied to ALL ops name renders); cadence phrase derived from
   unit_cadence/operating_periods_per_year (monthly → "per month" already
   implied by the unit name where it carries it — no duplicate cadence
   when the name embeds it). Single product degrades to the scalar form.
2. **Prompt rule** in the three target-market template sections: when the
   business has multiple products, the pricing statement MUST be exactly
   `{{fact:ops.product_pricing_summary}}` — the scalar pair is banned for
   multi-product. (The resolver keeps the CW-018 pair-render and range
   forms as defense-in-depth for GPT disobedience, but the taught path now
   owns the sentence.)
3. **Retire idiom patching**: no further per-phrasing regex work — misuse
   degrades to the already-safe paired forms, and occurrences get filed
   against prompt compliance, not the renderer.

**Verification:** render tests on the three live shapes (Catawba 3-product
verbatim, Vanguard 2-product, single-product) + snake_case humanization
asserts; prompt compliance observed in the pass-2 confirmation run (which
also carries the 5bf1bf7 band-fix live confirmation, per the roll-in).

---

*Written for review as a set (2026-08-08). Build starts per-spec on
Nick's ruling; Spec 1 additionally needs the WHERE decision (A vs B).*
