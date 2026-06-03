# Fix #1 — Early-Quarter Viability Scope (trace only, no code)

**Status:** scope / trace. No code changes proposed here.
**Question:** the payroll/revenue feasibility gate hard-fails a real ramping startup
(Sunny: ~$34k/qtr founder draws vs ~$23k/qtr early revenue → payroll/revenue ≈ **146%**,
far above the expert-intensity band max of 80%). This is structural — no payroll author
can satisfy a revenue-scaled band when the numerator is a fixed founder draw and the
denominator is nascent revenue. Before touching the gate, scope: what fires, what else
fires on the same early-quarter basis, and whether Fix #1 is one fix or a chain.

Every claim below is grounded `file:line`.

---

## 0. The Sunny numbers used throughout

The operative reproduction numbers are the ones in the Fix #1 brief:
- Early-quarter founder draws (payroll) ≈ **$34k/qtr** (fixed, non-scalable).
- Early-quarter revenue ≈ **$23k/qtr** (nascent, ramping).
- payroll / revenue ≈ **1.46 (146%)** in the early quarters.

Note: the earlier investigation [p3_32_k10_sunny_stage_ramp_investigation.md:74-92](p3_32_k10_sunny_stage_ramp_investigation.md#L74-L92)
records a *different*, higher-revenue Sunny run (~$121k–$239k/qtr quarterly revenue).
That run is not the Fix #1 reproduction; the low-revenue/high-founder-draw case in the
brief is the one that exposes the structural gate failure. Where I reason about EBITDA
margins below, I use the 146% case.

---

## 1. THE PAYROLL GATE

### 1.1 Entry assertion
`assert_payroll_revenue_feasibility` — [schedule.py:3215-3241](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3215-L3241).

- It computes a `stage_key` and **early-returns** when the stage string contains
  `"pre_quarter_grid"` — [schedule.py:3221-3223](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3221-L3223).
  This is the *only* stage-based exemption, and it is keyed on **pipeline stage name,
  not on forecast quarter**. It does not soften any quarter; it skips the check entirely
  at the pre-grid checkpoint.
- Otherwise it calls `payroll_revenue_feasibility_violations(...)` and, if any violation
  comes back, raises `_payroll_fail_fast("payroll_revenue_economic_feasibility_failed", ...)`
  — [schedule.py:3224-3241](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3224-L3241).
  This is a **hard fail-fast**, not a soft warning.

### 1.2 What it checks — `payroll_revenue_feasibility_violations`
[schedule.py:3059-3212](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3059-L3212).

Band resolution (computed **once**, for the whole horizon):
- Pull policy + labor-intensity class — [schedule.py:3093-3094](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3093-L3094).
- Resolve `min_pct` / `max_pct` from the sanity-bounds table via
  `headcount_payroll_revenue_sanity_bounds` — [schedule.py:3096-3105](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3096-L3105),
  defined at [lookup.py:836-850](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L836-L850).
- Band numbers (defaults) — [lookup.py:74-78](../../python/client_intake_and_finmo/post_intake_headcount/lookup.py#L74-L78):
  `low {0.06,0.45}`, `medium {0.10,0.55}`, `high {0.16,0.70}`, `expert {0.18,0.80}`.
- Tolerance expansion — [schedule.py:3106-3109](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3106-L3109):
  `tolerance_pct` default 0.03, `relative_tolerance` default 0.20, so
  `max_allowed = max_pct + max(0.03, max_pct*0.20)`.
  For Sunny (expert, max_pct=0.80): `max_allowed = 0.80 + max(0.03, 0.16) = 0.96`.
  `min_allowed = 0.18 − max(0.03, 0.036) = 0.144`. Effective band ≈ **[0.144, 0.96]**.

The per-quarter loop:
- Iterates **every** quarter row with `quarter_index >= 1`, sorted ascending —
  [schedule.py:3111-3114](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3111-L3114).
- Skips only quarters where `revenue <= 0` — [schedule.py:3124-3127](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3124-L3127).
- Computes `ratio = payroll / revenue` and flags a violation when
  `ratio < min_allowed or ratio > max_allowed` — [schedule.py:3128-3129](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3128-L3129).
- Emits `payroll_revenue_economic_feasibility_failed` per offending quarter —
  [schedule.py:3156-3188](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3156-L3188).
- Separately enforces a monotonic trend rule (payroll can't fall while revenue rises) —
  [schedule.py:3189-3209](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3189-L3209).

### 1.3 Early vs late treatment — **uniform, zero ramp allowance**
The loop body ([schedule.py:3120-3211](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3120-L3211))
has **no `quarter_index` conditional** anywhere. The same `[min_allowed, max_allowed]`
band is applied identically to Q1 and Q20. There is no grace window, no convergence
test, no per-quarter ramped band. The single band is computed before the loop
([schedule.py:3104-3109](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3104-L3109))
and reused unchanged for all quarters. **This is the root structural defect for Fix #1.**

For Sunny: early ratio 1.46 > max_allowed 0.96 → `too_high` violation in every early
quarter. No payroll author can fix it (the founder draw is fixed; revenue is the
denominator and is genuinely small early), so the gate's `required_action`
("re-derive supporting FTE from the per-quarter revenue via the dollar path" —
[schedule.py:3182-3187](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3182-L3187))
is unachievable: there is no supporting-FTE component to shrink — the cost is the
founder.

### 1.4 Every caller
`assert_payroll_revenue_feasibility` is invoked from exactly one site,
inside `assert_post_intake_global_invariants` — [fail_fast.py:2018-2022](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L2018-L2022)
(enclosing function [fail_fast.py:1932-2044](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L1932-L2044)),
with `stage=f"{stage}_global_payroll_revenue_feasibility"`.

`assert_post_intake_global_invariants` runs at **5 checkpoints** per system run:

| # | Caller | stage prefix | Hits gate? |
|---|--------|--------------|-----------|
| 1 | `prepare_initial_grid_for_draft` via `_assert_global_invariants_via_sequence` [runner.py:354](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L354) | `resume_checkpoint_ready` [runner.py:1517](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1517) | **YES** |
| 2 | same | `pre_quarter_grid_payroll_ready` [runner.py:1551](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1551) | **NO** — skipped by the `"pre_quarter_grid"` guard ([schedule.py:3222-3223](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3222-L3223)) |
| 3 | same | `quarter_grid_applied` [runner.py:1771](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1771) | **YES** |
| 4 | same | `quarter_grid_applied_after_feasibility_repair` [runner.py:1806](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1806) | **YES** |
| 5 | `run_finalize_post_intake_validation` via `_run_finalize_global_invariants` [finalize_post_intake.py:606-607](../../python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L606-L607), called from `_run_post_cascade_completion` [orchestrator.py:3421](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L3421) | `post_intake_finalize_validation_global` | **YES** |

`prepare_initial_grid_for_draft` is driven by the live system run via
`_run_planning_system_for_draft_unified` — [intake_consult.py:7062](../../python/api_handlers/intake_consult.py#L7062);
the finalize path is reached from `run_target_seeking_orchestrated_system_run` —
[orchestrator.py:1773](../../python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L1773).

**Conclusion §1:** the payroll gate fires uniformly, with no quarter-ramp awareness,
at 4 effective checkpoints (3 in round-1 initial grid + 1 at finalize). Sunny dies at
the **first** one (`resume_checkpoint_ready`, [runner.py:1517](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1517))
— before the cascade ever runs.

---

## 2. THE FULL VIABILITY-CHECK FAMILY

Two evaluation surfaces matter: (a) the session-time `evaluate_plan` checks
(mini_finmo + acceptance gate, what GPT sees mid-session) and (b) the realism gate
that runs inside the target-seeking solver. I inventory both, flagging for each whether
it understands "new business, give it time" or point-checks early quarters as if mature.

### 2.1 `evaluate_plan` registry
[evaluate_plan.py:68-96](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L68-L96).
Two strictness modes: `mini_finmo` (round-1) and `full_acceptance_gate` (structurally
complete) — [evaluate_plan.py:473](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L473).
Cash-related checks are filtered out of the session view —
[evaluate_plan.py:53-58](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L53-L58).

### 2.2 mini_finmo viability checks — `_eval_viability_checks`
[mini_finmo.py:354-457](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L354-L457).

| Check | Quarters | Ramp-aware? | file:line |
|-------|----------|-------------|-----------|
| `ebitda_positive_by_q11` | Q11 only (`q11_em >= 0`) | **YES (by deadline)** — early EBITDA un-checked; only Q11 must be ≥0 | [mini_finmo.py:383-385](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L383-L385) |
| `ebitda_recovery_trend_q5_q11` | Q5→Q11 delta | **YES** — rewards recovery, allows weak Q5 | [mini_finmo.py:386-388](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L386-L388) |
| `ebitda_margin_q20_holds_or_improves_vs_q11` | Q11 vs Q20 | n/a (mature-window stability) | [mini_finmo.py:389-393](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L389-L393) |
| `gross_margin_supports_ebitda_recovery` | Q5 vs Q11 | **YES** (trend, not level) | [mini_finmo.py:396-398](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L396-L398) |
| `fixed_cost_burden_reduced_or_scaled_by_q11` | Q1 vs Q11 (must fall) | **YES** (improvement, not level) | [mini_finmo.py:400-402](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L400-L402) |

Every mini_finmo viability check is **already Q11-anchored / trajectory-shaped** — none
point-checks an early-quarter *level*. They embody "give the business time."

### 2.3 mini_finmo stage_ramp coherence — `_eval_stage_ramp_coherence_checks`
This is where the **per-quarter ramped floor** lives, and it is the model Fix #1 should
extend.

- `stage_ramp_ni_floor_respected`: reads a **per-quarter** floor from the stage-ramp
  contract (`net_income_margin_floor` / `ni_floor`) — [mini_finmo.py:295-311](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L295-L311).
  The comment states the doctrine explicitly: **"ni_floor=0 in early quarters means
  'NI margin >= 0%'; later quarters may have ni_floor >= 0.05 or 0.07"** —
  [mini_finmo.py:292-294](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L292-L294).
  The ramp lives in the **data** (a quarter-indexed contract), not in special-casing
  inside the check. This is the cleanest "new business, give it time" pattern in the
  codebase. **Flag this as the model to extend.**
- The ratio ceilings (`cogs_max`, `marketing_max`, `rd_max`, `ga_max`) and `max_util`
  also read **per-quarter** bounds from the same contract —
  [mini_finmo.py:261-335](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L261-L335).
  Same pattern: the band is quarter-indexed, so the ramp is expressible without
  point-checking early quarters as if mature.

### 2.4 Acceptance gate — `verify_run_acceptance`
[gate.py](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py) (registry mirrored in [evaluate_plan.py:83-95](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L83-L95)).

| Check | Quarters | Ramp-aware? | file:line |
|-------|----------|-------------|-----------|
| `net_income_trajectory_viable` | Q5 & Q11 (`q11>=0` AND `q11-q5>=2pp`) | **YES** — Q5 may be deeply negative; only Q11≥0 + improvement | [gate.py:416-441](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416-L441) |
| `revenue_not_flat_q1_q10` | Q1–Q10 (CoV / growth) | partial — uniform Q1-Q10 window but a *growth* test, not a level test | [gate.py:332-372](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L332-L372) |
| `cash_legitimate_q1_q10` | Q1–Q10 (`cash>=0 or interest>0`) | **NO** (uniform) — but **filtered out of the session view** ([evaluate_plan.py:53-58](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L53-L58)) | [gate.py:375-402](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L375-L402) |
| `current_assets_positive_q1_q10` | Q1–Q10 (`>0`) | **NO** (uniform) — also cash-filtered | [gate.py:614-631](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L614-L631) |
| `cash_health_operational_not_debt_funded` | Q11 (`interest/rev<=5%`) | n/a — cash-filtered from session | [gate.py:444-465](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L444-L465) |
| `balance_sheet_growth_plausible` | Q20 (5× opex caps) | n/a (mature) — cash-filtered | [gate.py:548-579](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L548-L579) |
| Universal viability trajectory checks (`loss_window_funded_through_q5`, `ebitda_positive_by_q11`, etc.) | trajectory | mixed; `loss_window_funded_through_q5` is **explicitly early-ramp tolerant** | realism `trajectory_check` rows, see §2.5 |

The non-ramp-aware acceptance checks (`cash_legitimate`, `current_assets_positive`)
are level tests on early quarters — but they are **filtered out of the session-time
evaluate_plan view** ([evaluate_plan.py:53-58](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L53-L58),
[:393-394](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L393-L394))
and, being cash-side, are satisfied for Sunny as long as the early loss is funded by
debt/equity. They are not the blocker.

### 2.5 Realism gate — the one that point-checks early-quarter *levels*
This is the check family that, like the payroll gate, can bind on an early-quarter level —
but unlike the payroll gate it is **already partly stage-aware**.

- `ebitda_margin` realism metric: `gate_kind="hard_fail"`, `aggregation` defaults to
  **`per_quarter`**, `deadline_quarter=11` — [realism/lookup.py:597-627](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L597-L627).
- `per_quarter` aggregation iterates **Q1..Q20** — [validator.py:638-640](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L638-L640).
  So `ebitda_margin` **is** checked in Q1–Q4 (skipped only when revenue is 0 via
  `skip_when_revenue_zero`; Sunny has ~$23k revenue, so it is checked).
- The early-quarter floor is **stage-shifted**, not flat: `_profitability_floor_for_quarter`
  selects `profitability_floor_q1_q4` / `_q5_q10` / `_q11_q20` by quarter band —
  [validator.py:323-345](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L323-L345) —
  and raises the effective band floor to it — [validator.py:988-994](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L988-L994).
- The floor values are stage- and mode-specific: startup Q1-Q4 floors run from **−0.20
  to −0.40** depending on mode — [post_intake_mapping.py:4805-4863](../../python/client_intake_and_finmo/post_intake_mapping.py#L4805-L4863)
  (e.g. `profitability_floor_q1_q4_startup: -0.20` at [:4810](../../python/client_intake_and_finmo/post_intake_mapping.py#L4810),
  `-0.40` at [:4834](../../python/client_intake_and_finmo/post_intake_mapping.py#L4834)).
- A below-band `hard_fail` is downgraded to a warning only if its derived issue code is
  in the mode's `tolerated_issue_codes` — [validator.py:1021-1031](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L1021-L1031).
- `net_income_margin` realism metric is `gate_kind="skip"` —
  [realism/lookup.py:656-674](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L656-L674) —
  so NI margin is **not** gate-enforced; only `ebitda_margin` binds.

**Inconsistency surfaced:** the entire mini_finmo viability set (§2.2), the stage_ramp
floors (§2.3), `net_income_trajectory_viable` (§2.4), `loss_window_funded_through_q5`,
and the realism `ebitda_margin` floor (§2.5) all already encode "new business, give it
time" — either by Q11-anchoring, trajectory-shaping, per-quarter ramped contracts, or
stage-shifted floors. **Only the payroll/revenue gate (§1) point-checks early quarters
against a single mature band with no ramp at all.** It is the outlier.

---

## 3. THE CHAIN QUESTION

If we make ONLY the payroll gate startup-aware, does Sunny complete — or does it trip
the next check on the same early-quarter basis?

Reasoning from Sunny's Q1–Q4 numbers (founder payroll ≈ 146% of revenue):

- **EBITDA margin in early quarters.** EBITDA = revenue − COGS − operating expense,
  and payroll is part of operating expense. With payroll alone at 146% of revenue,
  `ebitda_margin <= 1 − 1.46 = −0.46` from payroll alone, and worse once COGS and other
  opex are subtracted. So Sunny's early-quarter EBITDA margin is roughly **−50% to −80%+**.
- **The realism `ebitda_margin` floor binds here.** It is checked per-quarter in Q1–Q4
  ([validator.py:638-640](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L638-L640)),
  `gate_kind="hard_fail"` ([realism/lookup.py:606](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L606)),
  with an effective floor of −0.20 to −0.40 in Q1-Q4
  ([post_intake_mapping.py:4810](../../python/client_intake_and_finmo/post_intake_mapping.py#L4810),
  [:4834](../../python/client_intake_and_finmo/post_intake_mapping.py#L4834)).
  A −50%+ EBITDA margin is **below even the deepest startup floor (−0.40)** → realism
  hard_fail, surfaced to acceptance as `realism_gate_no_hard_fail_violations`
  ([evaluate_plan.py:88](../../python/client_intake_and_finmo/post_intake_amalgamated/evaluate_plan.py#L88)),
  unless the active mode's `tolerated_issue_codes` downgrades it
  ([validator.py:1021-1031](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L1021-L1031)).

**Therefore Fix #1 is a CHAIN, not a single fix** — with an important qualification:

1. The **payroll/revenue gate (§1)** is the first and hardest blocker; Sunny dies there
   at `resume_checkpoint_ready` ([runner.py:1517](../../python/client_intake_and_finmo/post_intake_initial_grid/runner.py#L1517))
   before anything else runs.
2. After that is fixed, the next blocker on the *same early-quarter basis* is the
   realism **`ebitda_margin`** hard_fail (§2.5). Critically, that check is **already
   stage-aware** — the problem is not that it ignores the ramp, but that a founder draw
   at 146% of revenue produces a loss **deeper than any reasonable ramp allowance** (it
   blows past −0.40).
3. The Q11-anchored / trajectory checks (mini_finmo §2.2, `net_income_trajectory_viable`
   §2.4) should **pass** for Sunny *if* revenue matures enough by Q11 that payroll/revenue
   and EBITDA normalize. They do not point-check Q1–Q4 levels, so they are not part of
   the chain.

So the chain is **two binding checks** (payroll gate + realism `ebitda_margin`), and the
shared root cause is the same: a fixed, non-scalable founder draw measured against
nascent revenue. A fix that only relaxes the *timing* of the band (grace window /
convergence) clears the payroll gate but leaves the realism `ebitda_margin` floor
standing, because that floor is about loss *magnitude*, not timing. This is the central
finding for choosing an option in §4.

---

## 4. OPTIONS (make checks startup-aware without gutting them)

All three must preserve the ability to catch a business that is upside-down *forever*.

### Option A — Early-quarter grace window
Band not enforced during a ramp window (e.g. Q1–QN), enforced once revenue matures.

- **Entails:** make the payroll gate's per-quarter loop
  ([schedule.py:3120-3129](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3120-L3129))
  skip ratio enforcement for `quarter_index <= N` (N from policy), still enforcing N+1..Q20.
- **Existing pattern to copy:** the stage-ramp **per-quarter contract** (§2.3,
  [mini_finmo.py:295-311](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L295-L311))
  — express the band as quarter-indexed data (floor/ceiling per quarter) rather than one
  constant, exactly as `ni_floor` does (0 early, higher later). Also mirrors the
  realism stage-shifted bands ([validator.py:323-345](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L323-L345)).
- **Blast radius:** payroll gate only, but **insufficient alone** — it does not touch the
  realism `ebitda_margin` floor (§3 chain). Also blunt: it stops *catching* an
  upside-down ramp during the window unless paired with a maturity check.
- **Sunny:** clears the payroll gate; **still trips realism `ebitda_margin`**.

### Option B — Trajectory / convergence test
Require the ratio to **converge** into band by a steady-state quarter, not be in-band
every quarter.

- **Entails:** replace the per-quarter level test
  ([schedule.py:3128-3129](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3128-L3129))
  with: "ratio must be ≤ max_allowed by quarter K, and monotonically approaching band
  before K." Permanently-upside-down businesses (ratio never converges) still fail.
- **Existing pattern to copy:** the mini_finmo trajectory checks (§2.2) —
  `ebitda_recovery_trend_q5_q11` ([mini_finmo.py:386-388](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L386-L388))
  and `net_income_trajectory_viable` ([gate.py:416-441](../../python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416-L441))
  both test "Q11 acceptable AND improving from Q5" rather than every-quarter levels.
- **Blast radius:** payroll gate only; conceptually the best fit for "ramping startup vs
  permanently unviable." But again **does not by itself clear the realism `ebitda_margin`
  floor** — convergence is a timing concept, and the realism floor is a magnitude floor.
- **Sunny:** clears the payroll gate if revenue converges payroll/revenue into band by
  Q11; **still trips realism `ebitda_margin`** in Q1–Q4.

### Option C — Founder-draw / fixed-key-person carve-out
Treat non-scalable founder salary differently from scalable staffing when forming the
ratio.

- **Entails:** decompose payroll into (i) fixed founder/key-person draw and (ii) scalable
  staffing, and apply the revenue-scaled band to **scalable payroll only**; the fixed
  founder draw is checked against an absolute reasonableness bound (or against
  owner-comp norms), not a revenue ratio. The decomposition would live in the
  headcount schedule (the same `payroll_headcount` schedule the gate already reads —
  [schedule.py:3115-3116](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L3115-L3116)).
- **Existing pattern to copy:** partial — the realism layer already excludes
  `expenses::Payroll` from the EBITDA solver levers because Handler C is its canonical
  writer ([realism/lookup.py:610-619](../../python/client_intake_and_finmo/post_intake_realism/lookup.py#L610-L619)),
  i.e. payroll is already recognized as a distinct, separately-authored cost. There is
  no existing founder-vs-staff *split*, so this is the most net-new option.
- **Blast radius:** largest — touches the payroll schedule shape, the payroll gate, and
  (to fully clear the chain) the realism `ebitda_margin` interpretation, since the deep
  early EBITDA loss is *caused* by counting the founder draw against revenue. But it is
  the only option that addresses the **root cause** (§3): it is the magnitude of the
  fixed founder draw, not the timing of the band, that breaks both checks.
- **Sunny:** removing the fixed founder draw from the revenue-scaled ratio is the only
  option that plausibly clears **both** the payroll gate **and** the realism
  `ebitda_margin` floor on the same early-quarter basis.

---

## 5. RECOMMENDATION SHAPE (not a decision)

- **It is a chain of two checks, not one** (§3): the payroll/revenue gate (§1) and the
  realism `ebitda_margin` hard_fail (§2.5). Fixing only the payroll gate moves the
  failure one step downstream.
- **The defect is specifically the payroll gate's uniform band** — it is the lone check
  that point-checks early quarters against a mature band with zero ramp (§1.3). Every
  other check already understands the ramp, via Q11-anchoring, trajectory tests, or
  per-quarter/stage-shifted bands.
- **The model to extend is the per-quarter ramped contract** used by `ni_floor` and the
  stage-ramp ceilings (§2.3, [mini_finmo.py:292-311](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py#L292-L311))
  and the stage-shifted realism floors ([validator.py:323-345](../../python/client_intake_and_finmo/post_intake_realism/validator.py#L323-L345),
  [post_intake_mapping.py:4805-4863](../../python/client_intake_and_finmo/post_intake_mapping.py#L4805-L4863)):
  express the payroll band as quarter-indexed data rather than one constant. This is the
  least-disruptive shape and is consistent with existing doctrine.
- **But timing-only fixes (A/B) do not clear the chain.** Because the realism floor is a
  *magnitude* floor and Sunny's founder-draw loss exceeds even −0.40, a grace window or
  convergence test on the payroll gate alone leaves `ebitda_margin` failing. The root
  cause is the fixed founder draw measured against nascent revenue — which points toward
  **Option C (founder-draw carve-out)**, possibly layered on top of a B-style
  convergence test for the scalable remainder.
- **This is therefore a family-wide policy question, not a one-check patch.** The narrow
  framing ("make the payroll gate startup-aware") is necessary but not sufficient. The
  decision to make is whether to: (a) ramp the payroll band by quarter (clears §1 only),
  or (b) additionally carve out the fixed founder draw from revenue-scaled viability so
  both §1 and §2.5 stop penalizing a legitimately-ramping owner-operated startup —
  while both still catching a business whose *scalable* economics never converge.

No check should be gutted: the permanently-upside-down business must still fail. Every
option above retains a maturity/convergence/absolute bound that does so.
