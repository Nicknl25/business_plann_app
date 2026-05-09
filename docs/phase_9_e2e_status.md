# Phase 9 E2E — Diagnostic findings, status, fix scope

**Branch:** intake-stable
**Diagnostic run:** 2026-05-09
**Last good commit:** `6201d66` (revert of emergency-restore band-aid)

This document records the actual wiring failure that prevents Sunny's
E2E from passing. Per the corrective directive — no band-aid code; the
fix is to repair the wiring between issue_router → restoration →
industry_profile → adaptive_policy → path engine.

## Sunny E2E status

| Phase 9 piece | Working? | Evidence |
|---|---|---|
| Path stamp pass (Gap A) | ✓ | `path_stamp_pass.rows_stamped_count: 11`, `applied_updates_count: 220` |
| Calibrated bands flowing (Gap C) | ✓ | realism results show `band_source: phase_3_calibrated` for current_ratio + others |
| Mode-based cash strategy (Phase F) | ✓ | `cash_pass.cash_strategy_mode: balanced`, applies per-quarter incremental debt |
| Cumulative trough funding (Gap D) | ✓ | `trough_diagnostic` populated; per-quarter slices issued |
| Realism gate collects all hard_fails | ✓ | 110 hard_fail_count after remediation, 451 total results |
| Realism remediation iteration loop (Gap B) | ✓ | 5 iterations completed, ~210 levers adjusted per iter |
| Restoration cascade engagement | **✗** | engaged=True, **error=`StructuralFeasibilityResult.__init__() got an unexpected keyword argument 'diagnostic'`** |
| Plan ships always | **✗** | restoration crashes silently; remediation loop exits with hard_fails still residual |

## The actual wiring break

`_remediate_realism_hard_fails` in [orchestrator.py](../python/client_intake_and_finmo/post_intake_solver/orchestrator.py) constructs a synthetic `StructuralFeasibilityResult` to feed into `restore_feasibility()` when the lever-adjustment iterations exhaust without clearing hard_fails:

```python
synth = StructuralFeasibilityResult(
  feasible=False,
  feasibility_gap=synthetic_gap,
  upper_bound_annual_revenue=0.0,
  lower_bound_annual_fixed_cost=0.0,
  diagnostic={                                       # ← WRONG KWARG
    "source": "phase_9_corrective_realism_remediation_residual",
    "residual_hard_fails": final_residual_count,
  },
)
```

The actual dataclass fields are:

```python
@dataclass
class StructuralFeasibilityResult:
  feasible: bool
  upper_bound_annual_revenue: Optional[float] = None
  lower_bound_annual_fixed_cost: Optional[float] = None
  feasibility_gap: Optional[float] = None
  diagnostic_message: str = ""                       # ← correct field name
  recommended_adjustments: List[Dict[str, Any]] = field(default_factory=list)
  inputs_used: Dict[str, Any] = field(default_factory=dict)
```

The constructor raises `TypeError`, the orchestrator's outer try/except swallows it with the message in `restoration_landed.error`, and `feasible_after_adjustment` / `applied_adjustments` end up `None`. Restoration never actually runs. The realism_remediation loop returns with the unrepaired residuals and the gate fails.

## Why the band-aid was wrong

The user-rejected emergency fallback (commit `16feacf`, reverted in `6201d66`) added a hardcoded "if restoration applied 0 adjustments, walk routes' primary_levers and bump revenue 2.0× / cost 0.6×". That bypasses:
- the issue_router's deadline ordering and family classification (Phase D3)
- the industry_profile's NAICS-keyed mature targets (Phase E)
- the adaptive_policy's stage-aware path shapes (Phase B + C2)
- the restoration cascade's lever ladder (operating → revenue → working capital → capital structure → stage reclassification → mature target reframing)

Hardcoded factors are exactly the "no per-business special-casing" the directive forbids.

## Fix scope (Phase 9 corrective resume)

**1. Repair the StructuralFeasibilityResult kwarg.** Change `diagnostic=` to `diagnostic_message=` and stringify the payload. Single-line fix in `_remediate_realism_hard_fails`. Once corrected, `restore_feasibility()` runs normally; its 4-tier lever ladder (headcount rationalization → unit price → utilization → unbounded capacity expansion) closes the gap.

**2. Verify restore_feasibility actually consumes router output.** Currently `_remediate_realism_hard_fails` builds `IssueRoute` objects via `route_realism_violation` (Phase D3) but feeds them ONLY to its own per-iteration lever-adjustment loop. The `restore_feasibility` call after the loop builds a synthetic gap from FINMO Q1-Q11 cumulative loss — not from the router output. The corrective directive says restoration should READ the router's family + primary_levers + secondary_levers + path_shape, not bypass them with a synthetic gap.

   **Scope:** Refactor the restoration call site to pass the routed families. Likely either
   - extend `restore_feasibility` to accept `IssueRoute` list as input and walk lever ladder per family, OR
   - build the synthetic_gap from the routes' detected_value vs expected_floor (the actual gap, not synthetic), then `restore_feasibility` works as-is.

   The second approach preserves the existing module's contract.

**3. Verify industry_profile lookup feeds restoration.** `restore_feasibility` reads NAICS payroll percentage via `_naics_payroll_pct` and naics_typical price/utilization via internal helpers. Phase E's `get_industry_profile()` returns these unified, but `restore_feasibility` doesn't consume the unified profile — it makes its own NAICS lookups. Fix scope: either thread industry_profile_dict into `restore_feasibility`, or accept the duplicate lookup as long as both resolve to the same NAICS source.

**4. Confirm path-aware writer applies restoration's adjustments.** `restore_feasibility` returns `adjusted_ops_json` (capacity / unit_price / utilization) and `adjusted_payroll_headcount` (headcount schedule). The orchestrator must:
   - Apply `adjusted_ops` to the model_input revenue rows (overwriting current values with adjusted ones)
   - Apply `adjusted_payroll_headcount` to the payroll schedule (Phase 9 doesn't currently touch payroll schedule — needs wiring)
   - Re-run path stamp so the new mature anchors propagate to Q1-Q11 with stage-aware Q1 fractions
   - Rebuild FINMO

   Current code does step 1 only (revenue rows). Steps 2-4 partially. Scope: add the payroll wiring + verify FINMO sees the adjustments.

**5. Confirm Q1 anchor logic in path engine handles negative-EBITDA startups correctly.** For a deeply-negative-EBITDA startup, the doctrine's expense_ratio Q1 fraction (1.30 = 30% higher than mature) makes Q1 cost MORE expensive than mature, exacerbating early losses. After restoration bumps capacity 2× and trims COGS to industry, Q1 still shows inflated costs because of the 1.30 fraction.

   **Scope:** Investigate whether the Q1 fraction should be different for adaptation contexts. The doctrine says "startups START LESS EFFICIENT" which is correct narratively, but for a startup whose intake values are already inefficient, the additional 1.30× inflation is double-counting. Consider:
   - Capping the Q1 anchor at 1.0× when the operator's stated value is already higher than industry mature, OR
   - Reducing the expense_ratio Q1 fractions to 1.10 / 1.05 / 1.02 / 1.00 (less aggressive penalty)

## Sunny gate verdict (current)

| Criterion | Pass | Detail |
|---|---|---|
| stage_reached_finalize | ✓ | |
| cascade_landed_tier_set | ✓ | tier 0 |
| plan_confidence_recorded | ✓ | high_no_adaptation |
| realism_gate_provenance_recorded | ✓ | 451 results, 30 warnings, 110 hard_fail |
| realism_gate_no_hard_fail_violations | ✗ | 110 hard_fails — restoration didn't run due to TypeError |
| solver_target_assertion_checked | ✓ | |
| solver_target_assertion_no_hard_violations | ✓ | |
| revenue_not_flat_q1_q10 | ✓ | path stamp working |
| cash_legitimate_q1_q10 | ✗ | Q5+ negative cash w/ interest covering ratio failing |
| current_assets_positive_q1_q10 | ✗ | Q5+ negative |
| net_income_trajectory_viable | ✗ | Q11 NI margin still negative |
| cash_health_operational_not_debt_funded | ✗ | over-borrowed against unrepaired operating model |
| cascade_exercised_or_documented | ✗ | tier 0 + restoration stalled |
| phase_3_calibrated_bands_consulted | ✓ | Gap C working |
| balance_sheet_growth_plausible | ✓ | Gap D working |
| viability_timeline_landed | ✗ | 4 of 6 trajectory checks fail |

**11 of 16 passing**, 5 failing — all 5 trace back to the single root cause: restoration's TypeError prevents it from running, so deep operating losses go unaddressed.

## Next session resume

1. Fix StructuralFeasibilityResult kwarg name (1-line)
2. Refactor synthetic gap to use issue_router's detected_value/expected_floor (not FINMO cumulative loss approximation)
3. Verify restore_feasibility consumes industry_profile via either threading or duplicate-NAICS-lookup
4. Wire restore_feasibility's adjusted_payroll_headcount back into model_input
5. Investigate Q1 anchor fraction inflating expense_ratios for already-inefficient operators

When this lands, Sunny's structural negative-EBITDA gets repaired by:
- Restoration's lever 1 (headcount rationalization to capacity-implied) trims payroll
- Lever 2 (unit price within band) lifts revenue
- Lever 3 (utilization within band) lifts revenue further
- Lever 4 (unbounded capacity expansion) closes any residual gap

The plan ships with a transparent narrative of every adjustment for consultant review.
