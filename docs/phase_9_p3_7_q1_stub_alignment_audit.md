# Phase 9 P3.7 — Q1 vs Stub alignment audit

**Date:** 2026-05-10
**Subject:** Three writers (target solver, balance-sheet contextual seed, GPT exhaustion handler) and where each lands in the `values[]` array.
**Investigation only — no code changes.**

The user's architectural assertion:
- **Stub (`values[0]`) = intake snapshot.** Operator's CURRENT state. System must NOT modify it.
- **Q1..Q20 (`values[1..20]`) = forecast.** System DOES forecast all of these.

Audit question: does the codebase actually honor that distinction, or do the three writers misalign?

---

## 1. The values array layout

Every row in `model_input_json.sections.{revenue,expenses,balance_sheet}` carries a `values` list of length **21**:

| Index | Period | Semantics (per architecture) | Notes |
|---:|---|---|---|
| 0 | Stub / Q0 | Operator intake snapshot (pre-forecast) | Read by `_controller_row_stub_value` ([finmo_bridge.py:2023](python/client_intake_and_finmo/finmo_bridge.py#L2023)) for stub metric computation. |
| 1 | **Q1** | First forecast quarter | Read by FINMO via `_row_value(..., quarter_index=1)` → `storage_index = 1` ([model_inputs.py `_storage_index`](python/financial_model_engine/model_inputs.py)). |
| 2..20 | **Q2..Q20** | Forecast quarters | Same pattern. |

The architecture explicitly distinguishes stub from Q1. FINMO's stub computation reads `values[0]`; FINMO's live-quarter computation reads `values[quarter_index]`. They are NOT the same cell.

---

## 2. What each writer actually touches

### 2.1 Target solver — writes Q1..Q20 mechanically, but ramps anchor at Q1=current → Q1 residual = 0

The mechanical writer is `_write_driver_value_at_quarter` ([target_solver.py:473-511](python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L473-L511)):

```python
def _write_driver_value_at_quarter(*, driver_state, q_idx, new_value, target_metric):
    """Write `new_value` to every row backing this lever at LIVE quarter
    ``q_idx + 1`` (since row["values"][0] is the stub). ..."""
    live_idx = 1 + int(q_idx)   # q_idx=0 → live_idx=1 (Q1). q_idx=19 → live_idx=20 (Q20).
    ...
    vals[live_idx] = float(clamped)
```

**The writer can and does write `values[1]` (Q1).** It explicitly skips only `values[0]` (stub).

The solver's outer loop iterates `for q_idx in range(horizon)` where `horizon=20` ([target_solver.py:709](python/client_intake_and_finmo/post_intake_target_solver/target_solver.py#L709)), so q_idx∈[0..19] → Q1..Q20.

But within that loop:

```python
for q_idx in range(horizon):
    r = residuals[q_idx]
    if abs(r) <= tolerance:
        continue
```

A quarter is skipped only if its **residual** (metric_actual − target_ramp[q]) is within tolerance. So whether the solver touches Q1 depends entirely on `target_ramp[0]`.

`target_ramp` is built by `_build_target_ramp` ([restoration_loop.py:276](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L276)):

- **Working-capital / non-profitability targets** (`current_assets_minus_cash`, `current_liabilities_to_revenue`):
  ```python
  for q in range(horizon):
      frac = q / max(1, horizon - 1)
      ramp[q] = (1.0 - frac) * q1_current + frac * q20_target
  ```
  `ramp[0] = q1_current`. The Q1 of the ramp **is** the operator's current Q1 metric value (computed by `_compute_metric_per_q` against the current FINMO at the time the ramp is built). So `residuals[0] = current[0] − ramp[0] = 0`. **The solver's outer loop skips Q1 by construction for BS targets.**

- **Profitability targets** (`gross_margin_percent`, `ebitda_margin`):
  ```python
  if q1_loss_tolerated and q1_current < _floor_for_quarter(0):
      q1_anchor = q1_current
  else:
      q1_anchor = max(q1_current, _floor_for_quarter(0))
  ```
  When the planning mode does NOT tolerate Q1 loss AND `q1_current < band_floor`, the ramp's Q1 anchor is lifted to the floor → non-zero residual at Q1 → **solver does write Q1 for profitability targets in that case.**

| Lever class | Does the solver write `values[1]` (Q1)? |
|---|---|
| Working-capital / non-profitability targets | **No** — ramp anchors at current, residual is 0 |
| Profitability targets, planning mode tolerates Q1 loss | **No** — anchor at current |
| Profitability targets, planning mode does NOT tolerate Q1 loss AND current<floor | **Yes** — anchor lifted to floor → residual > 0 → solver writes Q1 |

So the answer to "why does the solver skip Q1 for BS items?" is **(a) intentional architectural decision**, driven by the ramp-shape choice in `_build_target_ramp`. The reasoning is documented in the function's docstring (lines 286-301):

> Q1 starts at max(current intake state, band_min) so the ramp respects the realism gate's per-quarter band floor.

For BS metrics there is no positive-only viability constraint, so the ramp is purely linear from `q1_current` to `q20_target` — meaning Q1 is held at the *current* metric value, which equals whatever the seed (or prior pass) put there.

### 2.2 Balance-sheet contextual seed — writes Q1..Q20, preserves stub

`apply_balance_sheet_contextual_seed_to_model_input` ([contextual_seed.py:202-270](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L202)):

```python
values = list(model_row.get("values") or [])
stub_value = values[0] if values else 0.0                # preserves index 0
...
live_values: List[float] = []
for idx in range(max(0, live_count)):                    # idx=0..19 → Q1..Q20
    quarter_index_1based = idx + 1
    existing = _safe_float(existing_live[idx]) if idx < len(existing_live) else None
    if quarter_index_1based in solver_authored_qs:
        live_values.append(round(float(existing or 0.0), 6))    # preserve solver write
    elif bool(seed_row.get("applicable")):
        live_values.append(round(seed_value, 6))                # flat-stamp seed_value
    else:
        live_values.append(round(float(existing or 0.0), 6))
model_row["values"] = _compose_period_values(stub_value=stub_value, live_values=live_values)
```

`_compose_period_values` then writes `[stub_value, *live_values]`. **The seed writes `values[1]..values[20]` with `seed_value` and explicitly preserves `values[0]`.**

The seed runs **on every FINMO rebuild** (it's invoked from `apply_derived_driver_policies_to_model_input` which `build_python_finmo_json` calls), but it has an exclusion mechanism: any quarter tagged via `applied_by_target_solver_quarters` is preserved (skipped from the flat-stamp). The first FINMO rebuild after intake has no solver provenance → seed flat-stamps all 20 quarters → subsequent FINMO rebuilds after the solver authors Q2..Q20 → seed flat-stamps **only Q1** (the unauthored quarter) and preserves Q2..Q20.

### 2.3 GPT exhaustion handler — writes Q1..Q20 for both P&L and WC

`_write_gpt_authored_per_quarter_values` for P&L drivers ([handler.py interpolation block](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py)):

```python
for q_idx, v in enumerate(values_to_write):
    live_idx = 1 + q_idx               # q_idx=0 → values[1] (Q1)
    if live_idx < len(vals):
        vals[live_idx] = float(v)
```

`_write_gpt_authored_working_capital_values` for WC drivers (P3.6, [handler.py:316-326](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L316)):

```python
for q_idx in range(HORIZON_QUARTERS):
    live_idx = 1 + q_idx
    if live_idx < len(vals):
        vals[live_idx] = float(value)
```

**The handler writes `values[1]..values[20]` for both P&L and WC. It does NOT write `values[0]` (stub).**

### 2.4 Summary table

| Writer | Stub (`values[0]`) | Q1 (`values[1]`) | Q2..Q20 (`values[2..20]`) |
|---|---|---|---|
| **Target solver (BS targets)** | does not touch | does not touch (ramp anchor) | writes |
| **Target solver (profit targets, lossy mode)** | does not touch | does not touch (ramp anchor at current) | writes |
| **Target solver (profit targets, non-lossy mode below floor)** | does not touch | writes (ramp anchor lifted to floor) | writes |
| **Balance-sheet contextual seed** | does not touch (preserves) | writes seed_value | writes seed_value |
| **GPT exhaustion handler** | does not touch | writes | writes |

**All three writers respect "stub = operator snapshot, never touch."** They differ on Q1.

---

## 3. The seed policy's explicit purpose

`balance_sheet_contextual_seed` module docstring ([contextual_seed.py:1-14](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py)):

```
"""Business-context balance-sheet driver seeding.

Module 5 Task 5.3 — Python proposes the balance-sheet seed grid; GPT
critiques. Python's `propose_balance_sheet_contextual_seed_payload`
builds the full payload from:
  1. Tier A intake anchors (stub-0 ar_balance, ap_balance,
     inventory_balance, prepaid_expenses, deferred_revenue when present)
  2. NAICS-cascade days/percent values (Module 1 resolver) for Q1+
     trajectory
  3. Per-lever applicability gates from NAICS-2 sectors
GPT receives the proposal and may amend specific applicable / seed_value
fields based on business-specific judgment (e.g., a retail superstore with
a membership program → flip deferred_revenue.applicable=true).
"""
```

Two-tier design:

| Tier | What it represents | Where it lives | Source |
|---|---|---|---|
| **Tier A — intake anchors** | Operator's stub-0 dollar balances (AR balance, AP balance, inventory balance, prepaid expenses, deferred revenue) | `schedules.{ar,ap,inventory,etc}_opening_balance_seed` and stub-0 cells | Operator's intake form |
| **Tier B — Q1+ trajectory** | Days / percent-of-revenue ratios for the FORECAST | `values[1..20]` of each BS row | NAICS cascade (industry typical) |

The intake anchors set ABSOLUTE DOLLAR BALANCES at Q0 (in the schedule seeds). The seed grid sets PER-QUARTER RATIOS for Q1..Q20 (in the values array). They are intentionally different things.

The intake form does NOT capture per-quarter forecasts of working-capital ratios — the operator can't realistically forecast their AR-days trajectory across the next 5 years. The seed grid fills that gap with NAICS-derived plausibility defaults so FINMO has something to compute against.

**So the seed's purpose is legitimate and clear:** it provides the FORECAST ratios for Q1..Q20 when the operator hasn't supplied them. The stub-0 dollar balances (Tier A) are the operator's actual snapshot.

### 3.1 Does the seed distinguish BS vs P&L?

**Yes — by design, only BS items are seeded contextually.** The candidate-row filter ([contextual_seed.py:90-109](python/client_intake_and_finmo/post_intake_balance_sheet/contextual_seed.py#L90)):

```python
def balance_sheet_contextual_seed_candidate_rows() -> List[Dict[str, Any]]:
  ...
  for row in post_intake_driver_formula_contract_rows():
    if not lever_id.startswith("balance_sheet::"):
      continue
    if _lower(row.get("driver_bundle")) != "working_capital_bundle":
      continue
    if _lower(row.get("forecast_presence_rule_key")) != "positive_driver_when_applicable":
      continue
    rows.append(...)
```

Only rows where:
- `lever_id` starts with `balance_sheet::`, AND
- `driver_bundle == working_capital_bundle`, AND
- `forecast_presence_rule_key == positive_driver_when_applicable`

…become contextual-seed candidates. P&L items (revenue, expenses sections) and BS items outside the working-capital bundle (debt schedule, equity, owners capital) are NOT touched by this seed.

So the BS-side seeding exists for a specific reason: working-capital ratios are *hard for operators to forecast but cohort-resolvable*. P&L ratios (CoGS%, marketing%, etc.) ARE more reliably captured at intake or computed elsewhere.

---

## 4. The actual NexGen alignment problem

Combining the three writers' behavior on NexGen's `Deferred Revenue (% of Revenue)` row:

| Quarter | Final value | Who set it |
|---:|---:|---|
| Stub (Q0) | 0.000 | (no writer; preserved baseline = 0 because intake doesn't directly populate a "% of revenue" stub) |
| Q1 | **0.300** | **Contextual seed (`seed_value=0.30`, applicable=True via subscription/membership token match)** |
| Q2-Q20 | 0.277 → 0.056 | Target solver (Tier 1 cost-priority allocation, drove the ratio down to band target by Q20) |

Why the solver skipped Q1:
- Restoration loop computed `current_metric_per_q[0] = 0.5509` (the `current_liabilities_to_revenue` value at Q1 with seed-stamped Q1 deferred revenue feeding FINMO).
- `_build_target_ramp` set `ramp[0] = q1_current = 0.5509` per the BS-target ramp shape.
- `residuals[0] = current[0] − ramp[0] = 0` → solver's outer loop skipped Q1.

The result: **Q1's deferred revenue stays at the cohort-default 30% because the ramp tells the solver that 0.59 is fine for Q1.** This is the alignment mismatch — the ramp anchors Q1 to a value that includes the seeded 30% as if that's the operator's actual state, when really 30% is a NAICS-derived guess.

---

## 5. Would changing the solver's Q1 anchor break anything?

### 5.1 What "fix the alignment" would actually mean

The user's read — "Stub = intake snapshot, Q1 = forecast, solver should write Q1" — translates concretely to one of:

| Approach | What changes | Side effects |
|---|---|---|
| **A. Ramp Q1 = band_target instead of q1_current** | `_build_target_ramp` for BS metrics anchors Q1 at `band_target` (or even at `(band_target+band_min)/2`), not at `q1_current`. Residual at Q1 becomes huge → solver tries to drive Q1 with whatever slack the BS drivers have. | Solver authority at Q1 limited by AP_days and Deferred_Revenue% bounds. With bounds tight (±15-20% typical), Q1 likely bound-pins → restoration loop returns EXHAUSTED instead of LANDED. Could regress drafts that currently pass on the LANDED path. Need explicit handoff to GPT handler. |
| **B. Ramp Q1 = q1_current but mark Q1 as solver-writable** | Add a step before the ramp build that re-derives `q1_current` from operator intake instead of from current FINMO. Operator intake for these levers IS captured in Tier A (stub-0 dollar balances) but isn't expressed as a "% of revenue" ratio. Would require deriving the ratio at intake. | Inverts the design intent of Tier A vs Tier B. The system would have to compute `deferred_revenue_balance / current_revenue` at intake time and stamp Q1 with that ratio. Operators may not have reliable enough numbers; cohort default exists for a reason. |
| **C. Remove the seed for Q1 specifically** | Seed flat-stamps only Q2-Q20, leaves Q1=0 (or =stub value). Solver's ramp at Q1=0 means residual is `0 − band_target`, opposite sign. Solver writes Q1 in the OTHER direction. | Q1 would land at solver's choice within bounds, but starting from 0 — totally non-operator-derived. Worse than current behavior. |
| **D. Change exhaustion semantics (Option A in the prior diagnosis doc)** | Leave the solver's Q1 anchor at q1_current. Tighten `RestorationStatus.LANDED` to forecast-check GPT-authorable realism metrics; route to handler when one would hard-fail downstream. | No change to solver / seed mechanics. Handler fires for NexGen-like cases and overwrites Q1..Q20 with GPT-authored values. Smallest blast radius. |

### 5.2 Does FINMO have Q1-specific contracts that would break under solver Q1 writes?

Audit of FINMO contracts:

- **Revenue formula contract** (`_enforce_revenue_driver_formula_contract`): checks `capacity × unit_price × utilization == finmo_revenue` for every LIVE quarter (Q1-Q20). No Q1-specific exception. Solver writing Q1 of revenue drivers (which it already does for revenue-side levers) doesn't trigger a contract violation as long as the three rows stay consistent.
- **Balance-sheet items**: no contract checks for `AR_days × revenue == finmo_AR` because FINMO derives AR FROM `AR_days`. No reverse formula to enforce. Solver writing Q1 of `AR_days` would simply produce a different Q1 AR in FINMO — internally consistent.
- **Stub computation** (`_build_operating_stub_metrics`): reads ONLY `values[0]` ([finmo_bridge.py:2023](python/client_intake_and_finmo/finmo_bridge.py#L2023)). Doesn't read Q1 values. So solver writing Q1 doesn't affect stub-side computation.
- **Schedule seeds**: opening balances for AR, AP, inventory, debt, etc., come from `schedules.*_opening_balance_seed` (set from Tier A intake anchors). These feed FINMO's quarter-0 starting state. Solver doesn't touch them.

**No Q1-specific contract would break under solver Q1 writes.** The architectural distinction the user has in mind (stub = intake snapshot, Q1 = forecast) IS the system's distinction at the contract level — but the solver's ramp-anchor choice prevents it from exercising Q1 authority on BS items.

### 5.3 Does anything LEGITIMATELY require the seed Q1 to dominate?

One concern worth flagging: if Tier A intake anchors set, e.g., `deferred_revenue_balance_opening_seed = $0` (operator has no deferred revenue at Q0), and the seed then stamps Q1 at 30% deferred-revenue ratio, FINMO computes:
- Q1 deferred_revenue = `0.30 × Q1_revenue` = a large positive number
- But Q0 deferred_revenue = $0
- The **change** in deferred revenue across Q0→Q1 flows through cash-flow statements as a working-capital change.

The seed's Q1 stamp creates a Q0→Q1 jump in working-capital balances that the operator didn't have at intake. That's a side effect of using cohort defaults for Q1.

If the operator's actual stub balance (Tier A) is non-zero, the jump is smaller. If the operator's actual stub balance is $0 and cohort default is 30%, there's a discontinuity. This is independent of whether the solver writes Q1 — it's a property of the seed itself.

---

## 6. Findings summary

| Question | Answer |
|---|---|
| Does the solver mechanically support writing Q1? | **Yes.** `_write_driver_value_at_quarter` writes `values[1 + q_idx]` for `q_idx=0..19`. |
| Why does the solver appear to skip Q1 for BS items? | **Ramp anchor**, not writer behavior. `_build_target_ramp` for non-profitability targets sets `ramp[0] = q1_current` → Q1 residual = 0 → outer loop skips Q1. **Intentional architectural decision** ([restoration_loop.py:286-302](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L286)). |
| Does the solver ever write Q1? | **Yes — for profitability targets** when planning mode does NOT tolerate Q1 loss AND `q1_current < band_floor`; the ramp's Q1 anchor is lifted to the floor, producing a non-zero residual at Q1. |
| What is `balance_sheet_contextual_seed` for? | **Provides NAICS-derived Q1..Q20 forecast ratios** for working-capital BS levers when the operator hasn't supplied per-quarter projections. Tier A intake anchors set Q0 dollar balances; Tier B (the seed) sets Q1..Q20 ratios. Two different things, both intentional. |
| Does the seed write Stub? | **No.** It preserves `values[0]` and writes `values[1..20]`. |
| Does the seed distinguish BS vs P&L? | **Yes.** Only `balance_sheet::*` rows with `driver_bundle=working_capital_bundle` and `forecast_presence_rule_key=positive_driver_when_applicable` are seed candidates. P&L items and BS items outside the working-capital bundle are untouched. |
| Does the handler write Q1? | **Yes — both P&L (Q1..Q20 via interpolation from anchors) and WC (Q1..Q20 stamped with single value).** Handler does NOT touch stub. |
| Would FINMO break if the solver wrote Q1 for BS items? | **No.** No Q1-specific contracts. Stub computation reads `values[0]` only. Schedule seeds feed Q0 opening balances independently. Solver Q1 writes for BS items would be internally consistent. |

---

## 7. Implication for NexGen and Option A

The alignment **isn't broken**; the system's distinction between stub (Q0, intake) and Q1 (first forecast quarter) is honored by every writer. The narrower problem is: **the solver's BS-target ramp anchors Q1 at `q1_current`, which equals the seed-stamped seed_value.** That's by design, but it has the consequence that Q1 deferred revenue for NexGen stays at the cohort-default 30% — invisible to the solver's optimization.

Two ways to address NexGen's specific failure:

- **(i) Change the ramp anchor for BS targets.** Make `ramp[0] = band_target` (or `(band_target + q1_current) / 2`) so the solver has a non-zero Q1 residual to absorb. The solver then exercises its Q1 authority through AP_days and Deferred_Revenue% slack. Probably bound-pins Q1 given typical ±15-20% bounds and the large gap, so the loop would return EXHAUSTED → handler fires. Wider blast radius (affects every BS-target run, not just NexGen-like cases).
- **(ii) Option A from the prior diagnosis doc.** Tighten `RestorationStatus.LANDED` to forecast-check GPT-authorable realism metrics. Doesn't change the solver / seed mechanics. Handler fires for NexGen-like cases on the existing scoped-authority path. Narrowest blast radius.

**Recommendation:** Option A. The Q1-skip is not an alignment bug — it's an architectural choice with a documented reason (working-capital metrics have no positive-only viability constraint, so the ramp anchors at the operator's current state and lets the solver drive the trajectory through Q2..Q20). Forcing the solver to absorb a Q1 residual against the seed-stamped value would change the load-bearing behavior of every BS target across every business and likely regress drafts that currently pass on the LANDED path. The GPT exhaustion handler is the correct authority for cases where the seed + solver can't bridge the gap; Option A simply makes the trigger condition catch NexGen.

---

## 8. Pointers for follow-up

If the user opts to change the solver's BS-target Q1 anchor (instead of / in addition to Option A):

- `_build_target_ramp` ([restoration_loop.py:311-317](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L311)) is the single point of change. For non-profitability targets, replace the pure-linear `q1_current → q20_target` shape with `band_aware_q1 → q20_target` (e.g., `q1_anchor = (band_target + q1_current) / 2` or simply `q1_anchor = band_target`).
- Sanity-check across NexGen, Sunny, Express, and any other completed drafts — the change affects every BS-target restoration pass.
- Watch for cascade: changing Q1 changes the FINMO state going into the cash strategy (current_liabilities trajectory shifts), which may affect funding-decision provenance.
- If the change pushes BS targets to EXHAUSTED instead of LANDED for previously-passing drafts, ensure the handler's scoped authority (P3.7 scope-implementation) is in place to absorb the new exhaustion cases without forcing a full 12-driver re-author.

If the user opts for Option A only: no solver changes; just the LANDED-exit predicate change + scoped-authority handler implementation, as scoped out in the prior NexGen-adaptation diagnosis doc.
