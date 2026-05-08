# Audit: `financials_year1_json` consumers

Triggered after the Phase 6 Step 9 structural feasibility check was found
to use the operator's Year-1 ramped projection as the "upper bound" for
the feasibility comparison. This document classifies every post-intake
read of `financials_year1_json` (and its subfields — particularly
`company_revenue_total_year1`, `revenue_total_year1`, `lobs`,
`payroll_year_one`) as one of:

- **Advisory** — used to inform a GPT decision or planning narrative;
  the consultant chooses whether/how to act on it. Acceptable.
- **Sanity-check** — compared against another value to flag conflicts or
  filter cohorts; not used as the authoritative value any derived
  calculation depends on. Acceptable.
- **Authoritative ground truth** — the value that downstream calculations
  consume directly to derive other quantities (revenue ceilings, capacity
  bounds, balance-sheet days, planning-mode classification). When the
  operator's Year-1 projection is a ramped early-stage number, treating
  it as authoritative produces wrong answers for any business that
  isn't already at steady state. **Bug.**

Only post-intake derivation paths are listed. Construction / persistence
paths in `api_handlers/intake_consult.py` and `intake_consult_draft.py`
that build, store, or render `financials_year1_json` are out of scope —
they're upstream of the question.

## Authoritative ground truth (BUG)

| File:line | Read | How used |
|---|---|---|
| [post_intake_solver/structural_feasibility_check.py:104-109](python/client_intake_and_finmo/post_intake_solver/structural_feasibility_check.py#L104-L109) | `company_revenue_total_year1` / `revenue_total_year1` | Priority 1 source for `_upper_bound_annual_revenue`. The function name promises an upper bound; the priority order delivers the operator's projection. The capacity-driven formula (priority 2) only fires when the projection is absent. **Already diagnosed; Fix 1/2 land here.** |
| [post_intake_balance_sheet/contextual_seed.py:302-309](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L302-L309) | `company_revenue_total_year1` / `revenue_total_year1` | `_proposer_intake_implied_seed` uses Year-1 revenue as the divisor for AR-days / AP-days / inventory-days computation: `quarter_revenue = revenue_year_one / 4`, then `days = balance / quarter_revenue × 90`. For ramping businesses, the small Year-1 denominator inflates implied days. The seed becomes the planning anchor for the balance-sheet lever. |
| [post_intake_solver/consultant_conflict_adjudication.py:109-128](python/client_intake_and_finmo/post_intake_solver/consultant_conflict_adjudication.py#L109-L128) | `company_revenue_total_year1` / `revenue_total_year1` | `_intake_implied_for_lever` — same pattern as contextual_seed. Computes "intake implied" AR / AP / inventory days from `balance / (year1_revenue/4) × 90`. The consultant compares this to the calibrated band. Wrong denominator → wrong implied value → wrong adjudication. |
| [quarter_grid.py:160-184](python/client_intake_and_finmo/quarter_grid.py#L160-L184) | `company_revenue_total_year1`, `company_payroll_total_year1`, `payroll_total_year1`, `marketing_total_year1`, `cogs_total_year1` | `_build_baseline_financial_summary` — used as the FALLBACK input to `determine_planning_mode` when FINMO doesn't yet have data. For first-pass planning-mode classification, this fallback is THE input. Year-1 projection drives the `turnaround` / `normalize` / `rebalance` decision. For Sunny: $93K projection vs $163K cost → diagnosed as turnaround. With capacity-driven upper bound, the diagnosis could differ. |
| [finmo_bridge.py:3034-3041](python/client_intake_and_finmo/finmo_bridge.py#L3034-L3041) | `company_revenue_total_year1` / `revenue_total_year1` | `revenue_total_year1` is then used at line 3041 as the divisor in `_cogs_ratio_from_financials` AND at line 3075 as `business_profile.target_annual_revenue`. The COGS ratio fallback only fires when intake didn't supply `cogs_percent_of_revenue` (Sunny does, so safe for Sunny). The cohort `target_annual_revenue` IS authoritative — see next row. |
| [finmo_bridge.py:3075](python/client_intake_and_finmo/finmo_bridge.py#L3075) | `revenue_total_year1` | `business_profile.target_annual_revenue` is consumed by the cohort-band resolver (`cohort_band_resolver.map_revenue_to_cap_categories`). Cohort selection determines which percentile band the lever calibration draws from. For a ramping business, the Year-1 projection buckets it into a smaller-cap cohort than its actual capacity warrants — bands then come back too tight. |
| [post_intake_solver/orchestrator.py:392-404](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L392-L404) | `company_revenue_total_year1`, `revenue_total_year1`, `current_revenue` | Same pattern as `finmo_bridge.py:3075` — builds `business_profile.target_annual_revenue` for the cohort match. Operator's Year-1 projection feeds the cohort-cap-category bucket directly. |

## Sanity-check (acceptable)

| File:line | Read | How used |
|---|---|---|
| [api_handlers/intake_consult.py:5138-5160](python/api_handlers/intake_consult.py#L5138-L5160) | `_year1_drivers_conflict` (helper used by `post_intake_initial_grid/runner.py:489`) | Compares incoming year1 against base_year1 (rebuilt from current intake state). On conflict, replaces with base_year1 — a re-derivation safety check, not a downstream-calculation input. |

## Advisory context (acceptable)

| File:line | Read | How used |
|---|---|---|
| [post_intake_headcount/schedule.py:2042-2050](python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2042-L2050) | `company_revenue_total_year1` / `revenue_total_year1` | Fed as `financial_context.annual_revenue` to the GPT payroll consultant. GPT uses it as planning context to choose headcount; payroll schedule output is what becomes authoritative downstream. **However**: see "separate concern" below — the schedule then anchors on operator's `current_payroll`, which is its own bug. |
| [post_intake_contracts/runner.py:1476-1483](python/client_intake_and_finmo/post_intake_contracts/runner.py#L1476-L1483) | `company_revenue_total_year1` / `revenue_total_year1` | Context for GPT R&D applicability decision. Year-1 revenue is one of several signals; GPT outputs r_and_d_enabled=true/false. |
| [post_intake_contracts/runner.py:1644-1654](python/client_intake_and_finmo/post_intake_contracts/runner.py#L1644-L1654) | `company_revenue_total_year1` / `revenue_total_year1` | Context for GPT cash-strategy decision. Advisory. |
| [post_intake_contracts/runner.py:1932-1940](python/client_intake_and_finmo/post_intake_contracts/runner.py#L1932-L1940) | `company_revenue_total_year1` / `revenue_total_year1` | Context for another GPT contract call. Advisory. |
| [post_intake_convergence/runtime.py:491-495, 767-768](python/client_intake_and_finmo/post_intake_convergence/runtime.py#L491-L495) | `first_year_revenue` (computed from FINMO actual quarter values, NOT directly from financials_year1_json) | Financial-story narrative builder — descriptive output for the report, not an input to any calculation. This one isn't actually a financials_year1_json consumer; included for completeness. |

## Construction / persistence (out of scope)

`api_handlers/intake_consult.py` (~80 references) and
`api_handlers/shared_context.py`, `client_intake_and_finmo/intake_consult_draft.py`,
`client_intake_and_finmo/financials_year1.py`, `financials_consultant.py` —
these BUILD `financials_year1_json` from operator input or persist/read
it for the intake form. They're upstream of the "treats this as
authoritative for downstream" question.

`financial_model_engine/run_engine_replay.py` — replay path; passes
year1 forward unchanged.

`post_intake_runtime_validation/initialize_post_intake.py` — schema
init only.

## Separate concern flagged (don't fix yet)

**`post_intake_headcount/schedule.py` propagates today's
`current_payroll` as the year-1 baseline across all 20 quarters with
only inflation adjustment.** Sunny Glaze evidence:

```
expenses::Payroll values q0-q20 (Sunny Glaze, draft ac0428cf):
  q0:  $45,830  (today, current_payroll/4)
  q1-q4:  $40,829  (slight discount from q0)
  q5-q8:  $42,055  (~3% raise)
  q9-q12: $43,315
  q13-q16: $44,616
  q17-q20: $45,952
```

This anchors fixed-cost forecasting on whatever staffing the operator
has TODAY — not on what staffing would be appropriate for the modeled
revenue capacity. For Sunny (single-shop donut business with operator-
stated 4 roles totaling $183K/yr), the schedule treats today's
over-staffing as the structural lower-bound across all 20 quarters.
This inflates the cost side of the structural feasibility check and
of every downstream margin / EBITDA computation.

The right behavior: the schedule should size staffing to the modeled
revenue capacity (capacity × price × utilization × productivity →
implied headcount), not anchor on today's over-staffing. Today's
over-staffing is operator context (just like Year-1 revenue
projection), not authoritative for forecast staffing.

Filed as a separate audit / fix; deferred per directive — the structural
feasibility fix is ahead of this on the order of operations.

## Summary

7 authoritative-ground-truth call sites, 1 sanity-check, 4 advisory.

The 7 authoritative sites cluster into three architectural anti-patterns:

1. **Year-1 revenue as upper bound / capacity ceiling**
   (structural_feasibility_check). The directive's Fix 1/2 lands here.

2. **Year-1 revenue as the divisor for derived ratios** (balance-sheet
   days in `contextual_seed.py` and `consultant_conflict_adjudication.py`,
   COGS ratio fallback in `finmo_bridge.py`). For ramping businesses,
   the small Year-1 denominator distorts the derived ratio.

3. **Year-1 revenue as the cohort selection key** (`finmo_bridge.py`,
   `orchestrator.py`). Buckets the business into a smaller-cap cohort
   than its actual capacity warrants when the operator under-projects
   Year-1.

The same architectural fix applies to all three: replace operator's
Year-1 projection with capacity-driven upper bound (or a horizon-
sensitive equivalent) wherever the value is consumed as authoritative
for downstream derivation.
