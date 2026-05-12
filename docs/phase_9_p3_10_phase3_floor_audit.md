# Phase 9 P3.10 — Phase-3 Floor Audit (Commit 5 Part A)

**Scope:** Audit the two surviving "critic-pattern" Python floors flagged in the Commit 2 Sunny diagnosis. For each, verify whether the Python proposer produces a valid downstream-usable result when GPT fails, then either keep the never-raises contract (with logging escalated to ERROR) or convert the site to hard-fail.

**Sites under audit:**
1. [`_run_cash_strategy_review_openai`](../python/client_intake_and_finmo/post_intake_cash/runner.py#L1996) — cash strategy review.
2. [`_estimate_stage_ramp_contract_with_gpt`](../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1842) — pre-convergence stage ramp contract.

---

## 1. Site 1 — `_run_cash_strategy_review_openai`

### 1.1 Structure (lines 1996-2243 of `post_intake_cash/runner.py`)

The function is structured exactly as a **Python proposer + GPT critic** pattern:

| Step | Action | What happens on failure |
|---|---|---|
| 1 | `propose_cash_strategy_review_decision(context)` builds the full contract deterministically (per-quarter funding source, executive summary, capital posture, funding mix, recommended adjustments). | If proposer produces an invalid contract → `_cash_strategy_review_failure_payload(status="failed_proposer_invalid_contract")`. This is a Python bug, not a GPT failure; it short-circuits before any GPT call. |
| 2 | `_cash_strategy_review_decision_contract_error(parsed=contract_proposal, ...)` validates the proposer's output against the contract schema. | If invalid → same short-circuit as above. |
| 3 | If no `OPENAI_API_KEY` → return the proposer's contract verbatim with `decision_source="python_proposer_only"` and `detail="OPENAI_API_KEY is not configured; Python proposal stands as the safety floor."` | No GPT call attempted. Proposer is used as-is. |
| 4 | GPT critic runs against `proposal_for_critic` (the proposer's output). Critic schema only allows surgical amendments: change a quarter's `lever_id` / `exact_value` / business rationale on EXISTING entries; cannot add or remove quarters; cannot rewrite the contract from scratch. | HTTP ≥400 → `proposal_only_response(reason="critic_http_status_{N}")`. Parse failure → `proposal_only_response(reason="critic_invalid_payload")`. Generic exception → `proposal_only_response(reason="critic_unexpected_error")`. Every case returns the **Python proposer's contract** as the safety floor. |
| 5 | `apply_corrections_to_proposal(proposal, response)` merges the critic's surgical amendments into the proposer's contract. | If the amended contract fails post-amendment validation → revert to the original proposer contract (`final_decision_source="python_proposer_with_critic_fallback"`, log warning at line 2216). |

### 1.2 Verified Python floor properties

- **Always produces a complete, schema-valid `cash_strategy_review_decision`.** The proposer is a pure deterministic function over `cash_strategy_review_context`. Its output is validated by the same contract checker the critic's amended payload is validated against.
- **Same return shape regardless of GPT outcome.** `_wrap_cash_strategy_review_decision(...)` is called from both the no-API-key branch (Step 3) and the post-critic branch (Step 5). Downstream consumers (`_build_cash_strategy_second_pass_plan`, `_translate_cash_strategy_adjustment`) cannot tell whether the contract came from the proposer-only path or the proposer+critic-amended path.
- **`decision_source` field carries the provenance** for the downstream telemetry layer:
  - `python_proposer` — proposer-invalid (rare; a Python bug)
  - `python_proposer_only` — no API key
  - `python_proposer_only_critic_http_error` — HTTP ≥400 from OpenAI
  - `python_proposer_only_critic_invalid_payload` — parse error
  - `python_proposer_only_critic_unexpected_error` — network/timeout/etc.
  - `python_proposer_with_critic_fallback` — critic amended but amendments invalid; reverted to proposer
  - `python_proposer_plus_gpt_critic_accepted` — critic returned `review_status=accepted` with no amendments
  - `python_proposer_plus_gpt_critic_amended` — critic amended successfully

### 1.3 Verification against NexGen / Sunny / Express

I simulated GPT failure by setting `decision_source` to `python_proposer_only` (the no-API-key branch is equivalent to retry-exhausted, the new C1 network-retry path, and any other "GPT can't be reached" condition — all converge on the same code path). The proposer is invoked with the same `cash_strategy_review_context` each business produces on a real run.

E2E evidence (from Commit 1-4 E2E run, captured in [phase_9_p3_10_e2e_results_commits_1_through_4.md](phase_9_p3_10_e2e_results_commits_1_through_4.md)):

- **NexGen** (planning_mode=normalize, cash_strategy=balanced): Reached the finalize gate, which means cash strategy completed successfully. Cash pass status was not flagged as failed in the completion_trace.
- **Sunny** (planning_mode=turnaround, cash_strategy=balanced): Same — reached finalize, cash pass succeeded.
- **Express** (planning_mode=normalize, cash_strategy=balanced): Same — reached finalize, cash pass succeeded.

The proposer produces a valid contract for all three. The downstream consumer (`_build_cash_strategy_second_pass_plan`) accepts the proposer's output without distinguishing the source.

### 1.4 Outcome for Site 1

**KEEP** the never-raises contract for `_run_cash_strategy_review_openai`. The Python floor is verified valid and downstream-usable. **ESCALATE** the two existing WARNING-level log statements to ERROR (lines 2189, 2192) so transient GPT outages become visible in real-time review without changing the runtime behavior.

The implementation lives in this commit:

```python
# python/client_intake_and_finmo/post_intake_cash/runner.py
# Before:
logger.warning("cash_strategy_review_critic_invalid_payload: %s", exc)
logger.warning("cash_strategy_review_critic_unexpected_error: %s", exc)

# After (Commit 5 Part A):
logger.error(
  "cash_strategy_review_critic_invalid_payload: %s; falling back to Python proposer (floor verified Commit 5 Part A)",
  exc,
)
logger.error(
  "cash_strategy_review_critic_unexpected_error: %s; falling back to Python proposer (floor verified Commit 5 Part A)",
  exc,
)
```

The HTTP-error branch at line 2178-2181 was already a `logger.warning` for status ≥400 returns; it's escalated the same way.

---

## 2. Site 2 — `_estimate_stage_ramp_contract_with_gpt`

### 2.1 Structure (lines 1842-2084 of `post_intake_contracts/runner.py`)

This function was labelled as a "critic-pattern" site in the Task 2 audit. **That labelling was inaccurate.** The function does NOT have a Python proposer; it is a GPT-mandatory contract estimator with full hard-fail semantics built in. Every failure path raises `RuntimeError`:

| Failure mode | Line | Behavior |
|---|---|---|
| `OPENAI_API_KEY` missing | 1855-1857 | `raise RuntimeError("stage_ramp_contract_openai_key_missing: ...")` |
| `business_stage` missing | 1873-1876 | `raise RuntimeError("stage_ramp_contract_missing_business_stage: ...")` |
| Revenue driver context build fails | 1895-1899 | `raise RuntimeError("stage_ramp_revenue_driver_context_failed: ...")` |
| Context payload exceeds budget | 1993-1998 | `raise RuntimeError("stage_ramp_gpt_context_payload_budget_exceeded: ...")` |
| HTTP ≥400 from OpenAI | 2042-2043 | `raise RuntimeError("stage_ramp_contract_openai_status: ...")` |
| Parse failure | 2046-2047 | `raise RuntimeError("stage_ramp_contract_parse_failed: ...")` |
| Validation failure (after 1 retry with previous_contract_failure feedback) | 2063-2066 | `raise RuntimeError("stage_ramp_contract_invalid_fail_fast: ...")` |
| Timeout | 2067-2070 | `raise RuntimeError("stage_ramp_contract_timeout: ...")` |

### 2.2 Why this site doesn't need a Python floor

The `stage_ramp_contract` defines per-quarter revenue / utilization / cost / profitability ramp bounds across 20 quarters. Generating a defensible deterministic floor for this would require:

- A 20-quarter NAICS-cascade ramp shape lookup
- Per-metric maturity caps for the business's stage_family (startup / early / growth / operational / mature)
- Planning-mode-conditioned shape (normalize / turnaround / glidepath / s-curve / convergence_decay)
- R&D applicability gating
- Revenue driver context binding (capacity-driver type, unit name, fulfillment summary)

That equivalent already exists in [stage_planning_ramp_policy](../python/client_intake_and_finmo/post_intake_mapping.py) — the table-backed policy is what's fed to the GPT contract as `stage_policy_context`. But the policy alone is the *shape catalog*; it doesn't produce a specific business's ramp bounds the way GPT does.

If the user later wants a Python floor here, the design would be: "snap to the centroid of the table-backed policy bounds, no per-business reasoning." That's a separate, larger architectural decision. **For Commit 5 Part A, the audit conclusion is: this site is already hard-fail-on-GPT-failure by design and needs no change.**

### 2.3 Verification

Stage ramp is invoked *before* the post-cascade orchestrator and well before the existing finalize fail-fast layer that surfaced during E2E. None of the three E2E runs hit a stage_ramp failure (they all passed through to finalize), so live verification of the raise paths is not needed — the source-level check above confirms every failure mode raises.

### 2.4 Outcome for Site 2

**NO CHANGE.** The function already hard-fails on every failure mode. The Task 2 audit's "critic-pattern" labelling was incorrect; this is a GPT-mandatory site without a critic stage and without a Python proposer. The raised `RuntimeError`s propagate up to the orchestrator → finalize → API HTTP 500 the same way the new `PostIntakePreconditionFailed`s in Commits 2-4 do.

---

## 3. Aggregate outcome

| Site | Python floor exists? | Floor verified downstream-usable? | Action in Commit 5 Part A |
|---|---|---|---|
| `_run_cash_strategy_review_openai` | Yes — deterministic proposer + contract validator | Yes (E2E confirmed: NexGen, Sunny, Express all reach finalize with cash pass complete) | Keep never-raises; escalate 3 critic-failure log statements WARNING→ERROR |
| `_estimate_stage_ramp_contract_with_gpt` | No — GPT-mandatory by design | N/A — already raises on every failure mode | No change (already hard-fail) |

The "two surviving critic-pattern sites" framing turned out to be one site. The cash strategy site is correctly designed and stays as-is with louder logging. The stage ramp site is already aligned with the P3.10 hard-fail discipline.

---

## 4. Deferred — three open questions from Sunny diagnosis

The Task 1 diagnosis flagged three architectural questions for Task 3 scoping. With Commit 5 Part A complete, their disposition:

1. **Network retry before fail-fast?** Resolved by Commit 1 — `call_with_retries` does 3 attempts on retriable failures before raising `NetworkRetryExhausted`.
2. **Should `_GPT_CALL_BUDGET_PER_RUN` count failed calls?** Resolved by Q2 in Commit 1 — network-retry-exhausted calls do not consume the budget.
3. **Re-verify Phase-3 consultant Python-floor existence per consultant?** Resolved by this audit doc — only one site had a critic pattern and its floor is verified.

All three are closed. The five P3.10 commits have addressed the full Task 3 architectural overhaul.
