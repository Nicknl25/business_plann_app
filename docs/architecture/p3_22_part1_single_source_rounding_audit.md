# Phase 9 P3.22 Part 1 — Single-Source Rounding Audit

**Outcome:** 2 SINGLE-SOURCEABLE sites identified (which are actually
the same check duplicated across two files with different tolerances).
3 LEGITIMATE ESCAPE clusters documented. ~40 other tolerance/comparison
sites confirmed out-of-scope (solver convergence, integer-valued
detection, input normalization, etc.).

## Method

Grepped `python/client_intake_and_finmo` for:
- `abs(...) > N`, `abs(...) < N` with literal numeric thresholds
- `math.isclose`
- `tolerance = ...` constants
- Comments mentioning "tolerance," "coherence," "noise" near comparison logic
- Any FailFast/assertion comparing two computed quantities

Classified each hit by asking: **does this site reconcile two
parallel computations of the same conceptual quantity, or is it
something else (input validation, invariant check, solver convergence,
change detection)?**

Only parallel-computation reconciliation sites are in scope per the
directive.  Other tolerance uses are documented for completeness but
not classified as P3.22 candidates.

---

## SECTION A — In-scope Pattern 1 sites

### Site #1 — finmo_bridge.py:586 (Stage 5 iter 1 fix)

- **File:line:** [finmo_bridge.py:586](python/client_intake_and_finmo/finmo_bridge.py#L586)
- **Function:** `_enforce_revenue_driver_formula_contract`
- **Tolerance:** `abs(delta_float) > 1.0` (i.e., $1)
- **Comparison:**
  - Path A: `finmo_revenue = float(_safe_float(row.get("revenue")))` — read from FINMO core's `quarter_rows[i].revenue`.
  - Path B: `driver_revenue = float(driver_revenue_series[idx - 1])` — `_revenue_live_series_from_model_input` at [finmo_bridge.py:1781](python/client_intake_and_finmo/finmo_bridge.py#L1781) computes `sum(Capacity * Unit Price * Utilization)` per product, then `round(value, 6)` at end.
- **Conceptual quantity:** per-quarter revenue.
- **Divergence source:** float arithmetic non-associativity.  Both paths sum the same products of three drivers per quarter; one computes inside FINMO core (engine-specific multiplication / accumulation order), the other in the driver-side helper.  Mathematically identical; bit-wise can differ by sub-cent at the rounding boundary.
- **History:** Stage 5 iter 1 (commit `afe5c88`) added the $1 tolerance after the ExpressLogix E2E hit Q1 with `finmo=1673073` vs `driver=1673074` (the int-rounded values straddled the boundary; the underlying float delta was `<$0.5`).

### Site #2 — fail_fast.py:1371 (the duplicate)

- **File:line:** [fail_fast/post_intake_fail_fast/fail_fast.py:1371](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1371)
- **Function:** inside `assert_post_intake_revenue_driver_formula` (the broader `post_intake_revenue_driver_*` assertion suite)
- **Tolerance:** `abs(expected_raw - actual_raw) > _REVENUE_FORMULA_TOLERANCE` where `_REVENUE_FORMULA_TOLERANCE = 0.015` (i.e., 1.5 cents)
- **Comparison:**
  - Path A: `actual_raw = float(actual_revenue_by_q.get(quarter))` — read from FINMO `quarter_rows[i].revenue` (same source as Site #1 Path A).
  - Path B: `expected_raw = float(computed_revenue_by_q.get(quarter))` — accumulated at [fail_fast.py:1340-1352](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1340-L1352) as `sum(Capacity * Unit Price * Utilization)` per product per quarter.  Same arithmetic as Site #1 Path B but performed inline rather than via `_revenue_live_series_from_model_input`.
- **Conceptual quantity:** per-quarter revenue.
- **Divergence source:** same as Site #1 — float arithmetic non-associativity.
- **History:** pre-existing.  The comment at [fail_fast.py:1357-1364](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1357-L1364) explicitly documents the float-rounding-mode issue and chose 1.5¢ as the threshold.

### The Site #1 / Site #2 relationship

Sites #1 and #2 are **the same conceptual contract check** —
"FINMO revenue must equal the driver-formula revenue per quarter" —
implemented in two places with different tolerances ($1.0 vs $0.015)
and slightly different driver-accumulation code (one calls a helper,
the other inlines).  This is a textbook doctrine §7 anti-pattern
("Two parallel implementations of the same conceptual value") within
the contract-check infrastructure itself.

The doctrine §4 Flavor 1 prescription applies: one canonical
implementation, other callers reference it directly.

---

## SECTION B — Legitimate escapes (Mirror Flavor 4 invariant checks)

These sites use tolerance but are NOT parallel-computation
reconciliation.  They check business invariants over a single
computed state.  Mirror Flavor 4 explicitly allows this.  Per the
directive: "no refactoring sites classified as LEGITIMATE ESCAPE."

### Legitimate Escape Cluster L1 — Accounting equation balance

- **File:line:** [finmo_bridge.py:805](python/client_intake_and_finmo/finmo_bridge.py#L805)
- **Check:** `abs(value) <= tolerance` where `tolerance = 1.0` and `value = accounting_equation_check` (which is `total_assets - total_liabilities_and_equity` computed inside FINMO core).
- **Why legitimate:** The accounting equation is a business invariant, not a parallel computation.  FINMO core assembles `total_assets` by summing one set of line items and `total_liabilities_and_equity` by summing a different set; the check confirms FINMO didn't drop a line item or double-count.  This is the canonical Mirror Flavor 4 invariant check.  Tolerance absorbs sub-dollar float-summation noise across ~20 line items per quarter.

### Legitimate Escape Cluster L2 — Mapping formula contract check

- **File:line:** [fail_fast.py:1130](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1130), [:1145](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1145)
- **Check:** `abs(actual - expected) > MAPPING_FORMULA_INT_TOLERANCE` where the constant is defined at [finmo_model.py:142](python/financial_model_engine/finmo_model.py#L142) as `MAPPING_FORMULA_INT_TOLERANCE: int = 1`.
- **Two formula keys checked:**
  - `finmo_equals_revenue_times_model_input_ratio`: actual finmo_field == revenue × model_input_ratio.
  - `finmo_equals_model_input_value`: actual finmo_field == model_input value.
- **Why legitimate (borderline):** This IS technically two-path reconciliation, but the two paths are **different by design** — one is "what FINMO computed for this field" and the other is "what the SQL mapping formula says it should be."  The check's purpose is to assert that the writer correctly applied the mapping.  Both paths go through `compute_model_input_value(x) = int(round(float(x)))`, which makes the comparison int-rounding-boundary-sensitive.  Single-sourcing would require either making FINMO read from the mapping formula (collapsing both paths into a single computation, which defeats the contract-check purpose) or removing the contract entirely.  **Documented as Mirror Flavor 4 invariant check; tolerance stays.**

### Legitimate Escape Cluster L3 — Capital lease invariant checks (8 sites)

- **Constant:** `CAPITAL_LEASE_RECONCILE_TOLERANCE = 1` at [post_intake_capital_lease/schedule.py:32](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L32) ("whole-dollar tolerance per spec").
- **Sites:**
  - [schedule.py:295](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L295) — Q0 obligation == intake seed.
  - [schedule.py:305](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L305) — Q1 ROU opening == intake seed.
  - [schedule.py:326](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L326) — closing balance == max(0, opening - principal).
  - [schedule.py:338](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L338) — ROU closing == expected straight-line depreciation.
  - [schedule.py:350](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L350) — interest == opening × rate.
  - [schedule.py:470](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L470) — payload row == computed row.
  - [schedule.py:564](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L564) — interest_total == debt_interest + lease_interest (component sum).
  - [schedule.py:600](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L600) — depreciation_total == ppe_dep + lease_dep (component sum).
  - [schedule.py:640](python/client_intake_and_finmo/post_intake_capital_lease/schedule.py#L640) — FCF == expected components (component sum).
- **Why legitimate:** All are invariant checks over a single canonical computation — either "does this row obey the amortization formula?" (per-quarter math) or "does this sum-of-parts match the whole?" (component decomposition).  None are two-different-paths-computing-the-same-quantity.  Mirror Flavor 4 by construction.  Tolerance handles int-rounding noise from `_safe_int(x) = int(round(float(x)))`.

---

## SECTION C — Out of scope (not parallel-computation reconciliation)

Documented for completeness; will not be classified under P3.22:

**Solver convergence tolerances** (`numeric_solver.py` ~20 sites):
`1e-9` tolerances on solver iteration steps, anchor convergence checks,
algebraic-within-tolerance flags.  These bound numerical optimization
iteration; they do not reconcile parallel computations.

**Integer-valued detection** (`fact_templates.py`, `financials_year1.py`,
`people_roles.py`, `path_engine.py`):
`abs(num - round(num)) < 1e-9` patterns checking "is this float
effectively an integer?" for display formatting decisions.  Not
reconciliation.

**Input normalization** (`post_intake_contracts/runner.py:122`):
`_safe_ratio` detects whether `5` means `5%` (ratio = 0.05) or `0.5`
(ratio = 0.5) using `if abs(parsed) > 1.0 and abs(parsed) <= 100.0`.
Input transformation; not reconciliation.

**Change detection** (`post_intake_cash/runner.py:4477-4484`):
`abs(final_X - first_X) > 1.0` patterns detecting whether the cash
strategy materially changed values vs the pre-cash baseline.  This
compares two snapshots of the SAME state at two POINTS IN TIME — not
two parallel computations of the same quantity.

**Input validation** (`finmo_bridge.py:1638`):
`abs(useful_life - int(useful_life)) > 0.000001` validates that
`useful_life_years` resolves to a positive whole number of quarters.
Input validation; not reconciliation.

---

## SECTION D — Refactor proposals for SINGLE-SOURCEABLE sites

### Proposal P1 (LOW COST) — Eliminate the Site #1 / Site #2 duplicate

**Scope:** Consolidate Sites #1 and #2 into a single canonical
check.  Remove the inline driver accumulation at fail_fast.py:1340-
1352; have fail_fast.py call `_revenue_live_series_from_model_input`
directly (the same helper finmo_bridge.py:566 uses).  Pick one
tolerance (recommend $0.015 — the tighter of the two; it represents
true float noise, while $1 was Stage 5 iter 1's "match the
accounting-equation convention" choice that turned out to be more
relaxed than necessary).  Reading paths consume from the single
helper.

**Source-of-truth choice:** `_revenue_live_series_from_model_input`
at [finmo_bridge.py:1781](python/client_intake_and_finmo/finmo_bridge.py#L1781) becomes the canonical
driver-formula revenue.  Both contract-check call sites (finmo_bridge
and fail_fast) read from it.  FINMO core's `quarter_rows[i].revenue`
remains the canonical RESULT — the contract check confirms the two
agree.

**Refactor shape:**
1. Delete the inline driver accumulation at fail_fast.py:1340-1352.
2. Replace with `computed_revenue_by_q = {q: v for q, v in enumerate(_revenue_live_series_from_model_input(model_input_json, live_count=horizon), start=1)}` (or equivalent).
3. Pick one tolerance constant in a shared module (recommend `_REVENUE_FORMULA_TOLERANCE = 0.015` exported from finmo_bridge.py).  Both call sites import it.
4. Remove `MAPPING_FORMULA_INT_TOLERANCE` import sharing if the consolidation absorbs it (it doesn't — that's a different check at Site L2).

**Estimated LOC:** ~30 LOC removed + ~10 LOC added (single import + single constant + one helper call) = net **~20 LOC saved**.

**Risk:** ZERO behavior change for healthy runs.  The tighter $0.015 tolerance means the fail_fast.py site keeps its current behavior; the finmo_bridge.py site becomes slightly stricter than today's $1 (a marginal-case run that passed under $1 but fails under $0.015 would surface — but such a run already failed the fail_fast.py check, so the divergence detection is unchanged).

**Test approach:**
- Regression test: the consolidated check fires identically to both pre-consolidation sites for the same input.
- Behavior-preservation test: run the Stage 5 ExpressLogix scenario (offline equivalent — unit-level reproduction of the Q1 case that triggered the iter 1 fix) and confirm no false positives.
- Source-shape test: confirm no other site computes `sum(Capacity * Unit Price * Utilization)` inline; all go through the helper.

### Proposal P2 (HIGH COST, NOT RECOMMENDED IN THIS ITER) — Make FINMO core use the helper as its revenue source

**Scope:** Refactor `calculate_finmo_model` (in `financial_model_engine/finmo_model.py`) so its per-quarter revenue computation calls `_revenue_live_series_from_model_input` (or equivalent shared helper) instead of computing revenue internally.  This would make the contract check tautologically true, allowing its removal entirely.

**Estimated LOC:** ~50-100 LOC in finmo_model.py + extensive regression tests across the FINMO engine.  Cross-module coupling (finmo_model lives in `financial_model_engine`, the helper lives in `client_intake_and_finmo/finmo_bridge`) means either moving the helper or accepting a back-reference.

**Risk:** MEDIUM-HIGH.  FINMO core is the canonical financial engine; any change to its revenue accumulation order risks behavior changes for healthy runs.  Would require full Phase 9 regression + E2E to confirm zero drift.

**Recommendation:** Defer.  Proposal P1 already eliminates the duplicate and tightens the tolerance to match true float noise.  The remaining "two paths compute revenue" pattern then becomes a single Mirror Flavor 4 invariant check (one path computes, one verifies), which is doctrinally acceptable.

---

## SECTION E — Recommendation summary

| Site | Classification | Recommendation |
|---|---|---|
| #1 finmo_bridge.py:586 (Stage 5 iter 1) | SINGLE-SOURCEABLE (duplicate) | Consolidate per Proposal P1 |
| #2 fail_fast.py:1371 (pre-existing) | SINGLE-SOURCEABLE (duplicate) | Consolidate per Proposal P1 |
| L1 finmo_bridge.py:805 (accounting eq.) | LEGITIMATE ESCAPE | Keep; document as Mirror Flavor 4 |
| L2 fail_fast.py:1130, 1145 (mapping contract) | LEGITIMATE ESCAPE | Keep; document as Mirror Flavor 4 |
| L3 capital_lease/schedule.py (8 sites) | LEGITIMATE ESCAPE | Keep; document as Mirror Flavor 4 |

**Total in-scope SINGLE-SOURCEABLE sites: 2 (which is 1 logical
check duplicated).**

**Total LEGITIMATE ESCAPE sites: 11 (1 accounting equation + 2
mapping formula keys + 8 capital lease invariants).**

**Recommended Part 2 scope:** Proposal P1 only.  Single commit
collapsing Site #1 and Site #2 into one canonical check at one
tolerance.  Estimated ~30 LOC change + regression tests.  Zero
behavior change for healthy runs.

**Out of recommended Part 2 scope:** Proposal P2 (FINMO core
refactor).  High cost relative to benefit; current P1 consolidation
gets to Mirror Flavor 4 cleanly.

## Compliance with directive's escape clauses

Per the directive:

> "If a site looks single-sourceable but the refactor would require
> restructuring two major modules, note that as 'single-sourceable
> but high-cost' — user decides whether to proceed."

Proposal P2 is exactly that case.  Flagged but not recommended for
Part 2; user direction needed if it's wanted.

> "no refactoring sites classified as LEGITIMATE ESCAPE"

Confirmed.  Sites L1, L2, L3 are documented Mirror Flavor 4
invariant checks; this audit recommends no refactor against them.

> "no changing the tolerance value at any site (the doctrine
> position is: eliminate the tolerance via single-sourcing, OR
> accept the tolerance with explicit Mirror Flavor 4
> classification — not 'adjust the tolerance to make a problem
> go away')"

Proposal P1 ELIMINATES the redundant duplicate check.  The single
remaining check after consolidation uses $0.015 — that is NOT a
tolerance loosening (current state has the same $0.015 check at
fail_fast.py firing in parallel with the $1 check at finmo_bridge.py);
the consolidation removes the redundant $1 check entirely.  Net
effect: the codebase enforces the tighter tolerance everywhere
(matches the existing pre-existing fail_fast precedent), not the
looser one.

## Hard stop conditions assessment

- > 10 tolerance sites needing audit: **NO.**  2 in-scope sites; 11 documented legitimate escapes; ~40 out-of-scope sites.
- Site classification requires deep math analysis not resolvable from code: **NO.**  Float non-associativity is well-understood; all classifications are confidently made from code reading + comments + existing tolerance precedents.

No hard stops triggered.  Audit complete and ready for user Part 2 direction.
