# Intake Flow Contract (for Cowork)

Written 2026-08-11 at Nick's direction, after CW-025: Cowork asked for a
written model of the intended flow so it can hold runs against a contract
instead of inferring intent from commit messages. **This document is that
contract.** If a run contradicts this document, file it. If a run matches
this document, it is not a bug — even if a value looks odd mid-flight
(the $0 lease that fills two turns later is the design, not a defect).

Source of truth for this doc: `python/api_handlers/intake_consult.py`
(stage specs + THE RECALC) and
`python/client_intake_and_finmo/intake_coherence/` (the gate). If code
and doc disagree, the doc is stale — file THAT (doc drift), and I'll
re-sync it.

---

## 1. The arc

```
ops → market → people → financials (23 staged questions) → coherence gate
    → [wall conversation | lever walk | roadmap]  → intake complete
    → Submit → system run (workbook build)
```

Sections before financials capture via free conversation + GPT
consultants. Financials is a STAGED sequence: one field-cluster at a
time, in a fixed order. The coherence gate runs when the last stage
completes — and re-runs on every turn from then on.

## 2. The financials stage order (fixed)

| # | Stage | Fields written | Kind |
|---|-------|----------------|------|
| 1 | revenue_intro | current_revenue | **proposal** (from ops drivers) |
| 2 | cogs | current_cogs, cogs_total_year1, cogs_percent_of_revenue | **proposal** (fitted band, e.g. "7–11%, I'd start at 9%") |
| 3 | current_payroll | current_payroll, payroll_total_year1 | **proposal** (from the people roster) |
| 4 | marketing | marketing_total_year1, marketing_percent_of_revenue | **proposal** (flat — no band yet; known scope gap, queued) |
| 5 | monthly_rent_expense | monthly_rent_expense | client-captured |
| 6 | future_rent_expected | future_rent_expected | client-captured (boolean) |
| 7 | other_operating_expense | other_operating_expense | client-captured |
| 8 | current_num_employees | current_num_employees | client-captured |
| 9 | current_capex | current_capex | client-captured |
| 10 | initial_assets | initial_assets | client-captured |
| 11 | initial_lease | initial_lease | client-captured |
| 12 | initial_equity | initial_equity | client-captured |
| 13–16 | debt block | total_debt_outstanding, other_monthly_debt_payments, annual_interest_payment, annual_principal_payment | client-captured (volunteer cluster: naming several in one message lands all) |
| 17–20 | balance block | cash_on_hand, ar_balance, ap_balance, inventory_balance | client-captured (volunteer cluster) |
| 21 | cash_strategy | cash_strategy | client-captured (enum) |
| 22 | funding_preference | funding_preference | client-captured (enum) |
| 23 | funding_split_debt_share | funding_split_debt_share | client-captured (only if preference = both) |

**Contract implications:**
- A later-stage field being absent/0 while an earlier stage is active is
  **NOT a bug** — it hasn't been asked yet. (The CW-025 "state note
  claims a recorded field is missing" filing was this: annual principal
  at the total-debt stage is genuinely not-yet-recorded, and the note
  saying "we'll get to that in a moment" was true.)
- A **proposal** stage (1–4) opens with an app-proposed number the
  client confirms or adjusts. The proposed anchor differing from the
  client's actuals is the DESIGN — the invitation to adjust is the
  point. File only if the proposal has no band where one is promised
  (COGS), if acceptance records something other than what was shown, or
  if a correction is refused.
- Within the debt/balance volunteer clusters, a message naming several
  sibling fields lands them all and their stages complete without being
  asked — skipped questions there are correct behavior.

## 3. Field kinds — who owns what

**Client-captured** (stages 5–23 above, plus ops/market/people
answers): the stored value is the client's statement, normalized to the
field's declared basis (annual vs monthly — see field_basis registry).

**Proposals-awaiting-confirmation** (stages 1–4): app-derived openings.
Until confirmed/adjusted they are anchors, not client facts.

**Derived twins — NEVER directly writable.** THE RECALC
(`_sync_financials_consult_persistence_state`) rebuilds these from
their sources on every turn, every edit, every stage advance, and at
run entry. Writing them directly is dead-by-construction (the write is
remapped to its real door or evaporates on the next pass):
- `current_payroll` / `payroll_total_year1` — derived from PEOPLE
  (owner + roster wages + rest_of_team + payroll_adjustment). The ONE
  correction door is the people section (`people.total_team_payroll`,
  `people.rest_of_team_payroll_year1`, `people.owner_pay_monthly`,
  `people.remove_role`). A client saying "my payroll is really $X"
  should produce a people-door write and a "Recorded:" receipt.
- `owner_compensation` — mirror of people owner pay.
- `cogs_total_year1`/`current_cogs` ↔ `cogs_percent_of_revenue` — twin
  family; `cogs_basis` ("ratio" or "dollars") declares which side is
  primary. A proposal accepted as a percent must stamp `ratio`.
- year-1 rollups in financials_year1_json — all derived.

**Coherence artifacts** (`_coherence` in financials_json): gate state —
status, walls, bounds, judged stamps (growth/demand/essentials), round
state. App-internal; never client-stated.

## 4. The completed-financials state (the surface that broke)

When stage 23 completes, financials has NO active stage. From then on
**every turn still routes through the intent router before any response
ships** (CW-025 rank-1, 2026-08-11). The contract for this state:

- A correction ("my payroll is $166,000", "change rest-of-team to
  $93,000") lands through the same doors as mid-stage corrections, gets
  a deterministic "Recorded: …" receipt, THE RECALC folds it, and the
  gate re-evaluates on the corrected numbers **in the same turn**. The
  receipt always precedes any gate verdict (two-beat rule).
- A figure that lands nowhere is DISCLOSED ("You gave me $X and I
  couldn't tell where to record it…"), never silently dropped — on
  every branch, including turns where something else landed.
- Prose claiming a write ("I'll use $X") cannot ship unless the write
  actually landed.
- A question gets an answer; an empty/contentless turn re-shows the
  gate's standing message.

**File immediately** if you ever see: the same gate/wall message
repeated verbatim after a correction; a correction acknowledged nowhere;
a "recorded/I'll use" claim with no matching stored change.

## 5. The coherence gate

Runs at financials completion and on every later turn. Two-tier verdict
(fence at gate entry, judged multiple during a walk). Outcomes:
- **Wall** — a structural ceiling fails (e.g. payroll share vs the
  labor-intensive lender ceiling). The wall names both exits in dollars
  (revenue to clear, payroll to clear). Cause-aware: a staffed real
  team is never met with "cut pay" — revenue is the honest path.
- **Walk** — lever rounds (pricing, volume, costs, …) with options
  bounded by judged market evidence. Every option names its consequence.
- **Roadmap** — only when no realistic configuration clears: distance
  framing, ranked paths, invitation close. A mid-walk collapse triggers
  a hold-and-confirm first (corner-collapse tripwire), never an abrupt
  verdict flip. The client's saved numbers are kept verbatim; nothing
  is faked to force a pass.

Judged stamps (growth, demand, price bounds, essentials) are authored
once at the gate and reused; they invalidate together when the
identity-level inputs change. `price_market_facts` (the dollar price
ceiling) survives re-authoring while the market slice is unchanged —
acceptance of an option NEVER moves the ceiling.

## 6. Run entry (Submit → workbook)

At system-run entry the app runs the SAME Recalc over the stored
sections and persists the result before the grid build reads anything
(run-entry Recalc). Consequences for testing:
- A coherent draft recomputes to the numbers it already has — byte-equal
  workbook on rerun.
- An old/dormant draft with stale derived values is healed at entry —
  differences between at-rest stored values and workbook values on
  DERIVED fields are the design (the workbook is the truth), not a bug.
  A mismatch on a CLIENT-CAPTURED field IS a bug — file it.
- Reruns go through POST without a planning_run_id (a rerun names a NEW
  run).

## 7. Known open items (do not re-file)

- Marketing proposal has no fitted band (design gap, queued).
- Owner wage may carry a cents-level monthly-rounding artifact
  (38,000.04) — known, parked.
- Headcount is asked in financials while payroll dollars live in people
  — consolidation queued for a ruling, current split is intentional.
- People-section rest-of-team enumeration (a named person inside a
  stated crew total) — CW-025 rank-2, in progress.
- `cogs_basis` re-tag after ratio-stamped acceptance — CW-025 rank-2,
  in progress.
- `baseline_marketing` contamination — CW-025 rank-2, in progress.
