# P3.32 K11 — Handler-Contract Awareness Audit (Phase 1, read-only)

**Status:** Read-only investigation. NO code changes. Awaiting user
review before any implementation.
**Trigger:** Sunny Glaze Donuts post-K10 retry failed
`stage_ramp_revenue_path_not_applied` at finalize. Investigation
([p3_32_k10_sunny_stage_ramp_investigation.md](./p3_32_k10_sunny_stage_ramp_investigation.md))
established that H2 (GPT exhaustion handler) has ZERO references to
`stage_ramp_contract` in its source and authors revenue anchors
blind to H4's per-quarter `rev_max` bounds. The user directed
universalizing the contract-awareness pattern across all handlers
rather than fixing H2 alone.
**Scope:** every post-intake handler / GPT-driven decision point and
every canonical contract that constrains values it might author.
**Output:** handler × contract matrix + per-gap evidence + per-gap
fix-shape candidates.

---

## §1 Handler inventory (the rows of the matrix)

The post-intake pipeline has the following decision-authoring sites.
"Authors" means the site WRITES specific lever_ids or contract
fields. "Reads-only" sites are excluded from the audit (they
consume contracts, they don't produce values constrained by them).

| # | Site | Entry point | Authors | Architecture |
|---|------|------------|---------|--------------|
| **H2** | GPT exhaustion handler | `run_gpt_exhaustion_handler` at [handler.py:756](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L756) | revenue::Unit Price / Capacity / Utilization · expenses::COGS / Marketing / G&A / R&D · 5 working-capital drivers | tool-calling session (`compute_full_trajectory`) |
| **H3** | Funding handler | `run_funding_handler` at [handler.py:474](../../python/client_intake_and_finmo/post_intake_funding_handler/handler.py#L474) | schedules::Debt Issuance / Repayment · balance_sheet::Owner's Capital / Other Equity / Distributions | Python proposer first; GPT tool-calling session (`compute_cash_trajectory`) on residual |
| **H4** | Stage ramp handler | `run_stage_ramp_handler` at [handler.py:252](../../python/client_intake_and_finmo/post_intake_stage_ramp_handler/handler.py#L252) | the entire `stage_ramp_contract.quarter_ramp_grid` (rev_target / rev_max / cogs / marketing / rd / ga / lease / ni_floor / posture / utilization_cap) | Python deterministic builder first; GPT tool-calling session (`probe_stage_ramp_contract`) on validator failure |
| **HC** | Handler C / Payroll | `run_payroll_tool_calling_session` at [tool_calling_session.py:657](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py#L657) | payroll_headcount_schedule (labor_intensity_class / wage_positioning_tier / wage_positioning_multiplier / capacity_units_per_supporting_fte / target_payroll_percent_of_revenue / per-OEWS-title FTE grid Q1-Q20) → derived: expenses::Payroll + revenue capacity envelope | tool-calling session (`get_payroll_revenue_sanity_bounds` / `find_classes_accepting_target_payroll_pct` / `propose_payroll_headcount_schedule`) — migrated K9, signal-enriched K10 |
| **H5** | Stage_ramp single-shot estimator | `_estimate_stage_ramp_contract_with_gpt` at [contracts/runner.py:2027](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L2027) | stage_ramp_contract (initial draft, before H4 refinement on validator failure) | strict-mode structured output, single-shot |
| **UC** | Unified convergence GPT | `_run_unified_convergence_openai` at [convergence/runtime.py:2776](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L2776) | per-quarter target_values for the numeric solver (writable_lever_catalog scope) | structured output |
| **CS** | Cash strategy proposer (deterministic) | `propose_cash_strategy_review_decision` at [post_intake_cash/cash_strategy_proposer.py:184](../../python/client_intake_and_finmo/post_intake_cash/cash_strategy_proposer.py#L184) | per-quarter funding_source selections (which lever fills each required_funding_quarter) | pure deterministic Python |
| **CR** | Cash strategy review GPT critic | `_run_cash_strategy_review_openai` at [post_intake_cash/runner.py:1997](../../python/client_intake_and_finmo/post_intake_cash/runner.py#L1997) | cash_strategy_review amendments to CS's proposal | GPT critic on CS output |
| **(aux)** | R&D applicability | `_estimate_r_and_d_applicability_with_gpt` at [contracts/runner.py:1397](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1397) | (constant `True` post-P3.10; no real decision) | N/A — universal constant |
| **(aux)** | Balance sheet seed | `_estimate_balance_sheet_contextual_seed_with_gpt` at [contracts/runner.py:1447](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L1447) | applicability flags for BS seed levers | Python proposes; GPT critic |
| **(aux)** | Realism verification critic | `_run_realism_verification_openai` at [contracts/runner.py:3921](../../python/client_intake_and_finmo/post_intake_contracts/runner.py#L3921) | per-issue verdicts (resolved / improved / stalled) | Python proposes; GPT critic; doesn't author levers |
| **(aux)** | Wage estimator | `_estimate_wage_with_gpt` at [people_roles.py:238](../../python/client_intake_and_finmo/people_roles.py#L238) | per-role wage estimates at intake | intake-time only; not runtime |

H2, H3, H4, HC, H5, UC, CS, CR are runtime authoring sites. The four
`(aux)` rows either author a constant, propose-critique (Python is
the floor), or operate at intake-time — they're not in the K11
audit scope.

---

## §2 Canonical contracts (the columns of the matrix)

Contracts that CONSTRAIN authored values. "Per-quarter" means the
constraint is indexed by quarter_index 1..20; "per-class" means
indexed by a categorical (low/medium/high/expert; or
floor/market/premium/specialized).

| Contract | Lives in | Constrains | Currently consulted by |
|----------|----------|-----------|------------------------|
| **stage_ramp_contract** (per-quarter) | state JSON (authored by H4) — `quarter_ramp_grid[].{rev_target, rev_max, rev_spike_max, max_util, cogs_target, cogs_max, marketing_max, rd_max, ga_max, lease_max, ni_floor, posture}` | The 7-PNL-driver trajectory + ni_floor downstream | H4 (author); H5 (validator); UC (reads via `_compact_business_world_contract_for_prompt` at [runtime.py:1937-1942](../../python/client_intake_and_finmo/post_intake_convergence/runtime.py#L1937-L1942)); HC (read-only context in initial prompt per K9 design memo D3); validators at finalize ([fail_fast.py:506](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L506)) |
| **payroll_revenue_sanity_bounds_json** (per-class) | SQL `post_intake_headcount_policy_lookup.payroll_revenue_sanity_bounds_json` — per labor_intensity_class min_pct/max_pct | HC's `target_payroll_percent_of_revenue` per chosen class | HC (Tool 1 `get_payroll_revenue_sanity_bounds`, Tool 2 `find_classes_accepting_target_payroll_pct`, validator) — DONE via K9 |
| **post_intake_planning_mode_policy_lookup** | SQL | stage_family + planning_mode + posture rules (which postures are allowed when) | H4 stage_policy arg |
| **post_intake_finalize_realism_check_lookup** | SQL | per-metric realism bands (gate_kind hard_fail/warn/skip; primary_levers; adaptation_family) | H2 (`compute_metrics_to_mute` at [handler.py:665](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/handler.py#L665) reads to know which metrics to mute post-commit); realism gate at finalize |
| **post_intake_cash_policy_lookup** | SQL | cash-strategy modes + buffer policies + ceiling policies | CS (lever_bounds, cash_strategy_mode); CR (critic operates on CS output) |
| **post_intake_industry_baseline_lookup** | SQL | NAICS-keyed baseline values (cohort norms) | Deterministic Python builders (H4 baseline, marketing baseline) |
| **lever_bounds** (per-lever per-quarter, derived) | runtime state | per-quarter min/max for each writable lever | H3 (passed into session as `lever_bounds`); UC; CS |

---

## §3 The handler × contract matrix

**Y = consults at iteration time. N = does not consult. n/a = not
applicable (handler doesn't author values this contract constrains).
Bold N = identified gap.**

| Handler | stage_ramp_contract | payroll_sanity_bounds | realism_check_lookup | cash_policy_lookup | planning_mode_policy | industry_baseline | lever_bounds |
|---------|---------------------|-----------------------|----------------------|---------------------|----------------------|-------------------|--------------|
| **H2** (PNL/WC) | **N** (the Sunny gap) | n/a (Payroll excluded since K1 F1+F2) | Y (mute logic) | n/a | n/a | n/a | partial (in operating_model) |
| **H3** (Funding) | **N** (indirect via ni_floor) | n/a | n/a (cash levers are gpt_authored; muting handled elsewhere) | partial (via cash_strategy_mode) | n/a | n/a | Y |
| **H4** (Stage ramp) | Y (author) | n/a | n/a | n/a | Y (stage_policy) | Y (baseline builder) | n/a |
| **HC** (Payroll) | Y (read-only context) | Y (Tool 1 + Tool 2 + validator) | n/a | n/a | n/a | n/a | n/a |
| **H5** (Stage ramp single-shot) | Y (author) | n/a | n/a | n/a | Y | Y | n/a |
| **UC** (Unified convergence) | Y (compacted into prompt) | n/a (Payroll out of UC scope) | Y (issue context) | n/a | n/a | Y | Y |
| **CS** (Cash strategy proposer) | **N** (indirect via ni_floor) | n/a | n/a | Y (via lever_bounds + cash_strategy_mode) | n/a | n/a | Y |
| **CR** (Cash strategy critic) | **N** (same indirect) | n/a | n/a | Y (operates on CS) | n/a | n/a | Y |

**Bolded N cells are the identified gaps. Three sites: H2, H3, CS/CR.**

---

## §4 Per-gap analysis

### Gap 1 — H2 ↔ stage_ramp_contract (PRIORITY 1)

**A1. What contract constrains values H2 authors?**

H2 authors the 7 PNL drivers (revenue triple + COGS/Marketing/SGA/
R&D %) plus 5 WC drivers. The `stage_ramp_contract.quarter_ramp_grid`
constrains EVERY one of the 7 PNL drivers' per-quarter trajectories:
- `rev_target` / `rev_max` constrain revenue growth (capacity ×
  unit_price × utilization derived).
- `cogs_target` / `cogs_max` constrain COGS%.
- `marketing_max`, `rd_max`, `ga_max`, `lease_max` constrain those
  ratios.
- `ni_floor` is the downstream consequence H2's choices must respect.
- `max_util` constrains H2's utilization anchor at Q1/Q11/Q20.

**A2. Does H2 currently consult it?** NO.

Repository-wide grep:
```
grep -rn "stage_ramp" python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/
→ 0 matches
```

H2's tool-calling session never receives `stage_ramp_contract`:
- `run_tool_calling_session` at [tool_calling_session.py:441](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py#L441) does not accept stage_ramp_contract as input.
- Its `operating_context` dict (built around line 755) contains `operating_model`, `q1_state`, `exhaustion_diagnostic`, `failing_metrics` — but NOT `stage_ramp_contract`.
- The mini_finmo viability_checks at
  [mini_finmo.py](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/mini_finmo.py) check EBITDA-margin trajectory metrics only — no per-quarter rev_max/cogs_max/etc. enforcement.
- The SYSTEM_PROMPT at
  [prompts.py](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/prompts.py) does not mention stage_ramp / rev_max / quarterly bounds.

**A3. Would consulting it have prevented historical failures?** YES.

Sunny Glaze Donuts post-K10 retry on 2026-05-21 02:21:
- H4 produced stage_ramp_contract with `rev_max=0.06` per quarter
  (turnaround mode; deterministic Python builder).
- H2 (blind to rev_max) authored revenue anchors producing Q2-Q7
  growth ~8.6% to 11.3% per quarter — substantially over rev_max.
- finalize validator
  `assert_stage_ramp_revenue_path_applied` at [fail_fast.py:506](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L506) fired.
- See [p3_32_k10_sunny_stage_ramp_investigation.md](./p3_32_k10_sunny_stage_ramp_investigation.md)
  §2 for revenue-growth diff between today (over rev_max) and
  yesterday (just within rev_max at boundary).

Yesterday's post-K9 Sunny had the SAME rev_max=0.06 contract but
H2's anchors happened to produce growth ~6% (at boundary). It
passed the stage_ramp validator but failed at acceptance gate
on `ebitda_positive_by_q11`. GPT non-determinism in H2's anchor
choice determines which validator fires.

The latent issue extends beyond rev_max: H2 also doesn't see
`cogs_max`, `marketing_max`, `ga_max`, `rd_max`, `lease_max`,
`max_util`. Any of these can produce the same shape — H2 authors
in-policy-for-realism-but-out-of-policy-for-stage-ramp values that
the finalize validator then rejects.

**A4. Fix shape candidates** (NOT a recommendation; for user
review):

Option A — **Thread `stage_ramp_contract` into H2 operating_context
+ mini_finmo enforces rev_max/cogs_max/etc.** This is the
tool-result-driven coherence pattern (audit C4). H2's mini_finmo
already runs FINMO under proposed anchors; it adds stage_ramp-
coherence checks to its `viability_checks` aggregate. GPT iterates
until both viability AND stage_ramp checks pass.

  Scope: ~250-400 LOC.
  Doctrine: tool-result-driven (audit C4 pattern).
  Risk: medium. The mini_finmo runs the math; adding the
  per-quarter rev_max/cogs_max comparison is mechanical. Updating
  prompt + tests is straightforward.

Option B — **Expose stage_ramp bounds via new H2 tool (e.g.,
`get_stage_ramp_bounds_per_quarter`)** analogous to K9 Tool 1 for
payroll. GPT calls it before authoring anchors; understands per-
quarter constraints up-front.

  Scope: ~300-450 LOC.
  Doctrine: tool-calling canonical (doctrine §10.4).
  Risk: medium. Tool addition + prompt update; mini_finmo could
  remain unaware (the tool alone informs GPT).

Option C — **Combination** — Both Option A (mini_finmo
enforcement) and Option B (queryable tool). Mini_finmo provides
the hard backstop (refuses to all_pass on stage_ramp violations);
the tool provides explicit signal.

  Scope: ~400-550 LOC.
  Doctrine: belt + suspenders.
  Risk: medium-low.

### Gap 2 — H3 ↔ stage_ramp_contract (indirect via ni_floor)

**A1.** H3 authors funding levers. The direct constraints are
`lever_bounds` (per-quarter min/max for each funding lever) — H3
already consults these. The INDIRECT constraint:
- Debt issuance (and the offsetting principal repayment schedule)
  creates interest expense, which depresses net income.
- `ni_floor` from stage_ramp_contract is a downstream check on
  net income margin.
- H3's debt choices can push net income below ni_floor.

**A2. Does H3 currently consult stage_ramp_contract?** NO.

```
grep -rn "stage_ramp" python/client_intake_and_finmo/post_intake_funding_handler/
→ 0 matches
```

H3's tool-calling session inputs are `cash_buffer_violations`,
`lever_bounds`, `cash_strategy_mode`, the four broadened
violation categories (distribution / surplus / contract /
hard-rule), and the Python allocator's first-pass result. No
stage_ramp_contract field.

H3's `compute_cash_trajectory` tool returns
`buffer_residual_violations` — buffer-only, no NI margin check.

**A3. Would consulting it have prevented failures?** NO EVIDENCE.

The P3.28 sweep + the K9-era CareFirst / Anderson & Blake /
Skyward / Sunny runs did NOT report H3-induced ni_floor failures.
Funding-induced interest expense was not observed to push NI
below ni_floor in sweep evidence.

This is a LATENT gap that's not currently surfacing failures.
Closing it preempts a class of bugs that could surface in
remaining drafts 5-28, but is not load-bearing for the current
verification round.

**A4. Fix shape candidates:**

Option A — **Add stage_ramp_contract.ni_floor to H3 prompt + tool
result** so H3 can see whether its proposed funding plan keeps
NI margin above ni_floor.

  Scope: ~100-200 LOC.
  Risk: low.
  Doctrine: same as gap 1 fix.

Option B — **Defer** — close the gap if/when it surfaces in
sweep failures.

### Gap 3 — CS / CR ↔ stage_ramp_contract (indirect; same shape as H3)

Same shape and analysis as H3. The deterministic Python proposer
and its GPT critic don't see ni_floor either. No evidence of
ni_floor failures driven by cash-strategy choices in sweep
history.

**Fix shape:** same as Gap 2; same options.

---

## §5 Cross-cutting findings

### Finding 1 — The contract-awareness gap is concentrated at the H2 site

H2 is unique among the runtime authoring sites in that it iterates
on a LARGE set of per-quarter drivers (7 PNL + 5 WC) without
visibility into per-quarter contract bounds. H4 (which authors
the contract), HC (which authors payroll and reads its policy
bounds), UC (which reads stage_ramp_contract bounds), and H5
(which validates) all have appropriate contract visibility for
THEIR authoring scope.

H3 / CS / CR have an indirect-only gap (ni_floor via interest
expense / distributions). No empirical failure evidence.

### Finding 2 — K9's Handler C pattern is the prototype

The K9 / K10 migration of Handler C is the canonical example of
the contract-awareness pattern:
1. Tool 1 surfaces per-class bounds directly (
   `get_payroll_revenue_sanity_bounds`).
2. Tool 2 surfaces accepting/rejecting classes for a candidate
   target (`find_classes_accepting_target_payroll_pct`).
3. The propose tool runs the full validator chain and returns
   structured failures with IN-LINE enrichment (K8 alternatives
   IN-LINE in failure entries).
4. The user_context carries an intake-implied operating-intensity
   signal (K10) to inform class selection.

The pattern abstracts to: "the authoring handler reads the
contract, exposes contract bounds via tool surface, and surfaces
contract-violation diagnostics IN-LINE in failure feedback."
H4's session has a similar shape for stage_ramp_contract itself.

H2's session lacks all of this for stage_ramp_contract.

### Finding 3 — The fix shape varies by what the handler IS doing

- **H2 iterates on a math-heavy trajectory** (computes EBITDA
  via mini_finmo). The natural fix is to ADD stage_ramp
  per-quarter checks to the mini_finmo viability_checks — a
  COMPUTATIONAL constraint, not a lookup tool. This matches H2's
  shape: it already iterates on a tool that runs FINMO; it just
  needs that tool to enforce one more class of constraints.
- **HC iterates on class-and-target choices** (no math heavy
  lifting, mostly enum selection + per-OEWS-title grid). The
  natural fix was a LOOKUP tool (K9 Tool 1 / Tool 2) — surface
  per-class bounds and which classes accept what target.

So K11.1 (H2 stage_ramp awareness) should follow Option A
(mini_finmo enforcement), with Option B (queryable tool) as
add-on signal. This is the same pattern, instantiated
differently for H2's session shape.

### Finding 4 — Doctrine §10.5 is the right place for the universal rule

The user proposed:
> "Every handler that authors values constrained by canonical
> contracts must consult those contracts at invocation time.
> Contract data must be:
>   - Read from canonical source (SQL/state)
>   - Passed into the handler's tool schema or decision logic
>     as bounds/constraints
>   - Enforced by the handler's validator
>   - Surfaced in failure feedback so iterative refinement can
>     adapt
> Handlers that don't consult applicable contracts are
> architecturally incomplete and must be brought into
> compliance."

This belongs as a new section in doctrine.md (§10.5, following
the existing §10.1 K7 doctrine correction, §10.2 K4(b)
elimination, §10.3 K1 F6 companion, §10.4 K9 tool-calling
canonical).

### Finding 5 — Implementation prioritization

| Priority | Gap | Evidence | Scope est. | Risk |
|----------|-----|----------|-----------|------|
| 1 | H2 ↔ stage_ramp_contract | Sunny post-K10 retry; latent for other drafts | ~250-550 LOC | medium |
| 2 | H3 ↔ stage_ramp_contract.ni_floor | NO evidence of failures; latent | ~100-200 LOC | low |
| 3 | CS / CR ↔ stage_ramp_contract.ni_floor | NO evidence; latent | ~100-200 LOC | low |

P1 is load-bearing for the current 4-baseline verification round.
P2 + P3 are preempted-gap-closures aligned with doctrine §10.5.

---

## §6 Recommended sequencing (for user review)

A. **Implement K11.1 (P1: H2 stage_ramp awareness) only**, defer
   P2 + P3 until evidence surfaces. Single commit ~250-550 LOC.
   Doctrine §10.5 added. Re-verify 4 baselines.

B. **Implement K11.1 + K11.2 + K11.3 together** as a "universalize
   the pattern" landmark commit (or split). Total ~450-950 LOC;
   likely splits into 2-3 sub-commits to stay under 800-LOC
   single-commit cap. Doctrine §10.5 added.

C. **Implement K11.1 + doctrine §10.5 only**, treat K11.2 / K11.3
   as documented-but-deferred (memo lists them as `(P2/P3 latent;
   close when evidence surfaces)`). Acceptable per the directive
   "If audit reveals more gaps than expected, propose phased
   implementation rather than blocking."

D. Some other shape user identifies.

---

## §7 NO IMPLEMENTATION

Per directive:
> PAUSE after audit. User reviews findings before implementation.

This memo is the audit deliverable. Awaiting user direction on:
1. Which sequencing option (A / B / C / D).
2. For K11.1: which fix shape (Option A mini_finmo enforcement,
   Option B queryable tool, Option C combination).
3. For K11.2 / K11.3: implement or defer.
4. Doctrine §10.5 wording (the proposed text in §5 Finding 4 is
   the user's own from the directive; confirm or amend).
