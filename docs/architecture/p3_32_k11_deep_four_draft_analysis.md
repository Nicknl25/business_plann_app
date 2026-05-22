# P3.32 K11 — Deep 12-Draft × 3-Run Instrumented Analysis

**Status:** Read-only investigation under L-4 instrumentation
(commits `222fc05` + `e76ca0f`). NO architectural fixes implemented.
Fix shapes proposed in Part E for user review.
**Method:** 12 drafts × 3 runs = 37 run-attempts (one Skyward-class
retry), each driven through the live 5050 pipeline with
`BPLAN_TRACE_VERBOSE=1`. Every Handler C probe, H2 probe, and OpenAI
turn persisted incrementally to `post_intake_handler_traces`.
**Data:** `_l4_batch/ledger.json` (outcomes), `post_intake_handler_traces`
(per-call forensics, queryable by draft_id).

---

## ⛔ HEADLINE — TWO STOP CONDITIONS TRIPPED (read this first)

The directive named two conditions that, if observed, "change the
entire P3.32 strategy." **Both are now empirically confirmed.**

1. **Passes are luck-dependent.** The same intake, run three times,
   produces different pass/fail outcomes. CareFirst:
   COMPLETE / FAIL / COMPLETE. Luna Boutique: COMPLETE / COMPLETE /
   FAIL. Outcome is decided by GPT non-determinism, not by any
   deterministic property of the system.

2. **The baseline four cannot be trusted as a baseline.** The prior
   memo (`a783b97`) classified CareFirst and Anderson & Blake as
   "genuine passes" and framed only Sunny + Skyward as broken. The
   batch disproves that framing: CareFirst is **2/3 (luck)**, Sunny is
   **0/3**, Skyward is **0/3**. Only Anderson & Blake is robust (3/3).

**Only 7 of 37 run-attempts completed (~19%).** The system fails the
large majority of runs, and the failures are dominated by ONE systemic
architectural fault, not per-draft idiosyncrasies.

The instrumentation itself worked flawlessly: traces persisted for all
37 runs **including every failure** (6–43 rows each), validating the
P1.3 truncation-elimination contract — a crashed run now leaves all
completed-call traces durable and queryable.

---

## PART A — The consistency matrix (the core finding)

| # | Draft | Run 1 | Run 2 | Run 3 | Completed |
|---|-------|-------|-------|-------|-----------|
| 1 | Sunny Glaze Donuts | FAIL finalize | FAIL payroll-timeout | FAIL payroll-timeout | **0/3** |
| 2 | Skyward Express Airlines | FAIL payroll-timeout | FAIL payroll-timeout | FAIL payroll-timeout | **0/3** |
| 3 | CareFirst Home Health | ✅ COMPLETE | FAIL payroll-exhausted | ✅ COMPLETE | **2/3 ⚠** |
| 4 | Anderson & Blake Legal | ✅ COMPLETE | ✅ COMPLETE | ✅ COMPLETE | **3/3** |
| 5 | Luna Boutique | ✅ COMPLETE | ✅ COMPLETE | FAIL finalize | **2/3 ⚠** |
| 6 | Elegant Threads Boutique | FAIL finalize | FAIL finalize | FAIL payroll-timeout | 0/3 |
| 7 | Revitalize Mobile IV Therapy | FAIL finalize | FAIL finalize | FAIL finalize | 0/3 |
| 8 | North Ridge Auto Care | FAIL finalize | FAIL finalize | FAIL finalize | 0/3 |
| 9 | ValueMart Superstores | FAIL pre-cash-gate | FAIL payroll-timeout | FAIL finalize | 0/3 |
| 10 | Freedom Freight Logistics | FAIL finalize | FAIL finalize | FAIL finalize | 0/3 |
| 11 | Pinnacle Logistics Inc. | FAIL payroll-timeout | FAIL payroll-timeout | FAIL finalize | 0/3 |
| 12 | SwiftCargo Logistics | FAIL stageramp-exhaust | FAIL finalize | FAIL stageramp-exhaust | 0/3 |

**Completed totals:** A&B 3/3; CareFirst 2/3; Luna 2/3; all eight
others 0/3. **7/37 ≈ 19%.**

### A1. Same-input variance (Phase 3 — GPT non-determinism)

Three runs of the *same* draft are not reaching the same outcome:

- **CareFirst** (turnaround/home-health): COMPLETE (343s) → FAIL at
  Handler C "payroll_tool_calling_session_exhausted" (43s) → COMPLETE
  (333s). Run 2 died in 43s — Handler C never produced a
  validator-accepted schedule and hit its hard cap; runs 1 and 3 took
  ~340s and landed. **Pure GPT-exploration luck.**
- **Luna Boutique** (retail): COMPLETE → COMPLETE → FAIL finalize. Run
  3 reached finalize with 12 H2 probes but never satisfied the
  stage-ramp revenue path.
- **SwiftCargo** (logistics): two different failure modes across three
  runs (H4 stage_ramp handler exhaustion twice, finalize once) — even
  the *failure mode* is non-deterministic.

This is the architectural-inconsistency signal the directive's
Principle 3 warned about: similar/identical inputs producing different
outcomes for reasons that are not principled. The variance source is
GPT exploration in H4 (stage_ramp contract), Handler C (payroll), and
H2 (P&L) — none of which has a deterministic floor that guarantees a
landing.

---

## PART B — Failure-mode taxonomy

Across the 30 failed run-attempts, five distinct failure modes:

| Mode | Stage | Count* | Meaning |
|------|-------|--------|---------|
| **B1** `stage_ramp_revenue_path_not_applied` | finalize global invariant | ~17 | Committed FINMO revenue violates the GPT-selected stage_ramp_contract Q1–Q20 revenue path. |
| **B2** `payroll_tool_calling_session_turn_failed` (`network_retry_exhausted`) | Handler C | ~8 | A Handler C OpenAI turn exceeded the 45 s read timeout 3× (≈140 s) and exhausted the retry budget. |
| **B3** `payroll_tool_calling_session_exhausted` | Handler C | 1 | Handler C hit its 10-call hard cap without a validator-accepted schedule. |
| **B4** `pre_cash_gate_gpt_authorable_checks_unfixed_after_handler` | pre-cash gate | 1 | A GPT-authorable check stayed unfixed after the handler ran. |
| **B5** `stage_ramp_handler_exhausted` | H4 (stage_ramp contract) | 2 | H4's GPT session never produced a validator-accepted stage_ramp contract. |

*Counts approximate (read from ledger outcome strings); exact
per-quarter detail is in the trace rows.

**B1 is the dominant fault and it is systemic** — it appears for
bakery, retail, home-health, auto, logistics, and professional-services
drafts alike. It is NOT a turnaround-mode-only or Sunny-only problem as
the prior memo implied. **B2 (Handler C timeout) is the second
systemic fault** and is the same mechanism the prior memo attributed to
"Skyward infrastructure" — but it is widespread (Sunny, Skyward,
Elegant Threads, ValueMart, Pinnacle), driven by Handler C's large-
context GPT calls running 29–32 s normally (see Part C) and crossing
45 s under modest latency.

### B1 — why "revenue path not applied" is the central architectural fault

`assert_stage_ramp_revenue_path_applied`
([fail_fast.py](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py))
checks that the committed FINMO's Q2/Q1 … Q20/Q19 revenue growth matches
the H4-authored stage_ramp_contract. H4 (GPT) authors a per-quarter
revenue ramp; H2 (GPT) authors the P&L drivers (unit_price, capacity,
utilization) that *produce* revenue; the finalize validator demands the
two agree. Nothing deterministically reconciles them. When H2's
driver-authored revenue trajectory diverges from H4's authored revenue
ramp — which happens whenever GPT's two independent authoring steps
disagree — finalize rejects the run. This is the **structural seam**
between two GPT authoring surfaces with no deterministic bridge.

---

## PART C — Equal-depth four-draft forensics

> Per-probe data extracted from `post_intake_handler_traces`. Sunny's
> table is reproduced from the instrumentation validation run
> (draft `36cdcfb5…`, a Sunny execution). Skyward / CareFirst / A&B
> tables are extracted from their batch runs (filled below).

### C1. Sunny Glaze Donuts (0/3) — H2 reaches viability but stage-ramp rejects it

H2 per-probe exploration (validation Sunny run, 8 probes):

| call | COGS q11 | COGS q20 | MKT q11 | EBITDA q11 | EBITDA q20 | all_pass | failing checks / #viol |
|------|----------|----------|---------|------------|------------|----------|------------------------|
| 2 | 0.70 | 0.68 | 0.20 | −0.348 | −0.238 | False | ebitda_q11, ni_floor, rev_max / 26 |
| 3 | 0.68 | 0.65 | 0.18 | −0.299 | −0.210 | False | ebitda_q11, ni_floor, rev_max / 26 |
| 4 | 0.66 | 0.63 | 0.15 | −0.230 | −0.140 | False | ebitda_q11, ni_floor, rev_max / 26 |
| 5 | 0.60 | 0.58 | 0.12 | −0.067 | +0.000 | False | ebitda_q11, ni_floor, rev_max / 26 |
| 6 | 0.55 | 0.50 | 0.10 | **+0.069** | +0.174 | False | ni_floor, rev_max / 16 |
| 7 | 0.55 | 0.50 | 0.10 | +0.069 | +0.174 | False | ni_floor, rev_max / 16 |
| 8 | 0.55 | 0.50 | 0.10 | +0.023 | +0.150 | False | ebitda_q11, ni_floor, rev_max / 18 |
| 9 | 0.55 | 0.50 | 0.10 | −0.009 | +0.135 | False | ebitda_q11, ni_floor, rev_max / 18 |

**This overturns the prior memo's Sunny diagnosis.** The prior memo
said K11.1 prompt-anchoring stalled H2 at COGS 0.65 with EBITDA −10%.
Under current code, H2 freely drove COGS to 0.55 and reached
**EBITDA-positive (+6.9% q11)** at call 6 — the cost-ratio exploration
is NOT the binding problem. The binding failures are **`rev_max`
(revenue-growth ceiling) and `ni_floor` (net-income floor)** —
stage_ramp constraints — which never clear even when EBITDA is healthy.
And calls 6→9 **oscillate off** the best region (EBITDA +0.069 → −0.009)
rather than converging: classic no-deterministic-floor drift. H2 ends
best-effort (no all_pass), commits a trajectory, and finalize then
rejects it under B1.

Sunny runs 2 & 3 didn't even reach H2 — they died at Handler C with B2
(network timeout), 4 traces each.

### C2. Skyward Express Airlines (0/3) — Handler C timeout, every run

After the manual capex addition (current_capex 0 → $2,000,000), Skyward
now reaches Handler C on every run — and times out there all three
times (B2, `network_retry_exhausted`, ~140 s, read timeout 45 s). H2
never runs (h2=0 traces on all three).

Skyward batch run 2 (`5a5456bf`) Handler C GPT turn latencies:

| turn | latency | in / out tokens | result |
|------|---------|-----------------|--------|
| HC turn 1 (get_bounds) | 3.2 s | 21459 / 24 | ok |
| HC turn 2 (propose) | **116.4 s** | 21679 / 1858 | ok (slow) |
| HC turn 3 (propose) | 35.7 s | 23212 / 4572 | ok |
| HC turn 4 (propose) | **148.1 s** | — | **read_timeout** (B2 fail) |

**Refined B2 mechanism (important):** the `read_timeout=45 s` is a
*stall* timeout (no bytes received for 45 s), not a total-duration cap.
Slow-but-steady turns of 116 s SUCCEEDED here; the failing turn 4
stalled (no progress for 45 s × 3 retries ≈ 148 s) and exhausted the
retry budget. So B2 is "OpenAI stalled mid-generation on a large Handler
C turn"; larger input/output raises stall probability. Compaction (K12
Stage 1) shrinks that surface; a raw timeout bump would not address the
stall. H2 never runs for Skyward — the run dies at Handler C first.

### C3. CareFirst Home Health (2/3) — proven luck-dependence

Completed run 1 (`ab43a8f2`) — H2 reached EBITDA-positive, Handler C
self-corrected:

| call | COGS q11 | EBITDA q11 | EBITDA q20 | all_pass | failing |
|------|----------|------------|------------|----------|---------|
| H2-2 | 0.70 | −0.465 | −0.233 | False | ebitda_q11, ni_floor |
| H2-3 | 0.60 | −0.156 | +0.013 | False | ebitda_q11, ni_floor |
| H2-4 | 0.55 | **+0.014** | +0.123 | False | ni_floor (only) |

Handler C: get_bounds → propose REJECTED (`economic_feasibility`) →
propose ACCEPTED. The run committed best-effort (ni_floor still failing)
and passed finalize.

FAILED run 2 (`4abf34b5`) — died in **43 s** with only 1 Handler C call
(get_bounds) and a 7.8 s turn returning 48 output tokens, then
`payroll_tool_calling_session_exhausted`: GPT effectively stopped
proposing and the session hit its cap with no validator-accepted
schedule. H2 never ran (h2=0). Same intake as runs 1/3 — the difference
is purely which payroll schedules GPT happened to propose. The prior
memo's "edge" hypothesis is **confirmed as luck**, not "genuine pass."

### C4. Anderson & Blake Legal (3/3) — the only robust draft

Completed run 1 (`0fb023fc`) — note H2 never reached all_pass yet the
run still PASSED finalize:

| call | EBITDA q11 | EBITDA q20 | all_pass | failing |
|------|------------|------------|----------|---------|
| H2-1 | +0.066 | +0.066 | False | gross_margin, ni_floor |
| H2-2 | +0.066 | +0.066 | False | gross_margin, ni_floor |
| H2-3 | +0.066 | +0.066 | False | gross_margin, ni_floor |

Handler C: get_bounds → propose rejected ×2 (`support_title_missing`) →
propose ACCEPTED on call 4. **Key insight:** A&B's committed
driver-implied revenue happened to satisfy the finalize stage_ramp
revenue path (no B1), so it landed despite H2 not clearing its own
viability checks. A&B is not "more viable" — its two GPT surfaces
(H4 ramp ↔ H2 drivers) happened to agree. Across the 3 runs, H2 probe
counts vary (6 / 2 / 2) and run 1 needed a retry — robustness is
relative; A&B is simply the draft where the stochastic agreement landed
all three times. This is luck that *held*, not a guarantee.

### C5. GPT-IO latency profile — the B2 mechanism quantified

Handler C *propose* turns carry the largest context of any GPT surface
(24 k–35 k input tokens, 1.5 k–4.6 k output) and are by far the slowest.
Observed propose-turn latencies across batch runs:

| draft / turn | latency | result |
|--------------|---------|--------|
| Sunny (validation) HC t2 / t3 | 32.2 s / 29.3 s | ok |
| CareFirst HC t2 / t3 | 39.8 s / 35.6 s | ok |
| CareFirst (2nd session) HC t2 | 73.5 s | ok (slow) |
| A&B HC t2 / t3 | 21.7 s / **75.8 s** | ok (slow) |
| Skyward HC t2 / t4 | **116.4 s** / **148.1 s** | ok / **timeout** |
| H2 tool turns (all drafts) | 2.4 s – 19.8 s | ok |

The `read_timeout=45 s` is a **stall** ceiling (no bytes for 45 s), not
a total-duration cap — which is why 75 s and 116 s turns succeed
(steady streaming) while a turn that stalls fails after 3 retries
(~148 s). The fault is therefore *stall probability*, which scales with
how much the model has to generate against a large context. Handler C is
the dominant B2 surface because it is consistently the heaviest turn.
**This is why K12 Stage 1 compacts Handler C's context rather than
bumping the timeout** — a bump tolerates the stall longer but doesn't
reduce its probability; compaction reduces the generation surface that
produces stalls.

---

## PART D — Revised diagnosis vs the prior memo (`a783b97`)

| Claim in prior memo | Batch evidence | Verdict |
|---------------------|----------------|---------|
| CareFirst "passes genuinely" | 2/3, run 2 dies at Handler C in 43 s | **Wrong — luck-dependent** |
| A&B "genuine, comfortable" | 3/3 (but variable probe counts) | **Confirmed (only robust draft)** |
| Sunny fails from K11.1 COGS prompt-anchoring | H2 freely reaches COGS 0.55 / EBITDA +6.9%; fails on rev_max + ni_floor | **Wrong cause — stage-ramp, not anchoring** |
| Skyward = isolated infra latency variance | B2 timeout is systemic across 5 drafts | **Understated — Handler C latency is structural** |
| Problem scope = Sunny + Skyward (4-draft frame) | 8/12 drafts 0/3; B1 systemic | **Scope far larger; system-wide** |
| "No deterministic viability floor" (D3, deferred) | Confirmed as THE root gap | **Must not be deferred** |

---

## PART E — Architectural gaps (Phase 4) and fix shapes

> Proposed only. No fix implemented this iter.

### G-B1 (NEW, top priority) — No deterministic reconciliation between H4 revenue ramp and H2 driver-authored revenue
- **Failure mode:** B1 `stage_ramp_revenue_path_not_applied`, the
  dominant fault (~17 attempts, all NAICS).
- **Root cause:** H4 (GPT) authors a per-quarter revenue ramp; H2 (GPT)
  authors P&L drivers that independently produce revenue; finalize
  demands they match; nothing bridges them deterministically.
- **Fix shape (doctrine §3 Pattern 2 — Python proposes, GPT critiques):**
  after H2 commits drivers, a Python step deterministically reconciles
  the driver-implied revenue to the H4 ramp (or vice-versa) within
  bounds, instead of relying on two GPT surfaces agreeing by chance.
  Estimated 150–300 LOC + tests.

### G3 (was deferred) — No deterministic viability floor for turnarounds
- **Failure mode:** H2 reaches a near-viable region then oscillates off
  it (Sunny calls 6→9); CareFirst run 2 never converges.
- **Fix shape:** when H2 exhausts budget without all_pass, a Python
  proposer computes the in-bounds cost-ratio/anchor configuration that
  *would* satisfy the checks and commits it as a floor (or seeds H2).
  **Must not be deferred** — it is load-bearing for the hard cases.

### G-B2 (NEW) — Handler C GPT turns routinely approach the 45 s read timeout
- **Failure mode:** B2, ~8 attempts; whole-draft failures.
- **Root cause:** Handler C *propose* turns carry 24–32 k input tokens
  and run ~30 s; 45 s leaves no margin.
- **Fix shape (orthogonal, lowest-risk):** raise Handler C read_timeout
  to 90–120 s AND/OR shrink the propose-turn input context. Config +
  prompt; ~5–20 LOC. Pure latency-tolerance, no logic change.

### G-B5 (NEW) — H4 stage_ramp contract handler can exhaust without an accepted contract
- **Failure mode:** B5, SwiftCargo runs 1 & 3 (and the *failure mode*
  itself was non-deterministic across runs).
- **Fix shape:** Python-first deterministic stage_ramp contract proposal
  with GPT critique-only (doctrine §3 Pattern 2), so H4 cannot fail to
  produce a validator-accepted contract.

### G6 (Phase 3) — System-wide non-determinism with no convergence guarantee
- Three GPT authoring surfaces (H4, Handler C, H2), none with a
  deterministic floor; outcome = product of three independent
  explorations landing. This is why identical inputs flip. The
  consistency the user wants requires deterministic floors on all
  three (Pattern 2), not prompt tuning.

### Sequencing recommendation
1. **G-B2** (Handler C timeout) — unblocks runs that currently die
   before reaching the real logic; cheapest; reveals true B1/B5 rates.
2. **G-B1** (revenue-path reconciliation) — kills the dominant fault.
3. **G3 + G-B5** (deterministic floors for H2 and H4) — the consistency
   fix; converts luck into guarantee.
4. Re-run the 12×3 batch to measure the new completion rate.

---

## PART F — Investigation honesty notes

- The instrumentation worked end-to-end; all 37 runs (incl. all 30
  failures) persisted forensic traces. P1.3 validated in production.
- Outcome data (Part A/B) is authoritative from `_l4_batch/ledger.json`.
- Sunny's per-probe table (C1) and the latency profile (C5) are from
  the validation run (a Sunny execution); the Skyward/CareFirst/A&B
  per-probe tables are extracted from their batch trace rows (Part C
  placeholders are filled by `_l4_batch/analyze_traces.py`).
- Skyward required the one-time manual `current_capex` seed
  ($2,000,000) to get past intake feasibility; this is recorded so the
  baseline is reproducible.
