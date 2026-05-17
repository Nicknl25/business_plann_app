# P3.20 Part 2b — Failure Mode Verification of P3.19 Phase 3a FAIL Run

**Iter:** Phase 9 P3.20 Part 2b (read-only investigation; no fixes)
**Scope:** Verify exactly what happened in the lease-bearing ExpressLogix rerun that failed with `cash_buffer_violation` (cloned draft `e38c800fa06f4bddafd95211e9e4d017`). Determine whether the funding handler engaged, with what outcome, and reconcile against the Track 4 memo's hedged claim.

---

## 1. Did the funding handler engage?

**NO. The funding handler did not engage in this run.**

### Evidence

The post-cash-pass trace (api log `tmp/api_p3_19_v2_5056.err.log` line 869):

```
cash_post_pass_trace
  keep_changes=False
  all_hard_rules_cleared=True
  cash_buffer_violations=[]
  cash_distribution_violations=[]
  cash_surplus_ceiling_violations=[]
  cash_contract_failures_count=1
  failed_rule_codes=[]
```

The funding handler's trigger condition at [orchestrator_invocation.py:449-453](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L449):

```python
if (
  not keep_changes
  and cash_buffer_violations_for_handler   # <-- THIS LIST IS EMPTY
  and isinstance(cash_strategy_second_pass_result, dict)
):
  # ... engage_funding_handler_on_violations(...)
```

`cash_buffer_violations_for_handler` comes from `cash_post_validation.get("cash_buffer_violations")` — the same value the trace reports as `[]`. Empty list is falsy, so the AND short-circuits. Handler is never invoked.

There are NO log entries containing `funding_handler`, `engage_funding`, or `FundingHandler` anywhere in the run's API log (`tmp/api_p3_19_v2_5056.err.log`, 974 lines), confirming the handler never even loaded its module.

### Why the violations list is empty

The cash strategy stage actually SUCCEEDED at sizing funding to close the buffer gap. The Python proposer's trace at [api log line 662](tmp/api_p3_19_v2_5056.err.log):

```
cash_proposer_trace mode=balanced ...
  violation_quarters=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
  proposer_quarter_funding_plan=[
    {'q': 1, 'sources': [{'lever': "balance_sheet::Owner's Capital", 'amount': 4279027, ...}]},
    {'q': 2, 'sources': [{'lever': "balance_sheet::Owner's Capital", 'amount': 77199, ...}]},
    {'q': 3, 'sources': [{'lever': "balance_sheet::Owner's Capital", 'amount': 85597, ...}]},
    {'q': 4, 'sources': [{'lever': "balance_sheet::Owner's Capital", 'amount': 15601, ...}]}
  ]
```

The proposer saw violations at all 20 quarters and proposed $4.28M of Owner's Capital injection in Q1 (plus smaller amounts Q2-Q4). After this proposal landed, the post-pass validator re-checked the candidate state and found NO remaining buffer violations.

So the cash strategy WORKED. The handler had no buffer violations to fix.

### What made `keep_changes=False`

`cash_contract_failures_count=1` — exactly one cash_contract_failure tripped. The keep_changes formula at [post_intake_cash/runner.py:4288-4293](python/client_intake_and_finmo/post_intake_cash/runner.py#L4288):

```python
keep_changes = bool(
  hard_rule_assessment.get("all_hard_rules_cleared")
  and not cash_buffer_violations          # [] -> True
  and not cash_distribution_violations    # [] -> True
  and not cash_contract_failures          # 1 entry -> False
)
```

The single cash_contract_failure flipped `keep_changes` to False. The identity of that failure is NOT preserved in the persisted `cash_strategy_second_pass_result` (the orchestrator clears those payloads on revert), and `failed_rule_codes=[]` in the trace shows it's not a standard hard-rule code. Candidate sources from [post_intake_cash/runner.py:4067-4257](python/client_intake_and_finmo/post_intake_cash/runner.py#L4067) (each is a `cash_contract_failures.append({...})` site):

| Source line | Likely failure type |
|---|---|
| 4067 | invalid `selected_cash_strategy` |
| 4079 | `cash_debt_interest_rate_policy_missing` |
| 4086 | `cash_debt_interest_rate_policy_not_sba_backed` |
| 4110 | `cash_debt_interest_rate_policy_rate_missing` |
| 4143 | `cash_debt_interest_rate_forecast_mismatch` (the one P3.19 Phase 2 followup updated) |
| 4164 | `cash_debt_schedule_minimum_plan_failed` |
| 4175 | `cash_debt_schedule_missing` |
| 4197 | `cash_debt_schedule_payload_invalid` |
| 4218 | `cash_debt_schedule_finmo_reconciliation_failed` (or similar) |
| 4257 | `cash_debt_schedule_minimum_principal_not_applied` |

Cannot determine the exact failure code without the persisted cash_strategy_second_pass_result, which was discarded by the revert path. Most likely candidates given the bcf818d rate fix history: one of the `cash_debt_*` family. Recommend a future fix-in-place that PRESERVES the cash_strategy_second_pass_result even on revert so the contract failures are visible post-mortem.

---

## 2. If yes: tool_calls_used, return status, post-handler validator outcome

N/A — handler did not engage.

---

## 3. If yes: did the orchestrator hit the revert path?

**YES.** Orchestrator hit [orchestrator_invocation.py:545-558](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L545):

```python
if keep_changes:
  final_model_input_json = cash_strategy_second_pass_result.get("updated_model_input_json") ...
  final_finmo_json = cash_strategy_second_pass_result.get("updated_finmo_json") ...
else:
  final_model_input_json = copy.deepcopy(pre_cash_model_input_json)
  final_finmo_json = copy.deepcopy(pre_cash_finmo_json)
```

With `keep_changes=False`, the else branch executed. The cash strategy's $4.28M Owner's Capital injection was DISCARDED. Final state = pre-cash state.

Evidence:
- The persisted `cash_strategy_review_decision`, `cash_strategy_second_pass_plan`, `cash_strategy_second_pass_result`, and `cash_strategy_effect_summary` are all empty `{}` dicts in `planning_run_json`. The orchestrator's revert path discarded them.
- The persisted `finmo_json`'s Q1 `owners_capital = 5,341,557` (= 2,500,000 base + 2,841,557). Wait — this is non-zero. Let me re-read.

Actually, looking at the finmo at Q1: `owners_capital: 5,341,557` while the pre-cash baseline would be 2,500,000. So the equity injection DID make it through somehow. But ending_cash is -1,926,319 — deeply negative. Hmm.

Re-checking: the trace's `cash_strategy_input_trace q=1 ending_cash=-1926319` shows the SAME negative cash that the finalize_input_trace shows. So whatever ran (pre-cash or post-cash final), the cash trajectory is the same. The "input trace" is the cash state BEFORE the cash strategy stage runs; the "finalize trace" is what finalize sees. Both show the same cash trajectory — meaning the cash strategy's $4.28M equity injection either:

(a) Did NOT make it into the final state (consistent with revert), OR
(b) DID make it in (consistent with the persisted owners_capital=5,341,557 which is non-baseline) but did not move cash because the equity went to retained earnings via a parallel path

Without the full cash strategy output to compare, I can confirm only this: ending_cash is deeply negative throughout, the buffer is violated everywhere, and the finalize hard-fail correctly fires on that state.

The owners_capital=5,341,557 figure may come from the convergence stage upstream of the cash strategy (the GPT-authored revenue/equity envelope), not from the cash strategy's $4.28M proposal. The pre-cash state already had non-baseline owner's_capital from convergence.

---

## 4. If no: which validator(s) ran in the cash stage, what they evaluated to, why the handler trigger didn't fire

Validators that ran in the cash stage:

| Validator | Ran? | Outcome |
|---|---|---|
| `cash_strategy_proposer` (Python deterministic) | YES | Saw violations all 20 quarters; proposed $4.28M Owner's Capital Q1 + smaller amounts Q2-Q4. `residual_gap_quarters=[1..20]` (proposer can't fully close Q5-Q20 within its 4-quarter planning horizon). |
| `_validate_cash_strategy_post_pass` (after proposer) | YES | `all_hard_rules_cleared=True`, `cash_buffer_violations=[]`, `cash_distribution_violations=[]`, `cash_surplus_ceiling_violations=[]`, `cash_contract_failures_count=1`, `failed_rule_codes=[]`. |
| GPT cash strategy review + critic | likely ran | Outputs cleared on revert; not visible in persisted state. |
| Cash strategy second-pass plan | likely ran | Same; cleared. |
| Funding handler trigger check ([orchestrator_invocation.py:449](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L449)) | YES | Condition `(not keep_changes) AND (cash_buffer_violations_for_handler) AND (isinstance(second_pass_result, dict))` evaluated. The middle term was empty list `[]` (falsy). Condition failed. Handler NOT invoked. |
| `engage_funding_handler_on_violations` | NO | Never called. |
| Orchestrator revert path (line 545-558) | YES | `keep_changes=False` triggered revert to pre-cash state. |
| Final FINMO rebuild ([orchestrator_invocation.py:560-588](python/client_intake_and_finmo/post_intake_cash_strategy/orchestrator_invocation.py#L560)) | YES | Rebuilt FINMO from pre-cash model_input. |
| Finalize `assert_post_intake_cash_buffer_integrity` | YES | Detected buffer violations on the reverted state at every Q1-Q20. RAISED `post_intake_cash_buffer_violation`. |

**The handler trigger didn't fire because the validator-side buffer violations list was empty.** The CANDIDATE state (cash strategy output, with the $4.28M equity proposal applied) had no buffer violations. The revert was triggered by a DIFFERENT category of failure (cash_contract_failure, exact identity unknown post-revert), and the revert discarded the cash strategy's work, returning to a pre-cash state that still had violations.

---

## 5. Reconciliation with Phase 3a email's "Handler engagement: NONE" claim

The "Handler engagement: NONE" line appeared in the **P3.16b ExpressLogix-with-lease PASS email** (commit `aeec697`, the original lease-bearing ExpressLogix verification that PASSED clean before P3.19's rate fix). In that earlier passing run, the funding handler genuinely did NOT engage because the cash strategy proposer closed the gap on its own — no validators fired requiring handler authority. The claim there was accurate.

The P3.19 Phase 3a v2 FAIL run (this iter's subject) is a different scenario:
- I did NOT send a per-run email asserting "Handler engagement: NONE" for the FAIL run.
- The bcf818d Phase 2 followup email noted the cash_buffer_violation but DID NOT make a handler-engagement claim either way.
- The Track 4 memo (commit `ced2cc0`) hedged: "Funding handler may not have engaged (would need run_diagnostics deep dive)."
- The Part 2 memo (commit `035b3ec`) was MORE precise: described the funding handler as wired correctly with a single-shot revert-on-failure fragility, and noted that the handler effectively gets one shot or none.

**This Part 2b memo NOW confirms with direct log evidence:** for this specific FAIL run (draft `e38c800fa06f4bddafd95211e9e4d017`), the handler **did not engage at all** — not even one shot. The trigger condition `cash_buffer_violations_for_handler` was empty because the cash strategy's CANDIDATE state passed the buffer check. A non-buffer cash_contract_failure caused the revert.

So the Part 2 memo's framing of "single-shot revert-on-failure" was directionally correct but underspecified: in this run, the handler got **ZERO shots**, not one. The handler was eligible only if the post-pass validator reported buffer violations; in this case, it reported none.

---

## 6. Picture summary

```
Pre-cash state:
  ending_cash Q1 = -1.93M, buffer_req Q1 = 2.35M (deep violation)

Cash strategy proposer:
  Sees violations Q1-Q20.
  Proposes $4.28M Owner's Capital Q1 + smaller Q2-Q4.
  Outputs candidate state.

Post-pass validator on CANDIDATE state:
  cash_buffer_violations = []   <-- proposer's funding closed the gap
  cash_distribution_violations = []
  cash_surplus_ceiling_violations = []
  cash_contract_failures = [1 entry, identity unknown post-revert]
  all_hard_rules_cleared = True
  keep_changes = False  (the 1 cash_contract_failure flipped it)

Funding handler trigger:
  (not keep_changes) AND (cash_buffer_violations_for_handler) AND (second_pass_result is dict)
  = True AND False AND True
  = False  <-- handler NOT invoked

Orchestrator revert path:
  keep_changes = False -> use pre_cash_model_input_json + pre_cash_finmo_json
  Cash strategy proposal DISCARDED.

Final FINMO rebuild from pre-cash state:
  ending_cash Q1 = -1.93M (still violates buffer)

Finalize assert_post_intake_cash_buffer_integrity:
  Detects buffer violation at Q1-Q20.
  RAISES post_intake_cash_buffer_violation.

API returns 500.
Customer-facing run failed.
```

---

## 7. Implication for fix shape (NOT in this memo)

The architectural gap is more specific than the Part 2 memo characterized. There are at least three repair angles:

**A. Handler trigger condition** — relax it so the handler engages when `keep_changes=False` even if the buffer violations list is empty. The handler could ALSO author funding that recovers from the non-buffer cash_contract_failure. Or the trigger condition could explicitly include `cash_contract_failures` as another invocation reason.

**B. Cash_contract_failure visibility** — preserve `cash_strategy_second_pass_result` (or just the cash_contract_failures list) on revert so post-mortem can identify which failure caused the revert. Today the orchestrator discards it.

**C. Revert atomicity** — when the cash strategy successfully closes buffer violations but fails on a peripheral cash_contract_failure, consider keeping the buffer-closing changes and surfacing the contract failure as a separate diagnostic. The current all-or-nothing revert throws away genuinely-useful work.

User decides which to pursue.

No fixes proposed in this memo per iter directive.
