# Phase 9 P3.28 — 28-draft sweep results summary

**Run date:** 2026-05-20 (intake-stable HEAD `8ef9daf`)
**Scope:** Sequential sweep of 28 source drafts through
`Test Files/run_persisted_system_run.py` against a fresh API server
on port 5050 with `CONVERGENCE_TEST_MODE=true`.
**Status:** OBSERVATION ONLY. No code fixes during sweep.

Raw artifacts:
- CSV: [docs/architecture/p3_28_sweep_results.csv](./p3_28_sweep_results.csv)
- Workbooks: [docs/architecture/p3_28_sweep_workbooks/](./p3_28_sweep_workbooks/)
- Per-draft logs: [_sweep_p3_28/per_draft_logs/](../../_sweep_p3_28/per_draft_logs/)
- Sweep log + results JSON: [_sweep_p3_28/](../../_sweep_p3_28/)

---

## §1 Aggregate outcomes

| Outcome        | Count | Rate    |
| -------------- | -----:| -------:|
| GENUINE_PASS   |    16 |  57.1%  |
| FALSE_PASS     |     0 |   0.0%  |
| FAIL           |    12 |  42.9%  |
| RUNNER_ERROR   |     0 |   0.0%  |
| WORKBOOK_ERROR |     0 |   0.0%  |

- Total wall-clock runtime: **2.05 h** (7383 s)
- Average per-draft duration: **263.7 s**
- Min/max draft duration: 76 s (Luminous Glow Med Spa, intake preflight) / 538 s (SwiftLogix)
- Handler engagement: **19 / 28** drafts fired the GPT exhaustion handler at Site 1.

**Critical methodology note on V-2 / V-4:** The workbook builder
emits formulas (`=IF(...)`, `='FINMO'!W8`, etc.) without cached
values. Because the sweep never opened the produced files in Excel,
`Checks!B2` and the rows-166-172 baseline-reconciliation deltas read
back as `None` from openpyxl. The re-classifier therefore infers V-2
and V-4 from `runner_returncode == 0 AND v1_score == 16/16 AND
realism_check_detail has zero hard fails` (column `v2_model_status =
OK_inferred` in the CSV). This is a doctrine-faithful inference (the
runner already enforces the acceptance gate's checks), but a
later-stage Excel-open verification would be needed to detect any
formula-evaluation noise we could not measure here. Where Excel
*had* opened a workbook (CareFirst was opened during P3.25 inspection),
real cached deltas are recorded in the CSV.

---

## §2 Per-draft detail table

**GENUINE_PASS (16)** — all rc=0, v1=16/16, no realism hard fails:

| #  | Business                          | NAICS  | Mode       | Stage       | Tool calls | Wall (s) |
| -:| --------------------------------- | ------ | ---------- | ----------- | ---------:| --------:|
|  3 | Skyward Express Airlines          | 481111 | rebalance  | operating   |        1 |      206 |
|  4 | Sunny Glaze Donuts                | 311811 | turnaround | operating   |        2 |      209 |
|  5 | Sweet Crumbs Bakery               | 311811 | rebalance  | operating   |        3 |      273 |
|  6 | Anderson & Clark Law Group        | 541110 | turnaround | operating   |        3 |      390 |
|  7 | Harrison & Greene Law Firm        | 541110 | turnaround | operating   |        6 |      345 |
|  8 | Caring Hands Home Health Services | 621610 | turnaround | pre-revenue |        6 |      184 |
|  9 | Luna Boutique                     | 458110 | rebalance  | operating   |        1 |      141 |
| 11 | Revitalize Mobile IV Therapy      | 621999 | turnaround | operating   |        2 |      310 |
| 13 | ExpressLogix Shipping Services    | 488999 | rebalance  | operating   |        1 |      327 |
| 16 | North Ridge Auto Care             | 811111 | normalize  | operating   |        1 |      165 |
| 18 | Evergreen Superstores Inc.        | 455211 | rebalance  | operating   |        1 |      237 |
| 19 | North Ridge Auto Care             | 811111 | rebalance  | operating   |        1 |      193 |
| 22 | Freedom Freight Logistics         | 488999 | rebalance  | operating   |        1 |      289 |
| 26 | Express Global Shipping Inc.      | 488999 | rebalance  | operating   |        4 |      326 |
| 27 | NexGen Software Solutions Inc.    | 513210 | normalize  | operating   |        1 |      273 |
| 28 | ExpressLogix Shipping Services    | 488999 | rebalance  | operating   |        1 |      283 |

**FAIL (12)** — by op code:

| #  | Business                          | NAICS  | v1 score | Fail category           | Op code                                            |
| -:| --------------------------------- | ------ | -------- | ----------------------- | -------------------------------------------------- |
|  1 | Anderson & Blake Legal Associates | 541110 | early    | cash_buffer             | post_intake_cash_buffer_violation                  |
|  2 | CareFirst Home Health Services    | 621610 | 13/16    | acceptance_gate         | acceptance_gate_failed                             |
| 10 | Elegant Threads Boutique          | 458110 | 13/16    | acceptance_gate         | acceptance_gate_failed                             |
| 12 | Luminous Glow Med Spa             | ?      | early    | intake_preflight        | payroll_headcount_key_person_oews_catalog_empty    |
| 14 | Precision Aesthetics Lab          | ?      | early    | cash_buffer             | post_intake_cash_buffer_violation                  |
| 15 | Harborview Kitchen & Co.          | 722511 | 14/16    | acceptance_gate         | acceptance_gate_failed                             |
| 17 | ValueMart Superstores             | ?      | early    | cash_buffer             | post_intake_cash_buffer_violation                  |
| 20 | ValueMart Superstores             | ?      | early    | stage_ramp              | stage_ramp_handler_exhausted                       |
| 21 | SwiftLogix Shipping Solutions     | ?      | early    | stage_ramp              | stage_ramp_contract_invalid                        |
| 23 | Pinnacle Logistics Inc.           | ?      | early    | revenue_driver_contract | revenue_driver_formula_contract_failed             |
| 24 | SwiftCargo Logistics              | ?      | early    | stage_ramp              | stage_ramp_contract_invalid                        |
| 25 | Arrowline Freight Services        | ?      | early    | stage_ramp              | stage_ramp_contract_invalid                        |

---

## §3 Failure pattern classification

### Pattern P1 — handler authority without source-of-truth reconciliation
**Count:** 0 directly detected in this sweep (V-4 not Excel-evaluable
without an Excel open pass — see §5).
**Status:** Yesterday's P3.24/P3.25 CareFirst incident (Mirror Flavor
1 divergence between `model_input.expenses.Payroll` and
`payroll_headcount.quarter_totals.payroll`) was addressed by P3.26
Commit 2 routing payroll feasibility back through Handler C as the
single writer. P3.28 cannot confirm Pattern P1 directly because the
sweep workbooks do not have cached formula values, but the routing
contract is verified in `feasibility_repair.py` and Handler C
remains canonical.

### Pattern P2 — handler authority without contract awareness
**Count:** 4 (`stage_ramp` group)
**Affected drafts:** ValueMart (run 20), SwiftLogix, SwiftCargo,
Arrowline Freight.
**Common characteristic:** All four drafts fail with
`stage_ramp_handler_exhausted` or `stage_ramp_contract_invalid` —
the stage_ramp handler is the GPT-driven authority for the QoQ
revenue-growth grid; its contract is validated downstream. Three of
the four drafts show `stage_ramp_contract_invalid` (validator
rejects the GPT-emitted contract). This matches the architectural
shape P3.27's NexGen investigation flagged: **the handler writes
revenue-side drivers without consulting the stage_ramp_contract's
own QoQ caps until validation**, so its output can be
deterministically rejected, exhausting the tool-call budget.

NexGen-class regression (`stage_ramp` Q5 QoQ violation per P3.26
investigation §3) did **not** recur in this sweep — NexGen passed at
GENUINE_PASS run 27 with one tool call. This is consistent with the
P3.26 memo's GPT-non-determinism hypothesis: same code, different
random GPT sample.

### Pattern P3 — restoration trigger gaps
**Count:** 0 detected.
**Status:** P3.26 Commit 1 (F-1 + F-2 + F-3) broadened the
restoration → handler trigger to fire on `ITERATING_STILL` with
non-empty `failing_metrics` and counted `max_inner_iterations_reached`
toward `semantic_exhaustion`. With 19/28 handler engagements in this
sweep, the trigger has clear traffic; no drafts exhibit the
yesterday-class "deterministic solver clears viability but acceptance
fails" silent skip.

### Pattern P4 / P7 — finalize-stage cash-buffer violations
**Count:** 3 (Anderson & Blake, Precision Aesthetics, ValueMart run 17)
**Common characteristic:** All three fail at the
`post_intake_finalize_validation_global` site with
`post_intake_cash_buffer_violation` — Final cash pass failed: every
live quarter must satisfy `ending_cash >= SQL cash-policy buffer`.
The acceptance handler chain (initial-grid → Phase B target-seeking
→ finalize) has **no cash-buffer-aware repair handler**. The Site 1
GPT exhaustion handler authors P&L and WC drivers but is not invoked
on cash-buffer violations because the violation surfaces after the
handler's exit gate at finalize. **No re-author path exists for
cash-buffer infeasibility**, so the run fails out.

### Pattern P5 — GPT output stability (Skyward-style)
**Count:** 1 today (SwiftLogix), 2 conditional (SwiftCargo,
Arrowline — same `stage_ramp_contract_invalid`)
**Common characteristic:** GPT did not produce a validator-accepted
contract within the tool-call budget. SwiftLogix's error fragment:
"`stage_ramp_handler_best_effort_no_acceptance: GPT session did not
produce a validator-accepted contract. validator_error=
stage_ramp_contract_invalid: quarter_ramp_grid utilization_cap
implies …`". The validator is correctly rejecting structurally
invalid stage-ramp grids; GPT cannot self-correct within budget.
This is the same failure class as P3.23a Draft 3 (Skyward) —
**handler timeout / no convergence within tool-call budget**.

### Pattern P6 — initial-grid feasibility gaps
**Count:** 1 (Pinnacle Logistics Inc.)
**Op code:** `revenue_driver_formula_contract_failed`
**Detail:** "FINMO revenue must equal model-input revenue drivers
for every live quarter. delta=0.034731 for Q5 against formula
`sum(Capacity × Unit Price × Utilization) across revenue products`".
This is a **revenue-driver contract violation** — the FINMO build
chain emitted a revenue that does not match the algebraic sum of
its own driver components for at least one quarter. P3.22 Part 2
introduced this contract (`phase_9_p3_22_part2_single_source_revenue_driver_formula`).
The fail-fast is firing on a tiny delta (0.035 / ~$10M revenue = ~3
parts per billion), suggesting either a float-precision tolerance
gap or a real driver-vs-FINMO mismatch the contract should catch.

### Pattern P8 — viability multi-metric failures
**Count:** 3 (CareFirst 13/16, Elegant Threads 13/16, Harborview Kitchen 14/16)
**Common characteristic:** Runs reach acceptance gate, handler
fires (engagement count 4 / 8 / 1 respectively), but the gate
counts 2-3 failing realism / viability checks. CareFirst is a
**turnaround / pre-revenue** case with handler engagement at the
P&L scope. Yesterday's P3.25 memo flagged CareFirst's specific
Mirror Flavor 1 divergence in payroll; today it now fails at the
gate (13/16) rather than passing the gate with bad data, which is
the *correct* enforcement posture. The fix in P3.26 Commit 2 routed
payroll feasibility back through Handler C — that path is firing
but the deterministic algebra cannot satisfy the realism bands.

### Pattern P9 — data-source gap (NAICS-specific)
**Count:** 1 (Luminous Glow Med Spa)
**Op code:** `payroll_headcount_key_person_oews_catalog_empty`
**Detail:** OEWS title catalog empty for the draft's NAICS. This is
a data-gap issue (NAICS coverage), not an architectural fault —
intake pre-flight correctly fails fast when the wage source is
missing.

### Summary by category
| Category                | Count |
| ----------------------- | -----:|
| stage_ramp              |     4 |
| acceptance_gate         |     3 |
| cash_buffer             |     3 |
| revenue_driver_contract |     1 |
| intake_preflight        |     1 |

---

## §4 FALSE_PASS analysis

**Zero FALSE_PASS detected** in this sweep.

Caveat: V-3 (FINMO trajectory vs realism claims) and V-4 (FINMO vs
Audit Source baseline divergence) cannot be fully exercised when
workbook formulas are uncached. The 16 GENUINE_PASS verdicts are
inferred from:
- runner returncode = 0 (acceptance gate passed)
- Diagnostics `Score = 16/16` and `Verdict = PASSED`
- Diagnostics `Realism Check Detail` rows show zero hard fails

A separate Excel-open V-4 verification pass against the 16 stored
workbooks would be needed to catch any P1-class Mirror Flavor 1
divergence on payroll or other multi-surface fields. Recommendation
in §6 below.

---

## §5 V-4 divergence distribution

Direct numeric V-4 distribution is **not measurable** for the 15 of
16 GENUINE_PASS drafts whose workbooks contain only formulas. The
sole exception is the CareFirst FAIL workbook (run 2,
13/16 acceptance), whose cached deltas show:

| Row                              | Cached delta |
| -------------------------------- | -----------: |
| Revenue Q20 FINMO vs Audit       | (matches)    |
| Payroll Q20 FINMO vs Audit       |   $36,512    |
| Net Income Q20 FINMO vs Audit    |  −$36,512    |
| Cash Q20 FINMO vs Audit          |  −$676,909   |
| Total Assets Q20 FINMO vs Audit  |  −$676,909   |
| Ending Cash Q20 FINMO vs Audit   |  −$676,909   |

This is the CareFirst P3.25 Mirror Flavor 1 trace from yesterday's
divergence memo — payroll diverges by $36.5K Q20 with cash
compounding to −$676K. The P3.26 Commit 2 repair re-routes payroll
through Handler C, but the workbook for this run shows the
pre-repair state (acceptance failed *before* the repair could
re-author). Acceptance correctly rejected.

**Recommendation:** Run a one-shot Excel-open V-4 pass on the 16
GENUINE_PASS workbooks (script: open each, save, re-read deltas).
This is the only way to confirm V-4 reconciliation post-P3.26 and
detect any latent Pattern P1.

---

## Methodology — what the sweep *did* and *did not* prove

**Did prove:**
- Acceptance gate enforcement is consistent: 16 / 28 runs reach
  16/16 with handler-led repair; 12 / 28 fail with clearly
  identified op codes.
- P3.26 Commit 1 (ITERATING_STILL routing) is exercising the
  handler in 19/28 runs without producing stuck-mid-iteration
  hangs.
- P3.26 Commit 2 (payroll feasibility routed to Handler C) is
  active — CareFirst now fails at the acceptance gate with a clean
  13/16 rather than slipping through with a bad workbook.
- No NexGen-class regression in this sample (NexGen run 27 passed
  cleanly with 1 tool call).

**Did not prove:**
- V-4 reconciliation on the 16 GENUINE_PASS workbooks
  (workbook-formulas-only constraint).
- That handler engagement is correctly populating
  `failing_metrics` payload (not measured per-draft).
- That cash_buffer violations are unfixable architecturally; only
  that no repair path *currently* attempts to fix them
  (Pattern P4 / P7).

See companion memo [p3_28_architectural_audit.md](./p3_28_architectural_audit.md)
for the per-handler / per-contract authority audit.
