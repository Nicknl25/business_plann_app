# Payroll/Revenue Feasibility Assert — Purpose Trace (no code, no fix)

**Question:** the cash/funding pass runs LAST. The payroll/revenue feasibility assert fires in
the OPERATING phase and crashes when payroll/revenue is out of band (Sunny: ~146% > ~96% max).
Is the assert (a) a viability proxy, (b) an affordability/funding proxy, or (c) a mechanical
coherence guard that something pre-funding genuinely requires? And does anything between the
assert and funding actually depend on payroll ≤ revenue?

**Answer up front:** it is **(a)+(b) — a premature viability/affordability judgment, NOT (c)**.
Nothing between the assert and the funding pass mechanically depends on payroll ≤ revenue;
finmo computes negative pre-funding cash freely and the cash pass is purpose-built to absorb the
shortfall. The founder-draw carve-out is therefore **moot**; the fix is to **retire/defer the
assert pre-funding**.

---

## 1. What the assert actually checks (its own framing)

`payroll_revenue_feasibility_violations` / `assert_payroll_revenue_feasibility`
([schedule.py:3059-3128](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3059-L3128),
[:3215-3241](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3215-L3241)):
- Computes `ratio = payroll / revenue` per quarter ([:3128](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3128)) and fails if it
  is outside the labor-intensity **"sanity bounds"** band ([:3096](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3096),
  [:3129](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3129)).
- Its own docstring: *"This is not a cap... It is a coherence test: if the relationship is
  outside the headcount policy range, upstream drivers must be recomputed"*
  ([:3065-3069](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3065-L3069)).
- Failure message: *"Payroll/revenue economics are outside the table-backed headcount policy
  range; recompute drivers instead of clipping outputs"*
  ([:3231](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3231)).

So by construction it is a judgment about the **payroll-to-revenue economic relationship** —
"is this labor cost structure economically reasonable for this revenue?" That is a
viability/affordability proxy, not a mechanical precondition.

---

## 2. The operative firing is PRE-funding (and pre-cascade, pre-viability-standard)

The assert fires from `assert_post_intake_global_invariants`
([fail_fast.py:2018-2022](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L2018-L2022))
at **multiple** points:
- **Initial-grid checkpoints** in `prepare_initial_grid_for_draft` —
  `resume_checkpoint_ready` ([runner.py:1517](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1517)),
  `quarter_grid_applied` ([:1771](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1771)),
  `quarter_grid_applied_after_feasibility_repair` ([:1806](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1806)).
- **Finalize** (post-cascade, post-cash) — `finalize_post_intake.py:607`.

**Sunny crashes at `quarter_grid_applied_after_feasibility_repair`** (confirmed live, 2026-06-02
run of draft `2ef6bfcc`; HTTP 500). That checkpoint is in the **initial grid**, which runs in
`_run_planning_system_for_draft_unified` **before** the cascade, the cash pass, and the
finalize realism/acceptance gates. So the firing that actually kills the run is **pre-funding,
pre-cascade, and pre-viability-standard** — it judges the payroll/revenue economics before any
of the passes that actually determine affordability or viability have run.

(Per the orchestration order, the cash/funding pass runs LAST: `_run_post_cascade_completion`
runs the cash strategy `run_mode_based_cash_strategy`
([orchestrator.py:2768-2889](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2768-L2889))
**before** `run_finalize_post_intake_validation`
([orchestrator.py:3408-3479](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L3408-L3479)).
So even the *finalize* firing is the standalone gate; the initial-grid firing is earlier still.)

---

## 3. Does anything pre-funding mechanically require payroll ≤ revenue? — NO

This is the decisive test. Tracing the operating-phase math between the assert and funding:

- **EBITDA is a linear subtraction** — `ebitda = gross_profit − (marketing + r&d + lease +
  payroll + g&a)` ([finmo_model.py:451](../../python/financial_model_engine/finmo_model.py#L451)).
  Payroll > revenue simply yields a deeply negative EBITDA. No break, no guard.
- **Net income** likewise linear ([finmo_model.py:489](../../python/financial_model_engine/finmo_model.py#L489)).
- **Ending cash has NO non-negativity guard** — `ending_cash = beginning_cash + net_cash_flow`
  ([finmo_model.py:583](../../python/financial_model_engine/finmo_model.py#L583)); it computes
  negative values freely.
- **No division by `(revenue − payroll)`** anywhere; accounts_payable is an additive function of
  the expense bucket, not a ratio of revenue ([finmo_model.py:503](../../python/financial_model_engine/finmo_model.py#L503)).
- **Nothing between the assert and funding consumes the payroll/revenue ratio as a
  precondition.** The only place the ratio is read is the assert itself; it feeds no repair lever
  or downstream computation. (The `required_revenue_at_bound = payroll / min_allowed` math at
  [schedule.py:3131-3133](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3131-L3133)
  only runs *inside* the violation builder, after it has already decided to fail.)

**So there is no real mechanical reason it must fire pre-funding.** Finmo tolerates payroll >
revenue and negative pre-funding cash by construction.

---

## 4. Negative early cash is the DESIGNED, expected state — funding absorbs it

The cash/funding pass is purpose-built to cover exactly this shortfall:
- `post_intake_cash_strategy/orchestrator_invocation.py:1-9` — *"Seeds a minimum debt schedule
  (covers any negative-cash quarter with new long-term debt at the industry rate)."*
- The cash pass rebuilds FINMO post-funding ([orchestrator.py:2864-2870](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L2864-L2870)).
- The viability standard's own Gate machinery encodes the same doctrine — early losses funded
  through a loss window are normal (see `loss_window_funded_through_q5` in the realism timeline
  and [fix_1_viability_standard_spec.md](fix_1_viability_standard_spec.md) §1: viability =
  economic soundness, *explicitly NOT solvency/runway*; funding is handled elsewhere).

Early payroll > revenue funded by debt/equity is the **normal state of a funded ramp**. The
assert hard-fails that normal state before the pass that funds it has run.

---

## 5. Classification + recommendation

**Classification: (a) viability proxy + (b) affordability proxy — both now owned by later
passes; NOT (c) a mechanical guard.**
- The "is the labor cost structure economically sound?" content is **(a) viability** → now owned
  by the new standard's trajectory gates ([fix_1_viability_standard_spec.md](fix_1_viability_standard_spec.md)
  §3), which judge EBITDA breakeven/cumulative trajectory rather than a single-quarter ratio.
- The "can this payroll be paid?" content is **(b) affordability** → owned by the cash/funding
  pass, which runs LATER and actually determines it via debt/equity.
- There is **no (c)** mechanical dependency: §3 shows nothing pre-funding requires payroll ≤
  revenue.

**Residual real concern (small, and not (c)):** a payroll/revenue ratio *wildly* outside any
plausible band can also indicate **malformed drivers** (a broken FTE/wage grid), which is what
the "recompute drivers" framing targets. But (i) this is a heuristic quality flag, not a
mechanical requirement, and (ii) it is applied as a **uniform band across all quarters with no
ramp allowance** ([schedule.py:3120-3129](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3120-L3129)),
so it cannot distinguish a malformed-driver outlier from a legitimately funded early ramp — the
exact conflation Fix #1 exists to fix.

**Recommendation:** Because it is (a)+(b), the **founder-draw carve-out is moot** — the fix is to
**retire or defer the pre-funding firing of this assert** so the plan reaches the passes that
actually determine affordability (funding) and viability (the new standard). If the
malformed-driver signal is worth keeping, it should be re-expressed as a *much wider* outer
sanity envelope (catching only physically-impossible ratios, e.g. orders of magnitude off) or
moved POST-funding/POST-viability — not a labor-intensity band that fires mid-operating-phase on
a normal funded ramp. Exact retire-vs-defer-vs-widen mechanics are a follow-on decision, not
made here.
