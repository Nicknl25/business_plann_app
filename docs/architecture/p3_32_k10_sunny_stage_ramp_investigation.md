# P3.32 K10 — Sunny stage_ramp_revenue_path investigation

**Status:** Read-only investigation. NO fix proposed (per user
direction). Awaiting user direction before any fix attempt.
**Failure mode this investigation covers:**
`stage_ramp_revenue_path_not_applied` at
post_intake_finalize_validation_global, observed on Sunny Glaze
Donuts (`6d37c6b98ace41ee9c91dd5fbf68b83e`) post-K10 retry on
2026-05-21 02:21.
**K10 commit:** `475e100`
phase_9_p3_32_k10_handler_c_class_selection_operating_intensity_signal

---

## Q1 — Did Sunny ever fail `stage_ramp_revenue_path_not_applied` pre-K10?

**No.** This is a new failure mode for Sunny.

| Run | Outcome | Failure mode (if any) |
|-----|---------|----------------------|
| P3.28 baseline | GENUINE_PASS 16/16 | (none) |
| Post-K9 (2026-05-21 01:58) | acceptance_gate_failed 13/16 | `ebitda_positive_by_q11` hard-fail at K4 acceptance gate (Q11 NI margin -0.17%); `landed_best_effort_no_all_pass` at 4 H2 tool calls |
| Post-K10 retry 1 (2026-05-21 02:17) | system_run_failed | `payroll_tool_calling_session_turn_failed` — `network_retry_exhausted` (OpenAI API timeout, runner-error class) |
| Post-K10 retry 2 (2026-05-21 02:21) | system_run_failed | `stage_ramp_revenue_path_not_applied` at finalize — Actual FINMO revenue growth violates `rev_max` from `stage_ramp_contract` |

The post-K9 run COMPLETED finalize validation (reached
`post_intake_finalize_validation_completed`) without firing the
stage_ramp_revenue_path validator. So yesterday's revenue
trajectory was within rev_max=0.06; today's was not.

---

## Q2 — Trace data flow: Handler C → stage_ramp validation

### Pipeline order

1. `H4 stage_ramp_handler` (in `post_intake_stage_ramp_handler/`)
   authors `stage_ramp_contract` (rev_target, rev_max per quarter).
   Runs BEFORE Handler C.
2. Deterministic Python proposer produces initial `model_input`
   for revenue / expenses.
3. `Handler C` (in
   [post_intake_headcount/tool_calling_session.py](../../python/client_intake_and_finmo/post_intake_headcount/tool_calling_session.py))
   authors `payroll_headcount` schedule. Apply chain writes
   `model_input.revenue.capacity_units` from
   `FTE × capacity_units_per_supporting_fte` via
   `apply_payroll_supported_capacity_to_model_input`.
4. `H2 GPT exhaustion handler` (in
   [post_intake_gpt_exhaustion_handler/tool_calling_session.py](../../python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/tool_calling_session.py))
   authors the 7 PNL drivers (revenue triple + COGS/Marketing/SGA/
   R&D %). Sees `model_input` (including capacity from Handler C),
   produces unit_price and utilization anchors. Runs WHEN
   exhaustion is detected.
5. `finalize validation` — assert_stage_ramp_revenue_path_applied
   at
   [fail_fast.py:506](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L506)
   checks that actual FINMO revenue growth per quarter stays
   within `rev_target ≤ growth ≤ rev_max` from the stage_ramp_
   contract.

### Where revenue trajectory comes from

- **Capacity** (revenue ceiling) ← Handler C's
  `capacity_units_per_supporting_fte × FTE`. Constant across
  20 quarters for Sunny (2.5 FTE × 17000 = 42,500
  units/quarter).
- **Unit price** ← H2's anchors at Q1/Q11/Q20 (interpolated).
- **Utilization** ← H2's anchors at Q1/Q11/Q20 (interpolated).
- **Revenue** = `capacity × unit_price × utilization` per
  quarter.

### Empirical revenue trajectories

Yesterday's post-K9 Sunny first 7 forecast quarters
(Q1...Q7 of live forecast):
```
Q1 = $121,729
Q2 = $129,349  → growth +6.26%  (rounded to 2dp = 1.06; AT boundary)
Q3 = $137,116  → +6.00%
Q4 = $145,028  → +5.77%
Q5 = $153,086  → +5.56%
Q6 = $161,291  → +5.36%
Q7 = $169,641  → +5.18%
```
All within rev_max=0.06. PASSED stage_ramp_revenue_path validator.

Today's post-K10 retry Sunny first 7 forecast quarters:
```
Q1 = $178,500
Q2 = $193,932  → growth +8.65%  (OVER rev_max=0.06)
Q3 = $215,816  → +11.29%        (OVER)
Q4 = $239,083  → +10.78%        (OVER)
Q5 = $263,766  → +10.32%        (OVER)
Q6 = $289,897  → +9.91%         (OVER)
Q7 = $317,508  → +9.52%         (OVER)
```
All over rev_max=0.06. FAILED.

### Q1 revenue delta (47% higher today)

Yesterday Q1=$121,729; Today Q1=$178,500. That's a 47% jump in
the starting forecast revenue. Capacity differs by only ~5%
(40,575 yesterday vs 42,500 today). The 47% delta is dominated
by H2's choice of unit_price + utilization anchors, NOT
Handler C's capacity.

### The two stage_ramp_contracts are IDENTICAL

| Field | Yesterday post-K9 | Today post-K10 retry |
|-------|-------------------|---------------------|
| stage_family | operational | operational |
| decision_source | python_deterministic_builder | python_deterministic_builder |
| planning_mode | turnaround | turnaround |
| Q1 rev_target / rev_max | 0.01 / 0.06 | 0.01 / 0.06 |
| Q11 rev_target / rev_max | 0.01 / 0.06 | 0.01 / 0.06 |
| Q20 rev_target / rev_max | 0.01 / 0.06 | 0.01 / 0.06 |
| Q1 / Q11 / Q20 posture | positive | positive |

Both runs received the SAME stage_ramp_contract. The H4 GPT
refinement layer was not invoked (deterministic Python builder
output passed H4's own validator).

### So what changed?

H2's authored revenue anchors. H2 produced a tighter, slower
trajectory yesterday (~6% growth, at rev_max boundary) and a
steeper trajectory today (~10% growth, over rev_max).

K10 changed:
- Handler C's class choice on Sunny (high → medium)
- Handler C's productivity (16230 → 17000)
- Capacity (40,575 → 42,500; ~5% increase)

K10 did NOT change:
- H4's deterministic stage_ramp builder
- H2's tool_calling_session module
- H2's authorities or prompt

**Hypothesis:** K10's class shift increased Handler C's capacity
output by 5%. H2 saw the slightly looser capacity and authored
more aggressive utilization/price anchors, pushing revenue
growth over rev_max. K10 INDIRECTLY influenced today's failure
by changing the capacity envelope H2 saw — but the FUNDAMENTAL
issue is that H2 doesn't see rev_max at all (see Q4 below).

---

## Q3 — Is this the H4 pattern from P3.28 sweep?

**No, it's a related-but-distinct shape.**

The P3.28 sweep recorded 4 stage_ramp failures (SwiftLogix,
SwiftCargo, Arrowline, ValueMart). The mode in those drafts was
`stage_ramp_contract_invalid` — H4's GPT-refined contract was
rejected by H4's own validator (the contract itself was
malformed or violated policy).

Sunny's failure today is `stage_ramp_revenue_path_not_applied`
— H4's contract is VALID, but the DOWNSTREAM revenue trajectory
doesn't match the contract. This is a different validator at a
different pipeline stage:

| Failure mode | Validator | Stage | What it checks |
|---|---|---|---|
| `stage_ramp_contract_invalid` (P3.28 sweep failures) | `_validate_stage_ramp_contract_payload` | H4 own validator (during refinement loop) | H4's contract obeys policy structure |
| `stage_ramp_revenue_path_not_applied` (today's Sunny) | `assert_stage_ramp_revenue_path_applied` ([fail_fast.py:506](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L506)) | post_intake_finalize_validation_global | actual FINMO revenue stays within H4-set rev_target / rev_max |

So Sunny is NOT a re-surfacing of the P3.28 sweep H4 pattern.
It's a different shape — coherence between H4's contract and
H2's downstream revenue anchors.

**But the underlying root cause is the same architectural gap:**
the system has multiple GPT-authored handlers (H2, H3, H4) that
each see partial context. H4 sets stage_ramp bounds; H2 doesn't
read them when authoring revenue anchors. The drafts where this
gap surfaces depend on which combination of (H4-tight-rev_max,
H2-aggressive-anchors, intake-driven-capacity) crosses the
validator threshold.

---

## Q4 — What triggered Sunny to cross into this failure now?

### Architectural root cause

The H2 GPT exhaustion handler has **zero references** to
`stage_ramp_contract` or `rev_max` in its source:
- `python/client_intake_and_finmo/post_intake_gpt_exhaustion_handler/`
  has 0 matches for `stage_ramp` across all `.py` files (confirmed
  via repo-wide grep on
  `post_intake_gpt_exhaustion_handler/*.py` for the literal
  string `stage_ramp` — no matches).
- H2's mini_finmo does not check rev_target / rev_max during
  the trajectory probe.
- H2's operating_model passed in the user prompt does not
  surface stage_ramp_contract.

**Consequence:** H2 authors revenue anchors without knowing
H4's per-quarter QoQ growth bounds. The constraint exists in
the system (H4 wrote it, finalize validator enforces it) but
H2 is BLIND to it during iteration. H2's tool result
(`viability_checks`) does not include a stage_ramp-coherence
check.

### Why Sunny crossed the threshold today specifically

Three interacting factors:

1. **H4's deterministic builder produces tight rev_max=0.06 for
   Sunny.** This is universal — same input produces same output
   for any run with Sunny's intake state. Both yesterday and
   today's runs received rev_max=0.06.

2. **H2's anchor choices vary across runs (GPT non-determinism).**
   Yesterday's H2 chose anchors producing ~6% growth (at
   boundary). Today's H2 chose anchors producing ~10% growth
   (over boundary).

3. **K10 marginally relaxed the capacity ceiling** (from
   Handler C: 40,575 → 42,500 units/quarter, ~5% looser). This
   gave H2 more revenue headroom to fill, plausibly pushing
   today's H2 toward more aggressive anchors.

### What K10 did + did not cause

- K10 DID cause Handler C to choose `medium` class for Sunny
  (objective achieved per the K10 design memo).
- K10's capacity output (5% higher than yesterday's K9 high-
  class output) MAY have nudged H2 toward more aggressive
  anchors.
- K10 did NOT introduce the H2↔H4 coherence gap. That gap is
  pre-existing and architectural.
- The post-K9 Sunny run failed at the K4 acceptance gate with
  the SAME stage_ramp_contract (rev_max=0.06). If yesterday's
  H2 had happened to author anchors producing ~10% growth
  instead of ~6%, yesterday would have failed at finalize
  validation instead of at acceptance gate.

### Why Skyward, CareFirst, Anderson & Blake aren't necessarily affected

- **Skyward post-K9:** GENUINE_PASS. Different planning_mode
  (`rebalance` not `turnaround`), and H4 produced rev_max=0.14
  for Skyward. With looser rev_max=0.14, even aggressive H2
  anchors (~10% growth) stay within bounds. The Skyward win is
  protected by Skyward's intrinsically looser stage_ramp
  contract — but the underlying coherence gap is unfixed.
- **CareFirst:** not yet re-run post-K10. CareFirst is also
  turnaround mode but a different industry. Could exhibit the
  same failure mode if H4 produces tight rev_max + H2 authors
  steep anchors.
- **Anderson & Blake:** not yet re-run post-K10. Operating
  mode, low turnaround risk; less likely to surface.

---

## §5 What this regression does NOT indicate

- **NOT a Mirror Flavor 1 violation.** V-4 would still pass on
  today's workbook (the model_input → FINMO trajectory is
  internally consistent; the violation is against the
  stage_ramp_contract, a separate contract). The K9 / F6
  invariants are intact.
- **NOT a K1 F1-F7 regression.** Payroll authority is preserved;
  exhaustion handler still excludes Payroll.
- **NOT a Tool 3 (Handler C propose) validator-chain bug.**
  Handler C's contract validates clean against Layers
  A.1 + A.2 + A.3.
- **NOT specifically caused by K10's prompt addition.** The
  H2↔H4 gap exists independent of K10. K10's class-shift may
  have made the failure more likely on Sunny by enlarging the
  capacity envelope.

---

## §6 What this regression DOES indicate

- The H2 GPT exhaustion handler authors revenue trajectories
  WITHOUT visibility into H4's stage_ramp_contract per-quarter
  bounds. The finalize validator catches the mismatch.
- This is a SYSTEMIC coherence gap in the post-intake handler
  architecture — H2 needs to read `stage_ramp_contract.quarter_
  ramp_grid` to know what rev_target / rev_max apply per quarter.
- GPT non-determinism in H2 means whether a draft fails this
  validator depends partly on which anchors GPT happens to
  pick.
- The pre-K9 Sunny PASSED P3.28 not because the coherence gap
  didn't exist, but because (pre-K9 Handler C's medium-class
  output yielded a slightly tighter capacity → H2 authored
  conservative anchors → revenue growth ≤ 6%) OR (planning_mode
  was different) OR (H2 GPT happened to pick conservative
  anchors).

This is one of the architectural pieces the cross-handler audit
flagged latently:
> "If the validator's constraints aren't fully visible to GPT
>  through the tool schema + error text (a C6-class issue), GPT
>  may iterate without insight."
> — docs/architecture/p3_32_cross_handler_prompt_audit.md §4

---

## §7 NO FIX PROPOSED — direction needed

Per user direction in the auto-pilot continuation message:
> Do NOT propose fix shape before investigation memo is written.
> Email user with findings, then await direction.

This memo is the deliverable.

If the user directs a fix, the fix shape candidates are
(presented in scope-ascending order — NOT a recommendation):

**a. Retry-only path.** Treat the failure as run-to-run variance.
   Re-run Sunny once more; if it passes, K10 is validated and the
   gap remains latent for another iter.
   - Risk: failure is reproducible in some fraction of runs;
     downstream sweeps may hit it again.
   - Cost: minimal — one re-run.

**b. Bound H2's revenue growth in mini_finmo.** Add a check in
   H2's mini_finmo that compares proposed anchors' implied
   per-quarter growth against the stage_ramp_contract's rev_max.
   Reject (or warn) inside the viability_checks aggregate.
   - Risk: requires routing stage_ramp_contract into H2's
     operating_context (currently absent).
   - Scope estimate: ~150-250 LOC (operating_context plumbing,
     mini_finmo check, viability_checks entry, tests).
   - Doctrine direction: tool-result-driven coherence (audit C4
     pattern).

**c. Expose stage_ramp bounds to H2's tool schema.** Add a tool
   that surfaces rev_max per quarter (analogous to K9 Tool 1 for
   payroll). H2 calls it before authoring anchors.
   - Risk: changes H2's tool surface; tests + prompt update.
   - Scope estimate: ~200-350 LOC.
   - Doctrine direction: tool-calling canonical for new GPT
     iterative loops (doctrine §10.4).

**d. Wider H4↔H2 coherence audit.** The gap may extend beyond
   rev_max — H2's anchor choices could also violate cogs_max,
   marketing_max, etc. from the stage_ramp_contract. Audit
   surfaces other coherence cracks; fix all together.
   - Risk: larger scope; possible 500+ LOC.
   - Could exceed the 800-LOC single-commit cap → design memo
     first.

**e. Defer.** Accept Sunny failure as a known limitation, ship
   the K9+K10 wins on Skyward (and CareFirst/Anderson & Blake
   if they pass), document the H2↔H4 coherence gap as the next
   architectural piece for a later iter.

The investigation is complete. Awaiting user direction.
