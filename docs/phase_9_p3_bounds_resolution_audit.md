# Phase 9 P3 — `_driver_bounds_for_target` audit

**Audit date:** 2026-05-10
**Function under review:** `_driver_bounds_for_target` in
[`python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py`](../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L337)
**Realism config source of truth:**
[`python/client_intake_and_finmo/post_intake_realism/lookup.py`](../python/client_intake_and_finmo/post_intake_realism/lookup.py)
**No code changes in this audit.**

---

## Bottom line

**Case (b) — architecture INTENDS to have these levers (per the realism
config you set up in Phase 1) but the implementation has a hardcoded
mismatch.** The pre-flight diagnostic was honest — it reported what the
function actually returns. The function does not return entries for
`expenses::Payroll`, `revenue::Unit Price`, `revenue::Capacity`, or
`revenue::Utilization` despite the docstring claiming branches for them.

Specifically:

- The function's docstring describes intended behavior for
  `revenue::Unit Price`, `revenue::Capacity`, `revenue::Utilization`
  (±50% bounds) and `quarter_currency` levers like `expenses::Payroll`
  and `expenses::Lease`.
- The function's body has **none of those branches** — only hardcoded
  `expenses::*` (percent_of_revenue) and `balance_sheet::*` branches.
- The Phase 1 realism config DOES list those revenue/payroll levers as
  `primary_levers` for the relevant targets. The solver is silently
  ignoring the config the realism gate respects.

Pre-flight diagnostic was NOT filtering. It reported the function's
actual output. The gap is in the function itself.

---

## 1. Actual output of `_driver_bounds_for_target` for Sunny (NAICS 311811)

Direct invocation, dumped verbatim:

### `gross_margin_percent` — 1 lever returned

| Lever | Kind | Bounds |
|---|---|---|
| `expenses::Cost of Goods Sold` | percent_of_revenue | [0.6335, 0.7952] |

### `ebitda_margin` — 4 levers returned

| Lever | Kind | Bounds |
|---|---|---|
| `expenses::Cost of Goods Sold` | percent_of_revenue | [0.6335, 0.7952] |
| `expenses::Marketing` | percent_of_revenue | [0.1010, 0.2641] |
| `expenses::Research & Development` | percent_of_revenue | [0.0062, 0.0226] |
| `expenses::General & Administrative` | percent_of_revenue | [0.1010, 0.2641] |

### `current_assets_minus_cash` — 3 levers returned

| Lever | Kind | Bounds |
|---|---|---|
| `balance_sheet::Accounts Receivable Days` | days | [24.29, 41.72] |
| `balance_sheet::Inventory Days` | days | [50.91, 111.79] |
| `balance_sheet::Prepaid Expenses (% of Revenue)` | percent_of_revenue | [0.0091, 0.0283] |

### `current_liabilities_to_revenue` — 2 levers returned

| Lever | Kind | Bounds |
|---|---|---|
| `balance_sheet::Accounts Payable Days` | days | [24.27, 67.13] |
| `balance_sheet::Deferred Revenue (% of Revenue)` | percent_of_revenue | [0.0037, 0.0149] |

---

## 2. What the realism config says SHOULD be the drivers

From `post_intake_finalize_realism_check_lookup` (the same config the
realism gate uses to evaluate hard_fails):

| Target | `primary_levers` | `secondary_levers` |
|---|---|---|
| `gross_margin_percent` | `cogs`, `revenue::Unit Price` | (none) |
| `ebitda_margin` | `cogs`, `Marketing`, `G&A`, `Payroll`, `Unit Price`, `Utilization` | `Capacity` |
| `current_assets_minus_cash` | `AR Days`, `Inventory Days`, `Prepaid %` | (none) |
| `current_liabilities_to_revenue` | `AP Days`, `Deferred %` | (none) |

---

## 3. Diff: config-promised vs function-wired

| Target | In config but NOT wired | In function but NOT in config |
|---|---|---|
| `gross_margin_percent` | **`revenue::Unit Price`** | (none) |
| `ebitda_margin` | **`expenses::Payroll`, `revenue::Unit Price`, `revenue::Utilization`, `revenue::Capacity`** | `expenses::Research & Development` (extraneous) |
| `current_assets_minus_cash` | (none — matches) | (none) |
| `current_liabilities_to_revenue` | (none — matches) | (none) |

**Net:**
- Gross margin target loses `revenue::Unit Price` slack.
- Ebitda margin target loses Payroll, Unit Price, Utilization, Capacity
  slack — these are precisely the levers Sunny needs to lift EBITDA from
  -40% (cogs% / marketing% / sga% are already at or below their lower
  bounds, so ebitda lift requires either revenue uplift or payroll
  cut, both outside the wired driver list).
- R&D is wired for ebitda but NOT in the config — Sunny donut shop has
  R&D = 0 already, so it's a no-op for Sunny but still an unnecessary
  divergence from the source of truth.

---

## 4. Why is the function wired this way?

`_driver_bounds_for_target` was written with a **hardcoded if/elif tree
keyed on target_metric** ([restoration_loop.py:380-424](../python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L380-L424)).
Each branch enumerates levers explicitly. The docstring promises
extra branches that the body never implements.

There's no `if "Payroll" in primary_levers` style read from the config.
The function does not read `primary_levers` from the realism lookup at
all. So the config has zero influence on what the solver attempts.

This is exactly the kind of hardcoded mirror that drifts away from
truth as soon as the source-of-truth (realism lookup row) changes.
Phase 1 set the realism config; this function never picked it up.

---

## 5. Why did pre-flight not surface the gap?

Pre-flight invoked `_driver_bounds_for_target` and reported each
returned lever. It was a faithful diagnostic of the function's actual
output. It did not cross-check against the realism config's
`primary_levers`. The diagnostic was correct about what the solver
operates on; it just did not flag that the solver operates on a
**subset** of what the realism config declares.

A hardening for future pre-flights: also read the realism row's
`primary_levers` and diff against the function's output. Would have
caught this gap before the user had to ask.

---

## 6. Implications for Sunny E2E (if run as-is)

With the function-wired driver list (no Payroll, no Price, no
Utilization, no Capacity for ebitda):

1. Sunny's Q1 ebitda = -0.40. The solver must lift to ≥ 0 by Q11.
2. Sunny's Q1 cogs% = 0.50, **already below cohort lower bound 0.633**.
   Driver_state.slack_in_direction("lower") = 0 immediately. cogs%
   contributes zero slack to lift ebitda.
3. Sunny's Q1 marketing% ≈ 0.06, **already below cohort lower bound
   0.10**. Same zero slack.
4. Sunny's Q1 r_and_d% = 0 (donut shop), bound [0.006, 0.023] — zero
   slack to lower (already at zero), can only raise (which would HURT
   ebitda).
5. Sunny's Q1 sga% — need to check; if also below 0.10, no slack.
6. Without Payroll (largest cost line for Sunny — $183k/year), without
   Unit Price (biggest revenue lift lever), the solver has nothing to
   work with.

**Predicted outcome with current wiring:** ebitda solver returns
BOUND_PINNED on outer pass 1, drivers_at_bounds_summary lists every
expense lever pinned at lower bound, restoration loop returns
EXHAUSTED with empty operating-driver authority. Acceptance gate
fails on `realism_gate_no_hard_fail_violations` (ebitda hard_fail
across Q1-Q11) and on `viability_timeline_landed`
(`ebitda_positive_by_q11` doctrine fails).

---

## 7. Recommended fix (NOT applied — this is diagnostic only)

Replace the hardcoded if/elif with a read from the realism lookup row:

```python
def _driver_bounds_for_target(*, target_metric, business_naics_6):
    row = post_intake_finalize_realism_check_for_metric(target_metric)
    primary = list((row or {}).get("primary_levers") or [])
    bounds = {}
    for lever_id in primary:
        if lever_id in _CASH_PASS_OWNED_LEVER_IDS:
            continue   # cash strategy owns
        # Per-lever-kind dispatch:
        if lever_id.startswith("expenses::") and lever_id != "expenses::Payroll" and lever_id != "expenses::Lease":
            band = _band_for_lever_pct(lever_id)   # cogs%, marketing%, etc.
        elif lever_id == "expenses::Payroll":
            band = _band_for_payroll(business_naics_6, current_revenue_q1)
        elif lever_id.startswith("revenue::"):
            band = _band_for_revenue_lever(lever_id, current_value)  # ±50%
        elif lever_id.startswith("balance_sheet::") and "Days" in lever_id:
            band = _band_for_days(lever_id)
        elif lever_id.startswith("balance_sheet::") and "%" in lever_id:
            band = _band_for_pct(lever_id)
        if band is not None:
            bounds[lever_id] = DriverBound(...)
    return bounds
```

This makes the realism config the single source of truth — what the
gate evaluates against = what the solver tries to land. No more
silent drift.

The new lever kinds (`revenue::Unit Price/Capacity/Utilization`,
`expenses::Payroll`) will also need:
- Sensitivity coefficients in `_sensitivity_coefficient`
  ([target_solver.py](../python/client_intake_and_finmo/post_intake_target_solver/target_solver.py))
- `_driver_kind_for_lever` already returns sensible kinds; verify
  `revenue_unit` / `quarter_currency` paths are exercised.

The recommended fix is a small structural change, not a rewrite. But
it IS a code change, so deferring per your "diagnostic only"
instruction.

---

## 8. What the user needs to decide

The diagnostic resolves your case-classification:

- **NOT (a)** — pre-flight was correct; the function genuinely
  excludes these levers.
- **It IS (b)** — small fix to read from realism config. ~50-80 lines
  including the missing sensitivity coefficients for revenue + payroll
  levers in `target_solver.py`.
- **NOT (c)** — the architecture's source of truth (realism lookup
  row) already declares these levers. Only the solver-side reader is
  missing.

Standing by for direction on whether to:
1. Apply the case (b) fix and re-run Sunny, or
2. Run Sunny as-is on the current wiring (with the predicted
   exhaustion), or
3. Other direction.
