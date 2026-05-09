# Phase 9 — Operating-Side Adaptation Failure Diagnosis

**Run timestamp:** 2026-05-09
**Scope:** Why net_income_trajectory_viable / viability_timeline_landed remain failed after the cash-pass-owned-lever flat-stamp fix (commit a406eb8) and the Task 1+2 realism gate cleanup (commit aa39e89).
**Subjects:** ExpressLogix (NAICS 488 freight), Sunny, NexGen.

This is a read-only diagnostic of the cascade flow + a fix list for the
specific bugs found. The cascade DOES fire on realism hard_fails today;
the bugs below explain why the iterations don't move the model into band.

---

## Bug 1 — Trajectory-check failures never reach the cascade

**File:** [post_intake_realism/validator.py:494-552](python/client_intake_and_finmo/post_intake_realism/validator.py#L494-L552)

The validator's universal-viability rows
(`ebitda_positive_by_q11`, `ebitda_recovery_trend_q5_q11`,
`loss_window_funded_through_q5`, `no_post_recovery_relapse_q11_q20`,
`gross_margin_supports_ebitda_recovery`,
`fixed_cost_burden_reduced_or_scaled_by_q11`)
are evaluated in a separate branch:

```python
if aggregation == "trajectory_check":
    ...
    status = "in_band" if passed else "out_of_band_hard_fail"
    results.append(RealismCheckResult(...))
    # trajectory_check rows DO NOT raise RealismBandViolation; they
    # surface as hard_fail status and the cascade reads them via the
    # issue router. ...
    continue
```

The comment claims the cascade reads them via the issue router. **It
doesn't.** The `continue` skips the per-quarter band-comparison loop,
which is where `hard_fail_violations.append(...)` lives
([validator.py:951-970](python/client_intake_and_finmo/post_intake_realism/validator.py#L951-L970)).
The orchestrator's remediation function
([orchestrator.py:277](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L277))
reads ONLY `hard_fail_violations`, not `results`.

**Effect:** When `ebitda_positive_by_q11` fails (Q11 EBITDA margin < 0)
the cascade is never invoked for it. For ExpressLogix the trajectory
checks all pass (Q11 EBITDA = 37.8%), so this bug doesn't bite — but
for Sunny / NexGen with a negative Q11 EBITDA the realism cascade gets
nothing to fix, the run rolls into the acceptance gate, and
`viability_timeline_landed` simply records the failure with no
remediation trace.

**Fix:** Append the trajectory_check failure row to
`hard_fail_violations` in the same shape as the per-quarter branch so
`route_realism_violation` can resolve the family from the realism
lookup row. The deadline_quarter and primary_levers metadata is
already on the row.

---

## Bug 2 — Cascade direction is family-hardcoded, not violation-direction-driven

**File:** [post_intake_solver/orchestrator.py:386-427](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L386-L427)

```python
direction: Optional[str] = None
if floor is not None and float(detected) < float(floor):
    direction = "increase"
elif ceiling is not None and float(detected) > float(ceiling):
    direction = "decrease"
else:
    continue

family = str(route.adaptation_family or "")
family_translates_to_decrease = family in {
    "margin_compression",
    "industry_normalization",
    "balance_sheet_adaptation",
    "payroll_ratio_excess",
    "leverage_excess",
    "capital_intensity_adaptation",
}
if family_translates_to_decrease:
    applied_direction = "decrease"
elif family in {
    "ramp_adaptation",
    "operating_scale_adaptation",
    "revenue_achievability",
    "turnaround_recovery_q5_q11",
}:
    applied_direction = "increase"
else:
    applied_direction = direction
```

The first block resolves the **violation direction** (does the
metric need to move up or down). The second block then **discards it**
and writes a hardcoded direction per family.

For ExpressLogix's COGS:
- band [0.67, 1.07], target 0.87, actual 0.32 → `direction = "increase"` (cogs% too low for freight)
- family = `margin_compression` → `applied_direction = "decrease"`
- `_GAP_B_DECREASE_FACTOR = 0.85` → COGS lever → 0.85× current → drives COGS *further down*

The rationale in the inline comment ("the metric is a ratio of cost /
revenue; remediation is always to DECREASE cost levers") encodes the
common case (cost too high) and silently breaks the inverse case
(cost too low for industry — too profitable). Same structural bug
appears in the revenue-family branch: a margin metric *above* ceiling
(too profitable) routes to `turnaround_recovery_q5_q11`, the cascade
applies `applied_direction = "increase"` to revenue levers, and
revenue rises further — making EBITDA more out-of-band, not less.

**Effect on ExpressLogix:** the cascade burns its 5 iterations applying
the wrong-direction lift to COGS / Marketing / G&A, the realism
hard_fails don't drop, restoration_landed engages, and the model that
ships out is what restoration produced (which is path-shape-preserved
via `apply_path_stamp_pass` — but that pulls toward
`industry_target` regardless of cascade lifts, making the cascade
iterations effectively no-op for industry-targeted levers).

**Effect on Sunny / NexGen (negative Q11 EBITDA):** even when EBITDA
margin is below floor (`direction = "increase"` for the metric),
applying `applied_direction = "increase"` to the cost levers bundled
into the same primary_levers list raises costs further, dragging
EBITDA back down. Same primary_levers list mixes COGS / Marketing /
G&A / Payroll with Unit Price / Utilization — the family direction
is one-size-fits-all when these levers actually move EBITDA in
opposite directions.

**Fix sketch:** classify each primary_lever as cost-side or
revenue-side, then map (violation_direction × lever_kind) to the
adjustment factor:

| metric direction needed | cost lever | revenue lever |
|---|---|---|
| increase metric (e.g. raise EBITDA) | decrease cost | increase revenue |
| decrease metric (e.g. lower COGS%) | decrease cost | increase revenue |

For cost-ratio metrics the rule "decrease cost lever when metric
is above ceiling" covers it; for margin metrics, cost-down +
revenue-up jointly raises margin. The same direction never applies
to both lever kinds simultaneously.

---

## Bug 3 — Path stamp's industry_target overrides cascade lifts

**File:** [post_intake_adaptive_planning/path_engine.py:739-743](python/client_intake_and_finmo/post_intake_adaptive_planning/path_engine.py#L739-L743)

```python
industry_target = _industry_target_for_lever(lever_id, industry_profile)
if industry_target is not None and industry_target > 0:
    target_anchor = float(industry_target)
else:
    target_anchor = float(mature_value)
```

After `_remediate_realism_hard_fails` lifts (or drops) the lever's
mature anchor by `_GAP_B_INCREASE_FACTOR=1.15` /
`_GAP_B_DECREASE_FACTOR=0.85`, it calls `apply_path_stamp_pass` to
re-shape the path. The path engine reads
`mature_value = values_list[-1]` (the lifted anchor) but immediately
overrides with `industry_target` whenever the IndustryProfile has
a band for the lever. So the cascade's per-iteration lift is
**no-op for industry-targeted levers**: COGS, Marketing, R&D, SGA,
Lease, Payroll, Depreciation, Taxes, AR/AP/Inventory days, Prepaid,
Deferred (the full set in
[path_engine.py:629-643](python/client_intake_and_finmo/post_intake_adaptive_planning/path_engine.py#L629-L643)).

This is the right call when industry_target is the actual destination
(NAICS-median COGS%, etc.) — Bug 2 is what makes it a problem,
because Bug 2 routes ExpressLogix's "COGS too low" to a "decrease COGS"
applied_direction, but the path stamp keeps writing
`industry_target = 0.87` regardless. Net effect: cascade's iterations
do nothing visible, and the run lands at industry_target on the lever
path. The realism gate then sees the lever at industry_target but the
*FINMO output* (cogs / revenue) still off-band because revenue got
re-shaped too and the ratio depends on both.

This isn't a separate bug — it's why fixing Bug 2 alone won't fix
ExpressLogix's COGS problem. The deeper question is whether
ExpressLogix's intake is actually freight-shaped (it shows software-
margin economics on a NAICS-488 classification). That's a triage
question outside the cascade.

---

## Bug 4 — Acceptance gate has stricter thresholds than realism trajectory

**File:** [post_intake_acceptance/gate.py:416-441](python/client_intake_and_finmo/post_intake_acceptance/gate.py#L416-L441)

`net_income_trajectory_viable`: requires `q11_ni_margin >= 0` AND
`q11_ni_margin - q5_ni_margin >= 0.02`.

The closest realism trajectory check is
`ebitda_recovery_trend_q5_q11` (
[formulas.py:718-730](python/client_intake_and_finmo/post_intake_realism/formulas.py#L718-L730)
), which returns `q11_ebitda_margin - q5_ebitda_margin` and the
validator passes it when the value is `>= 0`. That's:
- A different metric (EBITDA margin vs. NI margin)
- A different threshold (0 vs. 0.02)

For ExpressLogix the test run shows
`q5_ni_margin=0.2685, q11_ni_margin=0.2867, delta=0.0182, threshold=0.02`
— the realism trajectory check passes (`q11_ebitda_margin - q5 >= 0`)
because EBITDA margin moved more than NI margin between Q5 and Q11
(interest + tax timing pushes NI delta < EBITDA delta). The
acceptance gate fires on a delta the realism cascade never measures,
so even a perfectly-tuned cascade can't pre-empt this acceptance fail.

**Triage choice:** either (a) tighten the realism trajectory check to
match the acceptance threshold so the cascade fires earlier, or (b)
accept the gap and let acceptance fail informationally. The user's
call. No code change here pending that decision.

---

## Restoration cascade

**File:** [post_intake_solver/orchestrator.py:581-605](python/client_intake_and_finmo/post_intake_solver/orchestrator.py#L581-L605)

Restoration engages when `_remediate_realism_hard_fails` exits with
residual hard_fails. Per the comment "restoration always lands" — the
restoration cascade's lever ladder ends in unbounded capacity expansion
so the gap is closed by definition. Whatever it produces is what
ships in the model.

In ExpressLogix's last run with `final_residual_count > 0`, restoration
is the actual author of the post-cash final state. Because Bug 3
keeps cost levers at industry_target and Bug 2 misdirects the
intermediate iterations, restoration is closing against the wrong
baseline. The "applied_adjustments" diagnostic the user asked for
lives in `restoration_landed_diag.applied_adjustments` on the
planning_run_json blob; we'd need to read the persisted
`planning_run_json.realism_remediation.restoration_landed_diag` to
get exact counts (the test run report references them but doesn't
quote them).

---

## Fix list (this PR)

1. **[Bug 1]** Append trajectory_check failures to `hard_fail_violations`
   in `validator.py` so the cascade can route them. Strict scope —
   no other validator behavior changes.
2. **[Bug 2]** Replace the family-keyed `applied_direction` with a
   per-lever decision: classify each primary_lever as cost-side
   (`expenses::*`, `balance_sheet::*Days`) or revenue-side
   (`revenue::*`); apply the factor that lifts the metric in the
   direction it needs to move.

**Out of scope this PR:**
- Bug 3 architectural change (path-stamp authority over cascade
  lifts). The cleanest fix would be a `cascade_iteration_anchor`
  override in the path engine, but that's a larger surface change
  and the acceptance gate's failures aren't blocked on this for
  ExpressLogix specifically.
- Bug 4 acceptance/realism threshold alignment — needs user decision.
- ExpressLogix triage on whether intake is genuinely freight-shaped
  (NAICS-488 vs. service-margin economics).
