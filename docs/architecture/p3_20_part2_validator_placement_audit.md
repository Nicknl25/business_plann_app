# P3.20 Part 2 — Validator Placement Audit

**Iter:** Phase 9 P3.20 Part 2 (read-only investigation; no fixes)
**Scope:** Verify the cash pass diagnosis from P3.19 (cash_buffer_violation lives in the wrong place), inventory every handler-on-failure pattern, classify every finalize fail-fast as machinery integrity (A) vs plan viability (B), and identify class-B fail-fasts that should move.

---

## Section A — Cash pass diagnosis: VERIFIED with correction

**Original hypothesis:** "The `cash_buffer_violation` fail-fast lives at FINALIZE as a terminal hard-fail. The funding handler never engages because nothing in the cash strategy stage's validator layer flags the infeasibility."

**Actual state (verified with code reads):** The funding handler IS wired to the cash post-pass validator layer. The hypothesis is partially wrong — the handler does get a chance. But there's a real architectural fragility downstream of the handler that allows violations to leak through to finalize unfixed.

### A.1 — The cash post-pass validator does detect buffer violations

[post_intake_cash/validation_envelope.py:102, 112, 174-176](python/client_intake_and_finmo/post_intake_cash/validation_envelope.py#L102)

```python
buffer_violation = bool(ending_cash < buffer_required)
# ... violations get aggregated into cash_buffer_violations list in the envelope
```

This runs at the end of the cash strategy stage, AFTER the Python proposer and after the GPT cash-strategy critic + second-pass plan have run. It correctly identifies any quarter where ending cash falls below the cash buffer requirement.

### A.2 — The funding handler IS conditionally invoked on violations

[post_intake_cash_strategy/orchestrator_invocation.py:437-505](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L437):

```python
keep_changes = bool(cash_post_validation.get("keep_changes", True))
# ...
cash_buffer_violations_for_handler = list(
  cash_post_validation.get("cash_buffer_violations") or []
)
if (
  not keep_changes
  and cash_buffer_violations_for_handler
  and isinstance(cash_strategy_second_pass_result, dict)
):
  from client_intake_and_finmo.post_intake_funding_handler import (
    engage_funding_handler_on_violations,
  )
  # ...
  cash_funding_handler_result = engage_funding_handler_on_violations(
    cash_buffer_violations=cash_buffer_violations_for_handler,
    ...
  )
```

When violations exist AND `keep_changes` is false, the handler engages. The handler authority is the 5 funding levers (debt issuance, debt repayment, owner's capital, other equity, distributions) per [post_intake_funding_handler/handler.py:267-273](python/client_intake_and_finmo/post_intake_funding_handler/handler.py#L267).

### A.3 — Post-handler re-validation exists; revert path is the fragility

[orchestrator_invocation.py:506-543](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L506):

```python
if (
  cash_funding_handler_result.get("status") == "resolved"
  and isinstance(cash_funding_handler_result.get("updated_model_input_json"), dict)
  and isinstance(cash_funding_handler_result.get("updated_finmo_json"), dict)
):
  # Re-validate the post-handler state.
  post_handler_post_validation = _cash_runner._validate_cash_strategy_post_pass(...)
  if post_handler_post_validation and bool(post_handler_post_validation.get("keep_changes")):
    # Handler resolved violations AND post-pass agrees.
    # ... accept handler changes
    keep_changes = True
```

If the handler returns `resolved` AND re-validation agrees, handler changes are accepted and `keep_changes=True`. Otherwise, `keep_changes` stays False.

The fragility: [orchestrator_invocation.py:545-558](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L545):

```python
if keep_changes:
  final_model_input_json = cash_strategy_second_pass_result.get("updated_model_input_json") ...
  final_finmo_json = cash_strategy_second_pass_result.get("updated_finmo_json") ...
else:
  final_model_input_json = copy.deepcopy(pre_cash_model_input_json)
  final_finmo_json = copy.deepcopy(pre_cash_finmo_json)
```

When `keep_changes=False`, **the orchestrator reverts to the PRE-CASH state** — discarding both the cash strategy's work and the funding handler's work. The handler returned "exhausted" or "partial" with residual violations; the system gives up and uses the pre-cash state instead.

The pre-cash state typically also has cash buffer issues (otherwise the cash strategy wouldn't have been needed). So the post-revert state still violates the buffer.

### A.4 — Finalize re-runs the buffer check as a TERMINAL hard-fail

[fail_fast/post_intake_fail_fast/fail_fast.py — `assert_post_intake_cash_buffer_integrity`](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py):

```python
def assert_post_intake_cash_buffer_integrity(
  *,
  financials_json: Optional[Dict[str, Any]],
  model_input_json: Optional[Dict[str, Any]],
  finmo_json: Optional[Dict[str, Any]],
  stage: str,
) -> None:
  # iterates Q1-Q20; for each, computes opex_quarter, monthly_opex,
  # cash_buffer_required, and checks ending_cash >= buffer_required.
  # If any quarter violates, raises post_intake_cash_buffer_violation.
```

Called from [finalize_post_intake.py:587-594](python/client_intake_and_finmo/post_intake_runtime_validation/finalize_post_intake.py#L587):

```python
try:
  assert_post_intake_cash_buffer_integrity(
    financials_json=...,
    model_input_json=...,
    finmo_json=...,
    stage="post_intake_finalize_validation_cash_buffer",
  )
except Exception as exc:
  errors.append(f"cash_buffer_invalid: {exc}")
```

The finalize check is a TERMINAL hard-fail. It is NOT wired to re-invoke the funding handler.

### A.5 — The actual gap

The funding handler IS the right defender for cash buffer violations. The validator-triggers-handler wiring at the cash post-pass IS the right place. **The gap is downstream of the handler:**

1. **When the handler returns `exhausted` or `partial`:** the orchestrator reverts the entire cash strategy stage to pre-cash state. The pre-cash state still has the violations (that's why the cash strategy was needed in the first place). Those violations carry through to finalize and trigger the terminal hard-fail.
2. **When the handler returns `resolved` but post-pass re-validation says `keep_changes=False`:** same — orchestrator reverts to pre-cash state, violations carry through to finalize.
3. **When `cash_strategy_second_pass_result` is None or missing:** the handler is never invoked (line 452 condition fails). Pre-cash state carries through.

The result: in the worst case, the funding handler runs once, fails to resolve, and the system gives up rather than (a) attempting alternative funding strategies, (b) re-engaging the handler with adjusted lever bounds, or (c) escalating to a higher-authority handler. The terminal hard-fail at finalize fires.

### A.6 — Verified P3.19 Phase 3a failing run did follow this path

In the P3.19 Phase 3a `cash_buffer_violation` run, the failing draft `e38c800fa06f4bddafd95211e9e4d017` shows cash deeply negative throughout (Track 4 memo Section C). Following the orchestrator logic above, this means either:
- The handler engaged and returned exhausted/partial, then the orchestrator reverted to pre-cash state which also had violations, OR
- The handler never engaged (e.g., `cash_strategy_second_pass_result` was None or had a particular shape that bypassed the conditional)

Either way, finalize then fired `post_intake_cash_buffer_violation` against the un-fixed state. The handler "never had a chance" to fix the final state because by finalize, the handler's window has closed.

### A.7 — Diagnosis verdict

**The hypothesis is PARTIALLY CORRECT.** The cash_buffer_violation fail-fast at finalize IS a terminal hard-fail, but the funding handler IS wired into the cash post-pass validator path. The architectural gap is in the **handler's single-shot, give-up-on-revert** design: when the handler can't resolve violations, the orchestrator reverts rather than escalating or retrying with different parameters. The terminal finalize hard-fail then catches the un-fixed state.

The fix shape is therefore NOT "move the cash buffer check from finalize to a validator that triggers a handler" — it's already there. The fix shape is "make the handler's failure path do something other than revert and let finalize hard-fail" (e.g., retry with relaxed lever bounds, escalate to a different handler, or accept partial resolution and let finalize redo only the residual quarters).

---

## Section B — Inventory of every handler-on-failure pattern

### B.1 — Funding Handler

| Field | Value |
|---|---|
| **Module** | `python/client_intake_and_finmo/post_intake_funding_handler/` |
| **Trigger validator(s)** | `build_cash_validation_envelope()` at [post_intake_cash/validation_envelope.py:102-112](python/client_intake_and_finmo/post_intake_cash/validation_envelope.py#L102) detects `ending_cash < buffer_required` per quarter; populates `cash_buffer_violations` list in envelope. |
| **Trigger site** | [orchestrator_invocation.py:449-505](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L449) — conditional engagement when `not keep_changes AND cash_buffer_violations AND second_pass_result is dict`. |
| **Authority** | 5 levers: `schedules::Debt Issuance (New Borrowing)`, `schedules::Debt Repayment (Scheduled)`, `balance_sheet::Owner's Capital`, `balance_sheet::Other Equity`, `balance_sheet::Distributions`. Source: [handler.py:267-273](python/client_intake_and_finmo/post_intake_funding_handler/handler.py#L267). |
| **Budget** | `HARD_CAP_TOOL_CALLS = 10` (tool_calling_session.py). |
| **After-handler re-check** | [orchestrator_invocation.py:512-543](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L512) — re-runs `_validate_cash_strategy_post_pass()`. If `keep_changes=True`, accepts handler changes; else, REVERTS to pre-cash state. |
| **Terminal hard-fail** | `post_intake_cash_buffer_violation` at finalize via `assert_post_intake_cash_buffer_integrity()` ([fail_fast.py](python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py)). |

### B.2 — Stage Ramp Handler

| Field | Value |
|---|---|
| **Module** | `python/client_intake_and_finmo/post_intake_stage_ramp_handler/` |
| **Trigger validator(s)** | `validate_stage_ramp_contract_payload()` — checks stage ramp contract shape, profitability path, expense path, capacity curve compliance. |
| **Trigger site** | Invoked from `intake_consult.py` stage ramp authoring path when Python-built `build_python_stage_ramp_contract()` output fails validator. |
| **Authority** | Stage ramp contract fields per `STAGE_RAMP_FIELD_AUTHORITY` constant in handler.py — quarter ramp grid (revenue trajectory, margin targets, capacity curve, cost ratio caps). |
| **Budget** | 10 (mirror of funding handler design). |
| **After-handler re-check** | Handler returns refined contract; orchestrator re-validates with the same validator. |
| **Terminal hard-fail** | `stage_ramp_handler_*` machinery fail-fasts (round count drift, authority violation, output malformation, etc.) AND `stage_ramp_contract_invalid` if exhausted with residual violations. |

### B.3 — GPT Exhaustion / Restoration Handler

| Field | Value |
|---|---|
| **Module** | `python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/` |
| **Trigger validator(s)** | `run_restoration_loop()` deterministic algebra runs first; if no viability path exists (specific levers can't reach target metrics), handler engages with `RestorationStatus.EXHAUSTED`. |
| **Trigger site** | Post-cascade restoration loop in convergence runner. |
| **Authority** | 12 PNL levers + 5 working-capital levers (revenue capacity/price/utilization, expense ratios, AR/AP/inventory days, etc.). [handler.py:50-59, 105-111](python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L50). |
| **Budget** | `INITIAL_BUDGET=8 + EXTENSION=2 = 10`. |
| **After-handler re-check** | Handler commits anchors; path engine interpolates to 20 quarters; FINMO rebuilds; realism metrics re-evaluated post-commit. |
| **Terminal hard-fail** | `HandlerStatus.EXHAUSTED` with residual viability check failures; cascade proceeds to next stage; cascade-level realism gate catches if viability still unmet. |

### B.4 — Capital Lease — NO HANDLER (by design)

Per the P3.16 iter spec: "Capital lease has NO dedicated handler. Reasoning: the schedule is deterministic given intake inputs; contractual obligations can't be adjusted by GPT judgment. Downstream effects (cash pressure, interest drag) are handled by EXISTING handlers (funding, restoration) using their existing authority."

So capital lease validators are Type 1 (business-logic checks) or Type 2 (machinery fail-fasts), and there is no third option of triggering a dedicated handler. Cash pressure from leases flows through to the funding handler via the standard cash post-pass path.

---

## Section C — Classification of every finalize fail-fast

### Pipeline structure

`finalize_post_intake.py:run_finalize_post_intake_validation()` runs the following checks in order (accumulating errors in a list, then raising at the end if any errors):

1. Forecast horizon completeness
2. Model input values completeness
3. FINMO values completeness
4. Revenue formula reconciliation
5. Payroll schedule reconciliation
6. Debt schedule reconciliation
7. **Capital lease schedule reconciliation** (P3.16)
8. Balance sheet driver validation
9. Balance sheet STD/LTD coherence (iter 15)
10. **Balance sheet reconciliation** (iter 16, equality at quarter level)
11. Mapping formula integrity (contract + application)
12. **Global invariants** (multi-check umbrella including all of: FINMO statement integrity, accounting equation, stored totals match components, lease component splits, etc.)
13. **Cash buffer integrity** (the violation in question)
14. Cash phase trace completeness

For each individual fail-fast that may trigger, classification:

### Classification table

| Operation code | Source file | Condition | Classification | Notes |
|---|---|---|---|---|
| `post_intake_cash_buffer_violation` | fail_fast.py `assert_post_intake_cash_buffer_integrity` | `ending_cash < buffer_required` at any Q1-Q20 | **(B) Plan viability** | Funding handler IS wired upstream; finalize is the after-revert backstop. See Section A. |
| `accounting_equation_violation` | fail_fast.py:1544 `assert_post_intake_accounting_equation` (P3.17) | `Σasset_components ≠ Σliab_components + Σequity_components` at any Q1-Q20, >$1 | **(A) Machinery integrity** | Broken math; no handler can author a fix. |
| `stored_totals_match_components_violation` | fail_fast.py (P3.17 3b) | Stored `total_assets`/`total_liabilities`/`total_equity` ≠ component sums at any Q0-Q20 | **(A) Machinery integrity** | Same. |
| `post_intake_finmo_core_row_invalid` | fail_fast.py:1409 `assert_post_intake_finmo_statement_integrity` | Required FINMO field missing/non-numeric at any live quarter | **(A) Machinery integrity** | Structural completeness. |
| `post_intake_statement_math_invalid` | fail_fast.py:1495 (in same function as above) | gross_profit ≠ revenue-cogs, net_income ≠ ebitda-..., or total_assets ≠ total_liab_and_equity at quarter level | **(A) Machinery integrity** | Algebraic identities. |
| `post_intake_schedule_marker_missing` | fail_fast.py `assert_post_intake_schedule_markers_integrity` | Debt or payroll schedule contract markers missing | **(A) Machinery integrity** | Contract conformance. |
| `post_intake_model_input_row_missing` | fail_fast.py `assert_post_intake_model_input_rows_integrity` | Revenue driver row or lever row absent | **(A) Machinery integrity** | Structural completeness. |
| `post_intake_model_input_values_missing` | fail_fast.py (same function) | Driver values blank/non-numeric at any quarter | **(A) Machinery integrity** | Same. |
| `post_intake_revenue_driver_bundle_invalid` | fail_fast.py `assert_post_intake_revenue_driver_integrity` | Capacity-price-utilization triple incomplete | **(A) Machinery integrity** | Structural. |
| `post_intake_revenue_driver_formula_mismatch` | fail_fast.py (same function) | Formula-derived revenue ≠ FINMO revenue | **(A) Machinery integrity** | Mirror Flavor 4. |
| `balance_sheet_driver_formula_failed` | balance_sheet_driver_validation.py | Balance sheet driver formula (AR days × revenue / period etc.) ≠ FINMO field | **(A) Machinery integrity** | Same as revenue mirror. |
| `balance_sheet_std_ltd_coherence_*` | balance_sheet_driver_validation.py | Short-term + long-term debt ≠ debt closing balance | **(A) Machinery integrity** | Algebraic identity. |
| `balance_sheet_reconciliation_unavailable` | finalize_post_intake.py:697 | Balance sheet reconciliation function raised unexpectedly | **(A) Machinery integrity** | Infrastructure. |
| `mapping_formula_integrity_invalid` | finalize_post_intake.py:550 | Mapping formula contract or application drifted from spec | **(A) Machinery integrity** | Contract conformance. |
| `payroll_schedule_reconciliation_failed` | finalize_post_intake.py:354 | Payroll headcount payload invalid OR FINMO payroll ≠ headcount schedule rollup | **(A) Machinery integrity** | Schedule conformance. |
| `debt_schedule_reconciliation_failed` | finalize_post_intake.py:379 | Debt schedule payload invalid OR FINMO debt fields ≠ schedule rows | **(A) Machinery integrity** | Schedule conformance. |
| `capital_lease_schedule_reconciliation_failed` | finalize_post_intake.py:418 (P3.16) | Lease snapshot invalid OR FINMO lease fields ≠ snapshot, OR interest split misaligned, OR depreciation split misaligned, OR financing CF double-count | **(A) Machinery integrity** | Schedule conformance + algebraic identities. |
| `cash_phase_trace_incomplete` | finalize_post_intake.py:399 | Required cash pass phases not all completed | **(A) Machinery integrity** | Phase trace. |
| `forecast_horizon_*` | finalize_post_intake.py | Quarter count, periods, or rolling-sum windows out of expected horizon | **(A) Machinery integrity** | Structural. |
| `workbook_model_status_fail` (P3.20 Part 1) | post_intake_runtime_validation/workbook_model_status.py | Generated workbook Checks!B2 ≠ "OK" | **(A) Machinery integrity** | Downstream display check that aggregates many app-level invariants. By doctrine: the app-side fail-fasts catch most issues before this fires; this is the final "if anything got past the upstream guards, here's the loud signal". |

**Counts:**
- **Class (A) Machinery integrity:** ~19 fail-fasts
- **Class (B) Plan viability:** 1 fail-fast (`post_intake_cash_buffer_violation`)

---

## Section D — Class-B fail-fasts that should move

### D.1 — `post_intake_cash_buffer_violation`

**Currently:** terminal hard-fail at finalize.

**Where it SHOULD live:** Already exists as a validator earlier (at cash post-pass). The handler is wired correctly. The finalize hard-fail is the redundant safety net.

**The real fix is not relocation. The real fix is the handler's failure path.** Possible directions (NOT recommended in this memo — just options for user consideration):

1. **Multi-shot handler engagement:** When `keep_changes=False` after first handler attempt, try again with relaxed lever bounds or a different funding source policy before reverting.
2. **Accept-and-residual mode:** When the handler partially resolves (some quarters fixed, others not), accept the partial improvement and report a structured warning at finalize rather than a hard-fail. The plan is improved relative to pre-cash; reverting throws away the improvement.
3. **Pre-cash-state pre-check:** Before engaging the cash strategy at all, check whether the pre-cash state has feasibility issues that NO funding combination can resolve. If so, fail fast at a different stage (revenue/cost rebalancing) rather than letting the cash strategy spin and revert.
4. **Cross-handler escalation:** If the funding handler exhausts on cash buffer issues, the issue may be that operating expenses are unsupportable at current revenue. Escalate to the restoration handler with the cash-buffer-as-target-metric.

None of these are validator-placement issues. They are handler-design issues. The validator placement is correct.

### D.2 — Other class-B candidates: NONE

No other finalize fail-fasts are plan-viability issues a handler could plausibly fix. All others are machinery integrity (broken math, missing structure, contract conformance, identity violations). They correctly belong at finalize.

---

## Section E — Architectural concerns surfaced beyond fail-fast placement

### E.1 — The revert-on-handler-failure pattern is the actual fragility

When the funding handler can't resolve cash buffer violations:
- The orchestrator REVERTS to pre-cash state
- This silently discards all cash strategy work AND all handler work
- The pre-cash state typically also has the original violations (that's why cash strategy was needed)
- Finalize hard-fails on the un-changed violations

The revert is conservative (avoids polluting state with a partially-broken handler result), but it means the handler's window is single-shot. There's no retry, no escalation, no partial accept. The terminal hard-fail at finalize is the only consequence.

### E.2 — Realism violations route differently

Realism band hard-fail violations are treated as adaptation signals fed back into the restoration loop ([post_intake_realism/validator.py:605-618](python/client_intake_and_finmo/post_intake_realism/validator.py#L605)):

```python
# they MUST surface in hard_fail_violations so the post-cascade
# driven restoration loop reads hard_fail_violations directly
hard_fail_violations.append({
  ...
  "post_intake_finalize_realism_band_violation: ...",
})
```

Realism violations are NOT finalize hard-fails. They are signals consumed by the restoration handler. This is the correct pattern that the funding handler design partially mirrors but doesn't quite achieve (the funding handler exists but its failure mode is revert + terminal hard-fail, not continued iteration).

### E.3 — Capital lease has no handler — intentional but worth flagging

Per the P3.16 iter spec, capital lease intentionally has no dedicated handler. Cash pressure from leases is supposed to be absorbed by the funding handler. **If the funding handler's failure path is the underlying issue (Section A.5), then capital-lease-bearing businesses are doubly exposed:** the lease adds cash drain, the funding handler can't fully resolve, the system reverts and finalize hard-fails. This is consistent with the P3.19 Phase 3a observation that the cash buffer violation appeared after the rate fix made the existing-yet-marginal cash strategy collapse.

### E.4 — Stage ramp handler and restoration handler appear correctly wired

Both have:
- Validator-triggered engagement
- 10-call budget
- After-handler re-validation
- Specific terminal diagnostic on exhaustion

Stage ramp handler exhaustion is a machinery hard-fail (no further handler to escalate to; stage ramp is contract-level so failure is structural). Restoration handler exhaustion triggers cascade-level realism gates which may proceed to alternative cascade tiers. Both designs are consistent with the doctrine.

The funding handler is structurally the same shape as these but has the revert-to-pre-state-on-failure quirk that the other two don't have (stage ramp handler returns a contract that gets persisted regardless of resolution status; restoration handler commits anchors that the path engine uses regardless).

---

## Section F — Doctrine pattern classification

The cash buffer fragility is **Pattern 3 (diagnostic blames wrong layer):** the terminal finalize hard-fail blames "cash buffer violation" but the actual issue is that the funding handler's single-shot revert-on-failure means the handler can't recover from a hard case. The validator-handler wiring is correct (Section A); what's missing is a recovery loop equivalent to the restoration handler's repeated-attempt design.

This is NOT Pattern 1 (two paths divergence — the validator and handler reads the same buffer formula).
This is NOT Pattern 2 (GPT as routine authoring source — the cash strategy proposer is Python-deterministic; the GPT critic only runs when needed).

This may be a NEW pattern: **handler-failure-without-escalation.** Worth flagging to user as a possible new doctrine entry: when a handler exhausts, the next-step behavior must be defined explicitly (revert, escalate, accept-partial, retry). Today the funding handler defaults to revert; the restoration handler defaults to commit-anchors-and-continue; the stage ramp handler returns its best contract. The system should make this design choice explicit per handler.

---

## Section G — Summary for next directive

**Findings:**

1. **Cash pass diagnosis correction:** the funding handler IS wired correctly into the cash post-pass validator path. The hypothesis "nothing flags buffer infeasibility to the handler" is wrong.

2. **The actual gap:** the funding handler's single-shot revert-on-failure design means when the handler can't resolve, the system gives up. The pre-cash state (which had the original violation) carries through to finalize and triggers the terminal hard-fail. The handler effectively has one shot.

3. **Other class-B fail-fasts at finalize:** none. Every other finalize fail-fast is class (A) machinery integrity and correctly belongs there.

4. **Architectural concern beyond placement:** the funding handler's failure-mode design is the fragility, not the validator placement. Recommended fix shape options (Section D.1) involve handler retry, partial-accept, cross-handler escalation, or pre-cash-state pre-check — all handler-design changes, not validator moves.

5. **Capital lease compounding effect:** lease-bearing businesses are doubly exposed to the funding handler fragility because the lease adds cash drain that the handler must absorb.

**Recommended next directive shape:**

Pick ONE of these (NOT both at once):
- **Option A — Funding handler retry loop:** add an outer loop around the handler invocation that tries N attempts with progressively relaxed lever bounds before reverting. Test against the P3.19 Phase 3a draft.
- **Option B — Partial-accept mode:** when the handler returns `partial`, accept the improved state (don't revert) but emit a structured warning at finalize that the residual quarters violate buffer. Let acceptance gate downstream judge whether the partial improvement is acceptable.
- **Option C — Pre-cash-state pre-check:** before engaging cash strategy, run a "is this state recoverable by any funding combination?" check. If not, fail at an earlier stage with a clearer diagnostic that points at the operating-cost imbalance rather than the cash buffer.

Each of these is roughly the same complexity (1-3 days of work, ~200-500 LOC). User decides which to pursue first.

No fixes were proposed in this memo per iter directive — these are options for the next iter.
