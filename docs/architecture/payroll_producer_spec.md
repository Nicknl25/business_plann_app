# Payroll Producer — Spec

**Status:** SPEC / DESIGN ONLY. No code, no implementation. Every codebase claim is grounded in
file:line. Where intake/data cannot supply a value, it is said plainly and routed to a **named
policy default** or to **GPT review** — no silent hardcodes.

**Decision (given):** **Lineage B.** Python authors the round-1 `payroll_headcount_schedule`
deterministically; GPT critiques the output via the responder (confirm/veto/choose/other). We are
**not** giving GPT a payroll authoring surface.

**The gap being closed.** `set_payroll_schedule(contract=None)` →
`build_pending_payroll_stub` ([set_payroll_schedule.py:266-273](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L266-L273),
[lookup.py:939-981](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L939-L981))
returns a structurally-valid PLACEHOLDER. `set_stage_ramp_contract` and
`set_capex_rd_balance_seed` have real deterministic round-1 producers
([runner.py:1036](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1036),
[runner.py:862](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L862));
payroll does not. This spec defines the missing producer.

**Builds on (not re-derived):**
[executive_amalgamation_build_scope.md](executive_amalgamation_build_scope.md),
[payroll_schedule_revenue_grounding_research.md](payroll_schedule_revenue_grounding_research.md),
[fix_2_headcount_derivation_trace.md](fix_2_headcount_derivation_trace.md),
[fix_2_headcount_derivation_spec.md](fix_2_headcount_derivation_spec.md).

---

## Part A — Where the producer sits

Round-1 payroll authoring is the `set_payroll_schedule(contract=None)` call at
[runner.py:1197-1212](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1197-L1212).
The producer is the thing that, today, returns the stub on the `contract=None` path
([set_payroll_schedule.py:236-273](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L236-L273)).
It must instead return a **real contract**, which then flows through the existing, unchanged
machinery:

1. **Validate** — `validate_payroll_headcount_contract_payload`
   ([schedule.py:1843-1898](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1843-L1898),
   wired at [set_payroll_schedule.py:216-220](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L216-L220)).
2. **Build** — `build_payroll_headcount_payload_from_contract`
   ([schedule.py:1901-2042](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1901-L2042),
   wired at [set_payroll_schedule.py:221-225](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L221-L225)):
   resolves OEWS wages, injects key people, computes quarter_totals, then validates the payload via
   `validate_payroll_headcount_payload` ([lookup.py:1076-1193](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L1076-L1193)).
3. **Land in the Mirror** — accepted `payload` → `plan_state["payroll"]`
   ([runner.py:1840-1850](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1840-L1850)),
   then the SessionDriver cascade can critique it (Part H).

**Key consequence:** the producer authors the **contract** (the per-title/per-quarter FTE grid +
root fields). The existing **builder** already does wage resolution and payroll-dollar math
([schedule.py:1964-1967](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1964-L1967)).
So the producer's job is to **fill the grid** using the dollar path, then hand a complete contract
to the unchanged validate→build path. The producer's sizing math and the builder's payroll math
**must use the same wage resolution** (Part B.3) or the produced FTE and the built payroll dollars
will disagree.

The producer's inputs are already present at the `set_payroll_schedule` boundary:
`business_facts`, `ops_json`, `people_json`, `financials_json`, `financials_year1_json`,
`model_input_json`, `finmo_json`, `stage_ramp_contract`
([set_payroll_schedule.py:161](../../python/client_intake_and_finmo/post_intake_amalgamated/tools/set_payroll_schedule.py#L161);
passed [runner.py:1197-1212](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1197-L1212)).
The per-quarter revenue the dollar path needs is inside `model_input_json` / `finmo_json`.

---

## Part B — Q1: FTE from revenue via the DOLLAR path (the core)

### B.1 The formula chain

The producer sizes supporting FTE from the business's OWN per-quarter revenue, via dollars —
**never** via `FTE = required_capacity ÷ productivity`. Per quarter `q` (Q1…Q20):

```
1. revenue_q                = own per-quarter revenue (B.2)
2. pct_mid                  = midpoint of the resolved labor_intensity_class band (B.4, Part D)
3. total_payroll_budget_q   = revenue_q × pct_mid          # band is on TOTAL payroll (wages+benefits)
4. key_people_payroll_q     = Σ key-person payroll          # fixed from intake (B.5)
5. supporting_budget_q      = max(0, total_payroll_budget_q − key_people_payroll_q)
6. allocate supporting_budget_q across chosen OEWS titles by mix weight w_i (Part C):
      k_q = supporting_budget_q × 4 / ( (1 + benefits_pct) × Σ_i ( w_i × annual_wage_i ) )
      FTE_iq = k_q × w_i
7. starting/ending FTE per title per quarter follow the revenue ramp (B.6)
```

Step 6 is the inversion of the builder's payroll formula
`quarterly_payroll = average_fte × annual_wage / 4 + benefits`
([schedule.py:1964-1967](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1964-L1967)):
solving that for `average_fte` given a dollar budget. **`capacity_units_per_supporting_fte` does
not appear anywhere in steps 1-7.** That is the deliberate avoidance of the Fix #2 wall
(OQ-1: productivity has no dataset). The productivity field is handled in Part G as a *reported*
output, not an input.

**Anti-pattern guard.** If any future revision introduces `required_capacity_q = revenue_q ÷
(price_q × util_q)` followed by `FTE = required_capacity_q ÷ productivity`, that is the Fix #2
causal-reversal path the decision rejected — it reintroduces the productivity dependency. The
dollar path above is chosen precisely because it converts revenue→FTE through **wages** (a
well-covered NAICS quantity, Part C) instead of through **productivity** (no data).

### B.2 Where revenue comes from

`_revenue_driver_context_from_model_input`
([schedule.py:2244-2316](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2244-L2316))
already exposes, per quarter Q1-Q20, both `computed_revenue_from_model_input`
([schedule.py:2287-2290, 2306](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2287-L2290))
and `finmo_revenue` ([schedule.py:2274-2280, 2307](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2274-L2280)).
Revenue is `Σ(Capacity × Unit Price × Utilization)`
([finmo_bridge.py:1910-1915](../../python/client_intake_and_finmo/finmo_bridge.py#L1910-L1915),
[finmo_bridge.py:634](../../python/client_intake_and_finmo/finmo_bridge.py#L634)). Revenue Capacity
is authored at step 10 (`prepare_baseline_model_input`,
[post_intake_mapping.py:686-708](../../python/client_intake_and_finmo/post_intake_mapping.py#L686-L708)),
**before** payroll — so the trajectory exists when the producer runs.

**Use `finmo_revenue` as the `revenue_q` source** (the built, reconciled revenue) and fall back to
`computed_revenue_from_model_input` if a quarter's finmo revenue is absent. **[Decision to confirm]**
— either is defensible; finmo is the post-build figure the feasibility check itself uses.

### B.3 Wages (the conversion factor)

Annual wage per title = `_policy_adjusted_annual_wage` =
`base × max(1.0, wage_positioning_multiplier) × inflation`
([schedule.py:226-237](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L226-L237)),
inflation = `(1 + annual_wage_inflation_rate)^year_offset`
([schedule.py:220-223](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L220-L223),
default rate 3% [lookup.py:39](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L39)).
Base wage = `_select_wage` (prefers `a_median`, falls back to `a_pct10`)
([people_roles.py:291-316](../../python/client_intake_and_finmo/people_roles.py#L291-L316)). The
producer must call this **same** path for its step-6 sizing so the FTE it emits reproduces the
payroll dollars the builder will compute.

### B.4 The percent-of-revenue midpoint

Per-class bands ([lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79)):
low 6-45%, medium 10-55%, high 16-70%, expert 18-80%; resolved via
`headcount_payroll_revenue_sanity_bounds`
([lookup.py:836-850](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L836-L850)).
**Midpoint is not computed anywhere today** — the producer computes `(min_pct + max_pct) / 2`
**[INFERENCE / new]**. Sizing to the midpoint centers the produced ratio inside the band, so the
post-build feasibility check (Part E.3) passes by construction. The class itself is resolved in
Part D.

### B.5 Key people are subtracted first, not sized

Key people come from intake (`staffing_class = "key_person"`,
[schedule.py:766-825](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L766-L825)),
are pinned at FTE 1.0 across all quarters ([schedule.py:812-814](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L812-L814)),
and are merged ahead of supporting rows by the builder
([schedule.py:1940-1943](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1940-L1943)).
The producer authors **supporting** roles only (matching the existing division of labor,
[post_intake_mapping.py:2133](../../python/client_intake_and_finmo/post_intake_mapping.py#L2133)).
Step 4 subtracts the fixed key-people payroll from the budget so supporting FTE fills only the
**remaining** dollars — preventing double-counting against the revenue band.

### B.6 The ramp

`starting_fte`/`ending_fte` per title per quarter track the per-quarter revenue trajectory (B.2):
`ending_fte_iq = FTE_iq` from step 6 using `revenue_q`; `starting_fte_iq = ending_fte_i(q-1)`;
`hires_iq = max(0, ending_fte_iq − starting_fte_iq)`. This makes headcount **rise with the revenue
plan** — the D2 "staff toward revenue" property, achieved structurally rather than by instruction.

---

## Part C — Q2: Role-mix sourcing

**v1 — FINALIZED:** the role mix is **OEWS `tot_emp` proportion (top-N capped) + intake key
people**. No alternative sourcing in v1; the GPT cascade can swap individual titles reactively
(Part H). The two net-new pieces are (i) surfacing `tot_emp` into the catalog query and (ii) the
proportion/top-N allocation — both flagged below.

### C.1 Candidate titles (data-grounded, exists today)

`_oews_title_catalog_for_business`
([schedule.py:973](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L973)) →
`_oews_rows_for_business` ([schedule.py:828-867](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L828-L867))
fetches OEWS rows **filtered by NAICS** (SQL `WHERE prim_state=%s AND naics=%s`,
[people_roles.py:320-331](../../python/client_intake_and_finmo/people_roles.py#L320-L331)) and
returns `occ_title, occ_code, annual_wage, wage_source`
([schedule.py:934-970](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L934-L970)),
excluding "all occupations" ([schedule.py:946](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L946)).

### C.2 Mix weights from `tot_emp` (data exists; algorithm is NEW)

The employment-count column `tot_emp` exists in `oews_state_wages`
([bls_employment_wages_loader.py:165-174](../../python/data_pull/bls_employment_wages_loader.py#L165-L174))
and is a near-census occupation-by-NAICS staffing signal. **There is no existing code that derives
a staffing mix from `tot_emp`** — the only `tot_emp`-weighted computation in the repo is
industry-average wage in a baseline loader
([scripts/load_industry_baseline_lookup.py:387-450](../../scripts/load_industry_baseline_lookup.py#L387-L450)),
which is unrelated, and the catalog does **not** currently surface `tot_emp`
([schedule.py:934-970](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L934-L970)).
**[NEW WORK]** the producer (or an extended catalog query) must read `tot_emp` per occupation for
the NAICS and compute `w_i = tot_emp_i / Σ tot_emp`, restricted to a policy-capped top-N titles
(e.g. top 6-8 by `tot_emp`) to keep the grid within validator bounds (≥20, ≤400 rows total across
Q1-Q20, Part F). The cap is a **named policy default**, not a silent constant.

### C.3 Scaling and ramp

The mix weights `w_i` are scale-free; the FTE *level* per title per quarter comes entirely from the
dollar path (Part B step 6). As `revenue_q` ramps, `supporting_budget_q` ramps, so each title's FTE
ramps proportionally — the mix shape is constant, the headcount scales with revenue.

### C.4 Unusual businesses → GPT review backstop

When OEWS coverage is thin (NAICS-6 suppressed or sparse — the known coverage limit, see
[phase_9_naics_coverage_audit.md](phase_9_naics_coverage_audit.md)): `_oews_rows_for_business`
already falls back across geography/NAICS
([schedule.py:859](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L859));
if it still returns too few titles to staff, the producer emits its best deterministic mix and the
**GPT review backstop** (Part H) is the safety net — GPT can veto/swap a wrong title via the
cascade's `other_proposal`. **Honest flag:** that backstop is **reactive** (Part H) — it only
engages if the mix trips a standards check; an odd-but-passing mix ships unreviewed. Tracked as
OQ-3.

---

## Part D — labor_intensity_class: deterministic resolution

Today the class is **GPT-chosen**; the intake-implied payroll/revenue ratio is computed but
explicitly **non-binding** (`_intake_implied_operating_intensity`,
[schedule.py:1730-1799](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1730-L1799),
"INFORMATIONAL … may still choose any class" [schedule.py:1753-1754](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1753-L1754)).
For a deterministic producer it must be **resolved by Python**:

1. Compute the intake-implied ratio `payroll_total_year1 / revenue_year1`
   ([schedule.py:1768-1779](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1768-L1779)).
2. If present, select the class whose band ([lookup.py:74-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L79))
   contains it — `intensity_classes_accepting_target_payroll_pct`
   ([lookup.py:853-897](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L853-L897))
   already maps a percent to accepting classes; pick the tightest containing class.
3. If intake does not supply the ratio (no `payroll_total_year1` or no revenue): **route to a named
   policy default `medium`** AND flag the contract `rationale` so the GPT backstop can re-class.
   This is the "say so plainly, route to default + GPT" path — no silent pick.

The resolved class drives the midpoint (B.4) and is emitted as `labor_intensity_class` (Part F).

---

## Part E — Q3: The capacity overwrite (resolving the loop)

### E.1 The loop, precisely

Today `apply_payroll_supported_capacity_to_model_input`
([schedule.py:2525-2642](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2525-L2642),
called post-payroll [runner.py:1323-1344](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1323-L1344))
**overwrites** `model_input.revenue.Capacity` ([schedule.py:2541](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2541))
with `supported_capacity = average_fte × capacity_units_per_supporting_fte`
([schedule.py:2568-2571, 2631](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2568-L2571)).
Since revenue = Capacity × Price × Util ([finmo_bridge.py:1910-1915](../../python/client_intake_and_finmo/finmo_bridge.py#L1910-L1915)),
and the new producer derives FTE **from** revenue (Part B), keeping the overwrite creates:
**revenue → FTE → Capacity → revenue** — a circular rewrite that would corrupt the
step-10-authored revenue and re-introduce productivity as the hinge.

### E.2 Resolution: REMOVE the overwrite on the producer path; optionally replace with a non-mutating check

- **Remove the mutation.** Revenue Capacity authored at step 10 is the anchor (revenue-primary);
  payroll is sized from it and does **not** write back. This directly serves the decision
  (revenue-driven payroll) and the "remove/convert legacy, don't route around it" rule — with
  productivity no longer a driver, the overwrite's input (`× capacity_units_per_supporting_fte`)
  has no defensible source anyway.
- **Optionally replace with a consistency CHECK** (non-mutating): compute implied capacity from FTE
  and warn / route to GPT if it diverges materially from the authored revenue Capacity, **without**
  rewriting. This preserves a coherence signal (the original intent of the function,
  [schedule.py:2534](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2534))
  without the loop. **[Recommended: remove the mutation; keep a check only if a coherence signal is
  wanted.]**

### E.3 Blast radius

- The post-payroll call site ([runner.py:1323-1344](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1323-L1344))
  no longer rewrites `revenue.Capacity`; downstream consumers of the *overwritten* capacity now see
  the step-10 capacity. Audit those consumers before removing.
- The payroll-%-of-revenue **feasibility check** still runs
  (`payroll_revenue_feasibility_violations`,
  [schedule.py:2818-2989](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2818-L2989),
  invoked in finalize via [fail_fast.py:727-771](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L727-L771))
  and is unaffected **as a check** — but its **repair** currently nudges productivity
  ([schedule.py:2902-2964](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2902-L2964))
  and the repair step writes both Payroll and Capacity
  ([post_intake_mapping.py:754-822](../../python/client_intake_and_finmo/post_intake_mapping.py#L754-L822)).

  **OQ-1 disposition — RESOLVED: retire the productivity-nudge as the repair lever.** With the
  capacity overwrite dropped (E.2), `capacity_units_per_supporting_fte` is no longer a driver
  (Part G), so a repair that adjusts productivity has nothing real to move — it is vestigial and
  must be retired, not re-pointed at productivity. The feasibility check **as a check** stays. When
  it fires — only possible if a later cascade revision moves revenue off the midpoint the producer
  sized to (B.4) — the correct repair is to **re-run the dollar path (Part B) against the revised
  per-quarter revenue**, re-deriving supporting FTE / wage-budget. That re-derivation is the
  consistent lever: it is the same producer math, just re-applied. The productivity-nudge math at
  [schedule.py:2902-2964](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2902-L2964)
  and the dual Payroll+Capacity write at
  [post_intake_mapping.py:822](../../python/client_intake_and_finmo/post_intake_mapping.py#L822)
  should be removed/converted as part of the same change that removes the overwrite (per the
  "remove/convert legacy, don't route around it" rule) — not left dormant. Round-1 violations are
  unlikely because the producer sizes to the band midpoint; this disposition governs the later-drift
  case.

---

## Part F — Q4: Every field the producer must emit to PASS the validator (the hard bar)

Canonical contract validator: `validate_payroll_headcount_contract_payload`
([schedule.py:1843-1898](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1843-L1898));
field declarations [post_intake_mapping.py:2048-2160](../../python/client_intake_and_finmo/post_intake_mapping.py#L2048-L2160);
enum/bound policy [lookup.py:40-79](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L40-L79).
The stub fails because grid is empty, the three enums are `""`, three numerics are `0.0`, and
`rationale` is absent ([lookup.py:904-936, 971-980](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L904-L936)).

### Root fields

| Field | Constraint (file:line) | Producer source / derivation |
|---|---|---|
| `payroll_headcount_grid` | array, ≥20, ≤400, Q1-Q20 each ≥once ([mapping.py:2124-2134](../../python/client_intake_and_finmo/post_intake_mapping.py#L2124-L2134)) | supporting rows from Part B/C, per title per quarter; key people merged by builder |
| `capacity_labor_model` | enum labor_driven/hybrid/system_driven/expert_driven ([mapping.py:2135](../../python/client_intake_and_finmo/post_intake_mapping.py#L2135), [lookup.py:40-44](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L40-L44)) | **no data source** → named policy default mapped from `labor_intensity_class` (e.g. medium→`hybrid`); GPT may swap. **[OQ-2]** |
| `labor_intensity_class` | enum low/medium/high/expert ([mapping.py:2136](../../python/client_intake_and_finmo/post_intake_mapping.py#L2136), [lookup.py:46-50](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L46-L50)) | resolved deterministically (Part D); default `medium` + flag if intake silent |
| `wage_positioning_tier` | enum floor/market/premium/specialized ([mapping.py:2137](../../python/client_intake_and_finmo/post_intake_mapping.py#L2137)) | **no data source** → named policy default `market`; GPT may adjust |
| `wage_positioning_multiplier` | number 1.0-3.0, tier-consistent ([mapping.py:2138](../../python/client_intake_and_finmo/post_intake_mapping.py#L2138)) | `1.0` (matches `market`); changes only if tier changes |
| `capacity_units_per_supporting_fte` | number >0 (min 0.0001) ([mapping.py:2139](../../python/client_intake_and_finmo/post_intake_mapping.py#L2139)) | **DERIVED / reported**, not a driver — Part G |
| `target_payroll_percent_of_revenue` | 0.06-0.80, accepted by chosen class ([mapping.py:2150-2158](../../python/client_intake_and_finmo/post_intake_mapping.py#L2150-L2158)) | = `pct_mid` (B.4); in-band by construction |
| `rationale` | non-empty string ([schedule.py:1876-1882](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1876-L1882)) | generated: states revenue×midpoint→budget→wage→FTE chain, mix source, any default/flag |

### Per grid-row ([mapping.py:2048-2054](../../python/client_intake_and_finmo/post_intake_mapping.py#L2048-L2054))

| Field | Constraint | Producer source |
|---|---|---|
| `q` / `quarter_index` | int 1-20, Q1-Q20 each ≥once | row's quarter |
| `oews_occ_title` | must be a catalog member ([lookup.py:1006-1009](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L1006-L1009)) | chosen title from C.1 (key people may omit per [lookup.py:1006-1009](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L1006-L1009)) |
| `starting_fte` | 0-100000 | ramp (B.6) |
| `hires` | 0-100000 | `max(0, ending−starting)` (B.6) |
| `ending_fte` | 0-100000 | dollar-path FTE (B step 6) |
| `payroll_tax_benefits_pct` | 0.12-0.35 ([mapping.py:2054](../../python/client_intake_and_finmo/post_intake_mapping.py#L2054)) | **named policy default** within band (e.g. policy benefits %); same value used in B step 6. **[OQ-4]** confirm the policy default exists |

After the contract validates, the builder adds `average_fte`, `quarterly_wage_cost`,
`quarterly_taxes_benefits`, `total_quarterly_payroll`, and `quarter_totals`
([schedule.py:1964-2000](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L1964-L2000))
and re-validates the payload ([lookup.py:1076-1193](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L1076-L1193)).
The producer does not emit those — but its FTE must be wage-consistent (B.3) so the payload-level
totals and the feasibility ratio land on the midpoint.

---

## Part G — Q5: The productivity field (reported, never looked up)

`capacity_units_per_supporting_fte` is a **required** contract field (>0,
[mapping.py:2139](../../python/client_intake_and_finmo/post_intake_mapping.py#L2139)) but in this
design it is **not a driver** (Part B avoids it; Part E removes the overwrite that consumed it).
Spec it as **DERIVED / reported**, computed *after* FTE is sized:

```
capacity_units_per_supporting_fte = (Σ_q authored revenue Capacity_q) / (Σ_q supporting average_fte_q)
```

i.e. back-computed from the step-10 revenue Capacity (B.2) and the producer's own supporting FTE —
a *reported* ratio that satisfies the contract and is internally consistent, with **no data
lookup** (honoring Fix #2 OQ-1). If supporting FTE is ~0 in early quarters (degenerate divisor),
fall back to a **named intensity-class policy default** purely to keep the field positive and
valid, clearly labeled in `rationale` as non-driving. **Chosen form: DERIVED/reported (with a named
default fallback only for the degenerate case).** It must never be a NAICS/data lookup —
[mapping.py:2139](../../python/client_intake_and_finmo/post_intake_mapping.py#L2139) itself says
"Do not use revenue-per-employee."

---

## Part H — Q6: GPT review attach point

The producer's output lands in `plan_state["payroll"]`
([runner.py:1840-1850](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1840-L1850)).
GPT critiques it through the **restructure protocol**, not a standalone approval:

- When a payroll-implicated check fails — e.g. `fixed_cost_burden_reduced_or_scaled_by_q11`
  ([evaluate_plan.py:74](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L74)) —
  the cascade builds a Python proposal and the responder presents it; GPT replies via the four
  response tools (`confirm_proposal` / `veto_proposal` / `choose_option` / `other_proposal`,
  [responder.py:75-152](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L75-L152)).
- An accepted move is applied by `revise_payroll_schedule`
  (dispatch [session_factory.py:138-144, 156-163](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_factory.py#L138-L163)),
  which patches the producer's contract.

**What GPT can do:** confirm the Python-proposed payroll revision, veto it with a business reason,
choose among offered options, or propose an in-band alternative value (`other_proposal`,
[responder.py:131-151](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L131-L151)).
It judges the proposed *revision* — it does not author the schedule (Lineage B).

### H.1 OQ-3 disposition — RESOLVED: payroll review is REACTIVE, identical to every other surface

GPT review is reactive **for every surface**, by the §12 protocol's design, not as a payroll
quirk. The SessionDriver calls the responder (GPT) **only** in the cascade/failure path
([session_driver.py:511](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L511),
inside `_apply_tier`); the happy path is `EVALUATE → all_pass → FINALIZE` with **no GPT call**
([session_driver.py:254-265](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/session_driver.py#L254-L265)).
Stage_ramp, drivers, and capex/B-seed are all reviewed the same way: only when an `evaluate_plan`
standard fails. Adding a bespoke always-on payroll review tier would be the **inconsistent
special-case** — so we do **not** add one. Payroll review stays reactive, on consistency grounds.

**The corollary:** if the right behavior is "an implausible mix must be seen," the consistent place
to enforce that is a **standard in `evaluate_plan`**, not a special review path. A new standard
fails → the normal cascade fires → the normal responder review happens. That moves the lever to the
layer every other realism concern already lives in.

### H.2 Mix quality belongs to the standards layer (not review)

**(a) What `evaluate_plan` checks for payroll today — DOLLARS only; NO mix-sanity standard exists.**
The amalgamated standards checker has exactly **one** payroll-implicated check:
`fixed_cost_burden_reduced_or_scaled_by_q11` (VIABILITY_INVARIANT, implicated `("drivers","payroll")`,
[evaluate_plan.py:74](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L74)).
It tests a **dollar aggregate** — `(payroll + lease) / revenue` shrinking Q1→Q11
([mini_finmo.py:82-98](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L82-L98),
test [mini_finmo.py:400-402](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L400-L402)).
The payroll-%-of-revenue feasibility check is **separate** and does not run inside `evaluate_plan` —
it runs in finalize
([fail_fast.py:727-771](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L727-L771)
→ [schedule.py:2818-2966](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2818-L2966)),
and is keyed by `labor_intensity_class`, not by occupation
([schedule.py:2855](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2855)).
**Verified definitive:** no check in `evaluate_plan`, the acceptance gate
([gate.py:713-760](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L713-L760)),
or mini_finmo tests **role-mix / occupation plausibility** — which OEWS titles are staffed, whether
the FTE distribution across occupations is reasonable, or whether the composition is sane. The
mix-plausibility domain is **uncovered**. So an implausible-but-affordable mix (dollars fine,
composition wrong) can pass to FINALIZE unseen.

**(b) Proposed standard (spec note only — no code): `payroll_role_mix_plausible`.** Add a check to
the `evaluate_plan` registry so mix sanity is caught in the consistent place; on failure it triggers
the normal cascade → responder review, exactly like every other realism failure.

- **Where:** new entry in `_CHECK_REGISTRY`
  ([evaluate_plan.py:68-96](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L68-L96)).
- **FailureMode:** `BAND_INVARIANT` (cohort-shape realism — the same family as "any lever outside its
  cohort band", [evaluation_types.py:33](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluation_types.py#L33));
  implicated_sections `("payroll",)`.
- **What it would check** (composition realism against the cohort employment shape the producer
  itself uses, Part C.2):
  1. **Non-empty supporting staff when revenue > 0** — a plan with revenue but zero supporting FTE
     (outside key people) is implausible.
  2. **Per-occupation FTE share vs OEWS `tot_emp` share** — for each authored supporting title, its
     FTE share of the supporting total should sit within a tolerance band of that occupation's
     `tot_emp` share within the NAICS
     ([bls_employment_wages_loader.py:165-174](../../python/data_pull/bls_employment_wages_loader.py#L165-L174)).
     Flag titles carrying near-zero cohort employment but large FTE, or a single non-key occupation
     absorbing an implausible share.
  3. **Title-count plausibility** — supporting-title count within a policy min/max for the business
     scale (avoids both a 1-title monoculture and an over-fragmented grid).
  - Tolerance band is a **named policy value**, not a literal (consistent with the rest of this spec).
- **Honest nuance (state it):** because the **producer** sizes the mix *from* `tot_emp` shares
  (Part C.2), the producer's own round-1 output will trivially pass check (2). So this standard
  mainly bites on (i) **GPT revisions** that drift the mix via `other_proposal`
  ([responder.py:131-151](../../python/client_intake_and_finmo/post_intake_amalgamated/protocol/responder.py#L131-L151)),
  (ii) **sparse-NAICS fallbacks** where the catalog returned too few/odd titles
  ([schedule.py:859](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L859)),
  and (iii) any future non-deterministic authoring. It is still the right place: it is the standard
  that lets the cascade surface a bad mix to GPT through the normal path, and it stays valid if the
  producer is ever changed.

---

## Part I — Open questions (routes, not silent hardcodes)

- **OQ-1 — feasibility repair lever. RESOLVED (Part E.3):** retire the productivity-nudge repair
  ([schedule.py:2902-2964](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2902-L2964),
  [post_intake_mapping.py:822](../../python/client_intake_and_finmo/post_intake_mapping.py#L822)) as
  part of removing the overwrite; if the feasibility check fires on later revenue drift, re-run the
  Part B dollar path against the revised revenue (FTE/wage-budget is the lever, never productivity).
- **OQ-2 — `capacity_labor_model` default.** No data source. Spec'd as a named
  intensity→labor_model policy map; confirm the map values.
- **OQ-3 — GPT review timing. RESOLVED (Part H.1):** reactive, identical to every surface; no
  bespoke always-on payroll tier. Mix quality moves to a proposed `evaluate_plan` standard
  (Part H.2) — its tolerance/title-count bounds are the remaining values to set.
- **OQ-4 — `payroll_tax_benefits_pct` default.** Must be in [0.12, 0.35]; confirm a policy default
  exists (not found in this pass — route to a named policy value, not a literal).
- **OQ-5 — revenue source** `finmo_revenue` vs `computed_revenue_from_model_input` (B.2).
- **OQ-6 — top-N mix cap** (C.2): the per-NAICS title count is a named policy default; set its value.

---

## Part J — Hard-rule compliance

Spec only — no code. Every codebase claim is file:line grounded; external-data limits (OEWS NAICS-6
suppression) are stated with their real caveats. The dollar path (Part B) is built explicitly to
**avoid** `FTE = required_capacity ÷ productivity` (the Fix #2 wall), converting revenue→FTE through
**wages** instead of **productivity**; the one place productivity must appear (the contract field)
is **reported, never looked up** (Part G). The capacity overwrite that would close a
revenue→FTE→capacity→revenue loop is **removed** on the producer path (Part E). Every value intake
or data cannot supply — intensity class when intake is silent, `capacity_labor_model`,
`wage_positioning_tier`, `payroll_tax_benefits_pct`, the mix cap — is routed to a **named policy
default and/or GPT review**, with the gap stated plainly. No silent hardcodes introduced.
