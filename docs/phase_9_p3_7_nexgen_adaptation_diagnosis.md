# Phase 9 P3.7 — NexGen Adaptation Diagnosis

**Date:** 2026-05-10
**Subject draft:** `f6b0682f99354914b1f8d9cc21eeca36` (NexGen Software Solutions Inc., NAICS 513210, B2B SaaS)
**P3.6 commit under test:** `19dafb3`
**Acceptance gate result:** **15/16** — single failure on `realism_gate_no_hard_fail_violations`
**Investigation only — no code changes.**

---

## Investigation 1 — What happened to NexGen's restoration loop

### 1.1 Restoration loop status

```
RestorationStatus.LANDED
outer_passes_used: 1
reason: "all_viability_trajectory_checks_passed"
```

The loop exited via the **LANDED** path, not EXHAUSTED. This is the load-bearing detail of this whole investigation, because the GPT exhaustion handler fires only on `EXHAUSTED` ([orchestrator.py:1648](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1648)).

### 1.2 Per-target convergence (latest pass)

| Target | Status | Inner iters | Q11 initial | Q11 final | Band target | Drivers at bounds |
|---|---|---:|---:|---:|---:|---|
| `ebitda_margin` | **converged** | 2 | -0.226 | **+0.046** | -0.005 | `expenses::Payroll` lower |
| `current_assets_minus_cash` | **bound_pinned** | 3 | 0.140 | 0.388 | 0.559 | {} |
| `current_liabilities_to_revenue` | **bound_pinned** | 8 | 0.543 | 0.295 | **0.057** | {} |

Two of the three targets ended `bound_pinned` — the solver ran out of driver authority before reaching the band target — and yet the loop returned LANDED. This is because the LANDED exit condition is gated **only** on the 6 universal viability trajectory metrics passing ([restoration_loop.py:830](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L830)):

```python
if all(final_viability.get(m, False) for m in _VIABILITY_TRAJECTORY_METRICS):
    return RestorationResult(status=RestorationStatus.LANDED, ...)
```

`_VIABILITY_TRAJECTORY_METRICS` = `(ebitda_positive_by_q11, ebitda_recovery_trend_q5_q11, loss_window_funded_through_q5, no_post_recovery_relapse_q11_q20, gross_margin_supports_ebitda_recovery, fixed_cost_burden_reduced_or_scaled_by_q11)`. All 6 PASS for NexGen at Q11 → LANDED. The fact that two BS targets are bound-pinned (and the residuals will hard-fail the realism gate at Q1-Q9) is **invisible to the LANDED exit gate**.

The EXHAUSTED exit is mutually exclusive with LANDED — it explicitly requires `not all(final_viability...)` ([restoration_loop.py:882](python/client_intake_and_finmo/post_intake_target_solver/restoration_loop.py#L882)). Since viability passes, EXHAUSTED can never fire for NexGen even though the loop is functionally stuck.

### 1.3 The deferred-revenue smoking gun

`balance_sheet::Deferred Revenue (% of Revenue)` values written for NexGen, Q1-Q20:

```
Q0 (stub): 0.00
Q1:  0.300  ← provenance: none (seed policy, not solver)
Q2:  0.277
Q3:  0.251
Q4:  0.234
Q5:  0.218
Q6:  0.199
Q7:  0.180
Q8:  0.163
Q9:  0.148
Q10: 0.136
Q11: 0.118
Q12: 0.100
Q13: 0.091
Q14: 0.074
Q15: 0.059
Q16: 0.056
Q17-Q20: 0.056
```

The row carries `derived_driver: balance_sheet_contextual_seed` and the provenance map (`applied_by_target_solver_quarters`) covers `Q2..Q20` — **Q1 has no provenance**. Q1's 0.30 value was set by the `balance_sheet_contextual_seed` policy, not by the target solver, and the solver's contract excludes Q1 from its writes. The solver successfully ramped Q2-Q20 down from 30% toward its band target of 5.7% but **had zero authority over Q1**.

Seed-policy entry for this lever:

```python
{
  "lever_id": "balance_sheet::Deferred Revenue (% of Revenue)",
  "business_applicability_key": "deferred_revenue_business",
  "applicability_positive_tokens": ["subscription", "membership", "retainer",
    "deposit", "prepaid", "advance payment", "upfront", "annual contract"],
  "applicable": True,
  "seed_value": 0.30,
  "minimum_live_value": 0.01,
  "maximum_live_value": 0.75,
  "rationale": "naics_cascade (deferred_revenue_percent_of_revenue target=0.2138)"
}
```

Note: the naics_cascade derived a target of **0.2138**, but `seed_value` is **0.30** — Q1 was seeded above the cascade target. The seed policy is the active determinant of Q1's value.

### 1.4 Cohort band for `current_liabilities_to_revenue`

```
band_source:    phase_3_calibrated
effective_min:  -0.20335
effective_max:  0.351102
cohort_level:   None
cohort_naics_used: None
cohort_sample_size: None
```

The band comes from the **phase_3_calibrated** subsystem, not the live `cohort_alternating_edgar` walker. The cohort metadata fields (`cohort_level`, `cohort_naics_used`, `cohort_sample_size`) are all `None` because phase_3_calibrated bands are pre-computed across the industry universe and exposed as fixed bands per metric. They do not stratify by NAICS for this metric on this draft.

The cap is **35.1%** — built largely from non-SaaS firms (publishing, traditional services, retail). B2B SaaS businesses run structurally higher current liabilities at Q1 because of large annual-prepayment deferred-revenue pools.

### 1.5 The 15/16 acceptance-gate failure

Single failed check: `realism_gate_no_hard_fail_violations`. Nine `hard_fail_violations` rows, all on the same metric:

| Quarter | actual_value | effective_min | effective_max | band_source |
|---:|---:|---:|---:|---|
| Q1 | **0.5936** | -0.20335 | 0.35110 | phase_3_calibrated |
| Q2 | 0.5641 | -0.20335 | 0.35110 | phase_3_calibrated |
| Q3 | 0.5395 | -0.20335 | 0.35110 | phase_3_calibrated |
| Q4 | 0.5117 | -0.20335 | 0.35110 | phase_3_calibrated |
| Q5 | 0.4821 | -0.20335 | 0.35110 | phase_3_calibrated |
| Q6 | 0.4534 | -0.20335 | 0.35110 | phase_3_calibrated |
| Q7 | 0.4258 | -0.20335 | 0.35110 | phase_3_calibrated |
| Q8 | 0.3981 | -0.20335 | 0.35110 | phase_3_calibrated |
| Q9 | 0.3691 | -0.20335 | 0.35110 | phase_3_calibrated |

By Q10 the metric falls within band (Q11 = 0.295 per the restoration trace) and Q10-Q20 are all in-band. The failures are **entirely in the Q1-Q9 window** where the deferred-revenue ramp is still descending from the seed-set 30%.

Q1 line-item breakdown (revenue $1,400,533):
- accounts_payable:   $351,391  (**25.1%** of rev) — derived from AP_days=29.36 × opex / 90
- deferred_revenue:   $420,160  (**30.0%** of rev) — `0.30 × revenue` from the contextual seed
- short_term_debt:    $59,850   (4.3% of rev)
- **Total CL:**       $831,401  (**59.4%** of rev) — vs cap 35.1%

The 30% deferred-revenue seed is the dominant single contributor.

### 1.6 Classification of the failure mode

**Answer: (A), with a refinement.** The solver successfully wrote a Q2-Q20 ramp that brings `current_liabilities_to_revenue` within the calibrated band by Q11 and keeps it within band through Q20. The metric is band-compliant in the second half of the planning horizon. But:

1. The solver had no authority over Q1 (seed-policy locked) and the seed seeded at 30%, above even the cascade target.
2. Q1-Q9 are mid-descent from the seed; the ramp goes through the band cap at roughly Q9-Q10.
3. AP days at Q1 (29.36) is also high enough to push AP contribution to 25% of revenue independent of deferred revenue.

So strictly the loop "landed" by writing deferred revenue successfully in the latter window, but Q1-Q9 still overshoot. The exhaustion semantics don't catch this because EXHAUSTED requires viability to fail, which it doesn't.

---

## Investigation 2 — Current GPT handler scope

**Confirmed.** The handler's current behavior:

| Statement | Confirmed |
|---|---|
| Handler fires only on `RestorationStatus.EXHAUSTED` | ✓ ([orchestrator.py:1648](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1648)) |
| When firing, GPT must author **all 12 drivers** (7 P&L 3-anchor + 5 WC singles) | ✓ — the commit schema and tool schema both declare all 12 as `required` ([tool_calling_session.py `_build_commit_schema`](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py)) |
| No scoped / partial driver authority exists | ✓ — there is one entry point, one prompt, one schema; no branching by trigger cause |

For completeness: when the handler fires, it routes through `execute_tool_calling_session_and_commit` which builds the `operating_context` with the full `model_input_template` and `build_finmo` callable; the tool-calling session runs GPT iteratively against `compute_full_trajectory`; the committed anchors are written to `model_input` via `_write_gpt_authored_per_quarter_values`. The writer stamps **all 20 quarters including Q1** for both P&L (3-anchor interpolation) and WC (single-value broadcast). So the handler — if it fired — has the authority Q1's seed policy denies the solver.

---

## Investigation 3 — Architectural feasibility & gap analysis

### 3.1 Scoped GPT authority — feasibility

The proposed scoping:
- **P&L target exhaustion** → GPT authors P&L drivers AND WC drivers
- **BS-only target exhaustion** → GPT authors ONLY WC drivers
- **Both** → GPT authors all 12

This is architecturally feasible. The handler is already structured around dynamically-built schemas/prompts; scoping is a parameterization, not a rewrite.

**Changes required to scope authority:**

| Component | Change |
|---|---|
| **Trigger logic** ([orchestrator.py:1648](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1648)) | Replace the `if status == EXHAUSTED` gate with a classifier that returns one of `{none, pnl_only, wc_only, both}` based on (a) `RestorationStatus`, (b) which target(s) bound-pinned vs converged, (c) which realism metrics are forecast to hard-fail and whose `primary_levers` are GPT-authorable. |
| **Handler entry point** ([handler.py `run_gpt_exhaustion_handler`](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py)) | Accept a `scope` parameter and pass it down through `execute_tool_calling_session_and_commit`. |
| **Tool definition** ([tool_calling_session.py `_build_tool_definition`](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py)) | Parameterize `parameters.required` and `parameters.properties` by scope — emit only the driver groups in scope. |
| **Commit schema** (`_build_commit_schema`) | Same parameterization. |
| **User prompt** (`_build_initial_user_prompt`) | Tell GPT which drivers are in scope and which are fixed. Universal language: "You author X drivers; A, B, C are held at their current values." |
| **Validator** ([validators.py `validate_final_commit`](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/validators.py)) | Validate only the keys in scope. |
| **Writer** (`_write_gpt_authored_per_quarter_values`) | Already handles missing keys gracefully (`skipped_no_anchor`). **No change needed** — pass the scoped payload through and the writer's existing dispatch handles the rest. |
| **Mute mechanism** (`compute_metrics_to_mute`) | Take a `gpt_authored_lever_ids` set as input (computed from scope) rather than reading the static module-level constants. Mute only metrics whose `primary_levers` are in the actually-authored set. |

**Universal-app discipline holds.** No NAICS / archetype branching is introduced; scope is computed from generic restoration-result signals (which targets bound-pinned) and the realism config's `primary_levers` (which themselves are universal).

### 3.2 Interaction effects to flag

| Concern | Assessment |
|---|---|
| WC days change but revenue/COGS don't — FINMO consistency? | **No issue.** FINMO computes AR=`(AR_days/90) × revenue`, Inventory=`(Inv_days/90) × COGS`, AP=`(AP_days/90) × opex`. Revenue and COGS remain whatever the restoration loop wrote; only the WC days input changes. FINMO recomputes consistently. |
| Q1 seed-policy override via WC-only handler | The contextual seed sets Q1 deferred revenue at 30% because `applicability_positive_tokens` matched the business description. GPT's WC-only write at Q1 overrides this. **No state inconsistency** — the seed policy is informational; GPT is the authority. Worth documenting that GPT's WC values supersede the seed. |
| Pre-recovery driver vs post-recovery driver in a WC-only scope | WC drivers are single-value-across-horizon by design (P3.6). No Q1/Q11/Q20 distinction to lose. Doesn't matter what restoration did with P&L drivers — WC writes are independent. |
| `compute_metrics_to_mute` correctness in scoped case | Without modification, the current `compute_metrics_to_mute` would mute metrics whose `primary_levers` include any P&L driver — even when only WC was authored. **This would over-mute** and could hide P&L-side hard-fails. Must be fixed alongside scoping (see 3.1 table). |
| Universal viability trajectory checks (the 6 protected) | Stay never-muted regardless of scope. Already correct in current code. |

### 3.3 The second-chance handler question

The user's separate question: **should the handler also fire when restoration technically "lands" but the realism gate would still hard-fail?**

**There is a gap.** Today:

```
restoration_loop → [if EXHAUSTED → handler] → cash_strategy → realism_gate → acceptance_gate
                          ↑
                  (one and only one shot)
```

If the handler doesn't fire AND the realism gate later finds hard-fail violations on metrics whose `primary_levers` are GPT-authorable, the acceptance gate fails and the workbook isn't exported. There is no second-chance mechanism. The NexGen run is exactly this case: restoration LANDED, handler skipped, realism gate found 9 hard-fail rows that the handler — if it had fired — would have either fixed (by writing distinct WC values) or muted (because the metric's `primary_levers` are entirely in the GPT-authored set).

**Two design options to close the gap:**

**Option A — Forward-looking exhaustion semantics.** Tighten `RestorationStatus.LANDED` to require not just the 6 viability checks but also that no GPT-authorable realism metric is forecast to hard-fail. Implementation: after the viability check inside the loop, run a pre-realism band check for metrics whose `primary_levers` are entirely in `GPT_AUTHORED_LEVER_IDS ∪ GPT_AUTHORED_WORKING_CAPITAL_LEVER_IDS`; if any hard-fails, route to handler instead of returning LANDED. Has the property that the trigger is decided BEFORE the cash strategy runs, so the handler can author WC drivers and the cash strategy reads the GPT-authored model_input.

**Option B — Post-realism second-chance.** After the realism gate runs, if any `hard_fail_violations` have `primary_levers ⊆ (GPT_AUTHORED_LEVER_IDS ∪ GPT_AUTHORED_WORKING_CAPITAL_LEVER_IDS)`, re-invoke the handler with a scope determined from those failed metrics' levers, then re-run cash strategy + realism gate. Has the property that handler decisions can be informed by actual realism results, not predicted ones. Costlier (extra cash-strategy + realism-gate pass when triggered).

**Recommendation (for the user's decision, not a unilateral choice):** Option A is simpler and produces a single ordering for downstream stages. It also keeps the handler upstream of cash strategy, which means cash strategy sees the corrected model_input — important because cash strategy reads working-capital values to compute funding needs and a 30% deferred-revenue Q1 vs a 5% Q1 implies very different cash positions.

Option B is necessary only if there are realism failures that depend on values the restoration loop computes (cash projections, current_assets) that can't be cleanly predicted by the loop itself. For NexGen's specific case (deferred revenue on a stable %), Option A would catch it cleanly.

---

## Summary of the gap

NexGen failed 15/16 because:

1. The restoration loop's **LANDED exit** ignores BS-target bound-pinning; only universal viability matters.
2. The **contextual seed policy** sets Q1 deferred revenue at 30% (above its own naics_cascade target of 0.214) based on token-matching the business description; the target solver doesn't have Q1 authority.
3. The **GPT exhaustion handler fires only on EXHAUSTED**; LANDED with bound-pinned BS targets is invisible to it.
4. The handler, if it fired, would have full Q1 authority via the WC writer (P3.6) and would mute `current_liabilities_to_revenue` because both its `primary_levers` (AP Days + Deferred Revenue %) are in the GPT-authored set.

Two architectural moves close the gap: **scoped GPT authority** (so a partial fire is meaningful) and **forward-looking exhaustion semantics** (so a bound-pinned-but-viable result triggers the handler when a GPT-authorable realism failure is downstream-inevitable). Both are feasible without disturbing the tool-calling architecture, the cash strategy, or the universal viability protection.

---

## Pointers for follow-up implementation

- **Trigger classifier**: needs a function that takes `(restoration_result, model_input)` and returns `scope ∈ {none, pnl_only, wc_only, both}`. Inputs needed: `restoration_result.per_pass_diagnostics[-1].targets_bound_pinned`, plus a per-metric forecast band check that mirrors the realism gate's logic.
- **Per-metric forecast**: the realism gate already exposes `post_intake_finalize_realism_check_rows`; iterating through rows whose `active=True` and primary_levers are in the GPT-authored union, evaluating each on the post-restoration FINMO, gives the prospective hard-fail set.
- **`compute_metrics_to_mute` parameterization**: change signature to accept a `gpt_authored_lever_ids: Set[str]` arg; remove the module-level static read.
- **`_build_tool_definition` / `_build_commit_schema`**: factor out `required` and `properties` construction so the same code emits scoped variants.
- **`_build_initial_user_prompt`**: add a "your authority for this run covers: …" block that lists in-scope drivers.

Universal-app discipline is preserved at every step — the scope is derived from generic signals (restoration target results + realism config primary_levers), never from NAICS / archetype branches.
