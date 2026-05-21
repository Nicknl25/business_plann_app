# P3.32 Draft 3 (Skyward Express Airlines) — Handler C timeout investigation

**Status:** Investigation memo (no code changes proposed yet). Per user
directive: investigate the four hypotheses before any fix, cite file:line
for code paths, cite actual run data for behavioral evidence.

**Run summary:**
- Draft ID: `41f014a5567041d99b2572a67fe6b03d` (Skyward Express Airlines,
  NAICS 481111, rebalance, operating)
- First run (`f3fdf965ce3745e3a52421f201a73941`): FAIL with
  `revenue_driver_formula_contract_failed` at 4 quarters with sub-dollar
  float deltas (delta=0.030 to 0.046 on revenue $16-21M). K6 pattern.
- Retry (`749e3c3b3f7f416b894551146ed0dacd`): FAIL with
  `pre_cash_gate_gpt_authorable_checks_unfixed_after_handler` — 15
  payroll-touching violations. K1 F5 route was attempted; F5 invoked
  Handler C; Handler C timed out at 180s with
  `payroll_headcount_contract_timeout@payroll_headcount_contract_request:
  GPT headcount schedule exceeded total 180s payroll cycle budget before
  convergence.`

**Key shape:** The two failure modes differ (K6 first run, F5+Handler-C
timeout retry). The retry's failure is the FOCUS of this investigation
per user direction. The K6 float-tolerance question (first run) remains
open for later large-revenue drafts.

---

## Code paths verified

**Handler C entry:** `estimate_payroll_headcount_schedule_with_gpt`
at [post_intake_headcount/schedule.py:2180](../../python/client_intake_and_finmo/post_intake_headcount/schedule.py#L2180).

**Iterative refinement loop:** lines 2383-2549. Key constants and
control flow:
- `_PAYROLL_ITERATIVE_HARD_CAP_ROUNDS = 10` (hard cap on rounds)
- `timeout_seconds = float(sequence_settings.get("timeout_seconds") or
  180.0)` at line 2370 — the 180s wall-clock budget for the WHOLE cycle
- `total_start = time.perf_counter()` at line 2390 (fresh per Handler C
  invocation — NOT shared across F5 routes)
- Per-round preflight at line 2422-2436: if `remaining_seconds < 15.0`,
  hard-fail with `payroll_headcount_contract_timeout` BEFORE making
  another API call. This prevents starting a request that can't finish.
- Per-round postflight at line 2537-2549: if `total_elapsed >
  timeout_seconds`, hard-fail same code.
- GPT API call at line 2528 with `timeout_seconds=remaining_seconds`
  passed to `_post_openai`; that helper uses `(connect=10, read=max(10,
  remaining_seconds))` at line 652.

**State persistence between rounds:**
- Base `user_context` is captured once before the loop (not re-read).
- Only `last_failure_packet` is threaded into `request_context.
  previous_contract_failure` per round (lines 2442-2464).
- Round N receives only Round N-1's failure feedback (not the full
  history of all prior failures).
- Counter `_PAYROLL_ITER_GPT_CALL_COUNT` is monotonic per round
  (invariant assertion at line 2521-2526).

**SQL config:** `timeout_seconds=180, max_attempts=3` at
[post_intake_mapping.py:883](../../python/client_intake_and_finmo/post_intake_mapping.py#L883)
for the `payroll_headcount_schedule` process step.

---

## H1 evaluation — Budget too tight for airline complexity

**Skyward payload size:**
- Unique OEWS roles selected: **7**
  - Aircraft Mechanics and Service Technicians
  - Airline Pilots, Copilots, and Flight Engineers
  - Chief Executive Officer (CEO)
  - Chief Operating Officer (COO)
  - Customer Service Representatives
  - Flight Attendants
  - Reservation and Transportation Ticket Agents and Travel Clerks
- Total rows in `payroll_headcount.rows`: **140** (7 roles × 20
  quarters)
- Quarter totals: 20
- Revenue driver rows: 3

**Comparison to known-pass baselines:**
- CareFirst (draft 2, GENUINE PASS): 60 rows (3 roles × 20 quarters),
  Handler C succeeded in 5 tool calls / converged in seconds.
- Anderson & Blake (draft 1, GENUINE PASS): comparable smaller payload.

**Assessment:** 7 roles vs 3 roles is 2.3× more output per GPT response.
Each round's structured-output payload is correspondingly larger. GPT
response time scales super-linearly with output size for structured
outputs. A round that takes 25s for 3 roles could take 60-90s for 7
roles. At 60s/round, only 3 rounds fit in 180s; at 90s/round, only 2
rounds. CareFirst succeeded in 5 tool calls; Skyward only got 2-3 before
budget exhaustion.

**H1 partially supported but not fully diagnostic:** The complexity is
real, but the question is whether 2 rounds is structurally insufficient
or whether the GPT iteration is also drifting (H2). Cannot distinguish
without per-round latency data which is NOT currently persisted to
planning_run_json.

---

## H2 evaluation — GPT structured output drift

**The persisted planning_run_json does NOT contain per-round trace
data** for the Handler C iterative refinement loop. Only summary stats
(round_n at failure, total elapsed_seconds, timeout_seconds) are in
`terminal_failure_context.fail_fast_details`. The per-round response
content, structured field values, and rationale text are NOT preserved.

**The API server stdout log** for the run also does not contain
per-round structured field comparison; the log captures only high-level
trace lines (e.g., `finmo_std_layer1_trace q=1 window=[...] value=0.0`).

**Direct conclusion: H2 cannot be evaluated from existing artifacts.**
The diagnosis the user requested ("does target_payroll_percent_of_revenue
in the structured field match what the rationale claims?") is
unanswerable without round-by-round persisted trace.

**Required tooling for H2 evaluation:** Per-round logging that persists
to either planning_run_json or a dedicated SQL diagnostic column:
- Round N start time
- Round N input context size (chars)
- Round N GPT API call duration
- Round N response: structured output (compact JSON), rationale text
  (truncated)
- Round N validator outcome (pass / fail with code)
- Round N failure feedback packet built for Round N+1

This is L-4 tooling (testing/diagnostic infrastructure) — needed not
just for this investigation but for any future Handler C convergence
diagnosis.

---

## H3 evaluation — Handler C state alignment issue (F6 class)

**Code path inspection** at lines 2390-2549 confirms:
- Base `user_context` is set ONCE at function entry (line 2390 area —
  passed in via `_build_payroll_headcount_user_context` upstream).
- `previous_contract_failure` is the ONLY field threaded across rounds.
- `last_failure_packet` updates with round results (line 2406+).
- `request_context = deepcopy(user_context)` at line 2441 — deep-copies
  the base context per round.
- No re-reading of SQL state, model_input, finmo, or payroll_headcount
  between rounds within the same Handler C invocation.

**Assessment:** Handler C is internally consistent across rounds within
a single invocation. No F6-class drift WITHIN the loop.

**However:** Handler C is invoked TWICE in this flow:
- First by `_rebuild_payroll_authority` in convergence runner
  (post_intake_convergence/runner.py:780-823) with a `previous_contract_
  failure` seed.
- Second by F5's `route_payroll_feasibility_to_handler_c` at
  orchestrator.py:~2270 with the pre-cash-gate violations as
  `previous_contract_failure`.

Each invocation has its OWN 180s budget (`total_start = perf_counter()`
inside `estimate_payroll_headcount_schedule_with_gpt`). So the SECOND
invocation (F5's) starts with a full 180s budget.

The CareFirst F6 case was different: the orchestrator's local
payroll_headcount drifted from the canonical SQL column. Skyward's
F5 invocation passes `payroll_headcount=payroll_headcount or {}` from
the orchestrator's local variable. If F6's re-sync ran (it should have
— it's at the entry of `_run_post_cascade_completion`), then this
local should already be canonical. But Skyward failed BEFORE F6's
re-sync had a chance to take effect on the F5 invocation's payroll_
headcount argument...

**Actually:** F6's re-sync runs at the start of `_run_post_cascade_
completion`. F5 runs LATER in the same function. So F6's re-sync IS
applied before F5 invokes Handler C. The payroll_headcount passed to
Handler C via F5 SHOULD be canonical at that point. This means
H3-WITHIN-F5 is NOT the cause.

**Assessment:** H3 ruled out. Handler C's stateless-between-rounds
discipline is intact, and F6's re-sync handles state alignment before
F5 invokes Handler C.

---

## H4 evaluation — Cross-domain adaptation gap

**Skyward profile:**
- NAICS 481111 (Scheduled Passenger Air Transportation)
- Planning mode: rebalance
- Business stage: operating
- Revenue scale at Q5+: $16-21M+ (large-revenue draft)
- 7 OEWS roles (high role diversity for an airline)

**Stage_ramp_contract for this NAICS:** Not directly inspectable
without re-running the draft, but the contract is GPT-generated by the
stage_ramp handler at intake time. Its `rev_max`, `utilization_cap`,
and cost-ratio constraints would be set based on the NAICS cohort
defaults + GPT's business-specific judgment.

**Cross-handler coordination:** F5 invokes Handler C alone, passing the
failing metrics as `previous_contract_failure`. Handler C can adjust:
- OEWS role selection
- FTE per role per quarter
- target_payroll_percent_of_revenue
- wage_positioning_tier / multiplier (within cohort options)

Handler C CANNOT adjust:
- Revenue side (Capacity, Unit Price, Utilization) — that's outside
  payroll's authority
- stage_ramp_contract bounds — that's the stage_ramp handler's
  authority
- Cash strategy — that's downstream

**The gate violation pattern:** 15 violations all
`metric_key=payroll_percent_of_revenue, source_check=stage_ramp_expense_
path_applied, actual_value=0.0, primary_levers=[expenses::Payroll]`.

The `actual_value=0.0` is suspicious. Either:
- (a) Payroll percent of revenue is genuinely 0 (e.g., payroll wasn't
  applied to model_input yet — pre-F6 alignment issue?), OR
- (b) The validator is computing the ratio with zero revenue (Q6-Q20
  revenue not applied)

If (a): F6's re-sync didn't apply on the F5 path? OR F6 fired but
Skyward's convergence runner produced a payroll_headcount that
disagrees with model_input.expenses.Payroll.values (which the
validator reads). If the values are 0 because the convergence runner
didn't apply them, that's a NEW F6-class bug surfacing on Skyward.

If (b): The validator reads stage_ramp_expense bounds at Q6+ but
applied revenue at Q6+ is 0 — possibly because the cascade hasn't
finished applying revenue ramps.

**Assessment:** H4 partially supported. The actual_value=0.0 pattern
strongly suggests something upstream (cascade, convergence) didn't
apply payroll OR revenue to model_input by the time the pre-cash gate
fired. This is more F6-adjacent than airline-specific. Could be a
NEW write-path bug NOT covered by K1 F1-F6 (e.g., the cascade pass
itself).

---

## Synthesis

The current evidence supports a MIXED diagnosis:
- **H1**: real complexity (7 roles → larger GPT output → slower
  rounds); contributes to but doesn't fully explain timeout.
- **H2**: cannot evaluate without per-round persistence (L-4
  instrumentation gap).
- **H3**: ruled out for the Handler C internal loop.
- **H4**: actual_value=0.0 pattern suggests an upstream
  write-path that didn't apply payroll OR revenue by gate time.
  Could be a NEW F-class bug.

**The HONEST answer:** I cannot propose a specific fix shape with
confidence given the current persisted artifacts. The two most likely
fixes are:
1. **L-4 instrumentation** for Handler C iterative refinement
   (per-round persisted trace) so the next failure surfaces H1 vs H2
   evidence directly. This is prerequisite to fix-shape selection.
2. **Investigate the actual_value=0.0 violations** by inspecting
   `assert_stage_ramp_expense_path_applied` at
   [post_intake_fail_fast/fail_fast.py](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py)
   to determine whether the zero is in payroll dollars or in revenue
   dollars. If payroll, F6-class bug. If revenue, cascade-side bug.

**Recommended next step:** Build L-4 instrumentation (~80 LOC), re-run
Skyward, then diagnose with real per-round data. Move to draft 4 in
parallel while gathering evidence from other drafts.

**RUNNER_ERROR classification appropriate here:** Two runs, no
viable plan produced, root cause not yet diagnosable from current
artifacts. Not flailing per user direction (no third retry). Sweep
continues; Skyward returns after L-4 instrumentation lands.

---

## Open questions

1. Does the convergence runner persist payroll AND apply to
   model_input.expenses.Payroll.values? (Check
   convergence/runner.py:_apply_payroll_authority chain.)

2. Is `assert_stage_ramp_expense_path_applied` reading from the
   workbook's view of the validator's expected payroll, or from
   model_input.expenses.Payroll.values, or from
   payroll_headcount.quarter_totals? File:line ref needed.

3. Per-round latency budget — would lifting 180s → 300s materially
   help, or would GPT still drift? Cannot answer without H2 data.

These belong in the next iter's pre-fix investigation.
