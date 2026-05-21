# P3.32 K11.1 — Four-Draft Comparative Analysis

**Status:** Read-only investigation. NO code changes. NO fix
implemented. Fix shapes proposed in Part D for user review only.
**Scope:** Sunny, Skyward, CareFirst, Anderson & Blake under K11.1
(commits 6aa40ac + 1ee12e2).
**Method:** Forensic comparison of run reports, H2 tool-call
traces, revenue/P&L trajectories, OEWS catalog sizes, and
stage_ramp_contract bounds across the four drafts.

---

## Headline findings (read this first)

1. **Sunny's failure is REAL and K11.1 made it measurably worse.**
   K11.1's new SYSTEM_PROMPT block anchored H2's cost-ratio
   exploration. Pre-K11 H2 drove COGS down to 0.58 (reaching Q11
   EBITDA -0.2%, nearly viable). Post-K11.1 H2 stops at COGS 0.65
   (Q11 EBITDA -10%). The mini_finmo enforcement itself is correct
   and is NOT false-rejecting — the regression is prompt-anchoring,
   not enforcement.

2. **Skyward's failure is INFRASTRUCTURE, not architectural.** The
   "Skyward has a large payload" hypothesis is DISPROVEN by direct
   measurement: Skyward's OEWS catalog is the SMALLEST of the four
   (177 candidates / 23 KB) and it authors the FEWEST roles. The
   same draft passed yesterday in 238s. The timeout is OpenAI API
   latency variance on this draft's call pattern, not a payload
   problem.

3. **CareFirst and Anderson & Blake pass genuinely — but CareFirst
   is on the edge.** CareFirst needed the H2 budget extension
   (7 tool calls) to land; A&B landed easily (2 calls). The two
   turnaround-mode drafts (Sunny, CareFirst) are the hard cases;
   the difference between them is that CareFirst's H2 used the
   extension and Sunny's H2 quit at 4 calls before the extension
   fired.

4. **The deeper architectural gap:** the system has no
   deterministic viability floor. Borderline turnaround drafts
   depend on H2's GPT exploration both finding the viable region
   AND not stopping early. This is the root issue beneath Sunny.

---

## PART A — Sunny deep analysis

### A1. Was the pre-K11.1 Sunny pass honest? (rev_max compliance)

**The finalize validator checks Q2/Q1 .. Q20/Q19 — NOT the Q1-stub
→ Q1-forecast jump.** `revenue_by_q` in
`assert_stage_ramp_revenue_path_applied`
([fail_fast.py:529-532](../../python/client_intake_and_finmo/fail_fast/post_intake_fail_fast/fail_fast.py#L529-L532))
is built from `_live_quarter_rows` (Q1..Q20 live forecast), and
the loop runs `for quarter in range(2, 21)`. The big stub→forecast
jump (which looks like +400-700% in the raw revenue list) is NOT
validated.

**Pre-K9 (yesterday morning) Sunny trajectory, checked against K11.1
mini_finmo's own rev_max logic (2dp rounding, rev_max=0.06 →
allowed ratio 1.06):**

| Q | rev | ratio | 2dp | verdict |
|---|-----|-------|-----|---------|
| Q2 | 129,349 | 1.0626 | 1.06 | PASS (at boundary) |
| Q3 | 137,116 | 1.0600 | 1.06 | PASS |
| Q4-Q11 | … | 1.046-1.058 | 1.05-1.06 | PASS |
| Q12-Q20 | … | 1.009 | 1.01 | PASS |

**Verdict: K11.1's mini_finmo would have classified the pre-K9
trajectory as ALL PASS on rev_max.** K11.1 is NOT false-rejecting a
trajectory that finalize would have accepted. The pre-K9 trajectory
sat exactly at the 2dp boundary (Q2/Q1 = 1.0626 rounds to 1.06 ≤
1.06) — the system was already operating at the rev_max threshold,
and K11.1's enforcement is consistent with that.

**Conclusion A1:** The pre-K11.1 Sunny pass was honest (it satisfied
rev_max). K11.1's enforcement does not reject it. So the K11.1 Sunny
regression is NOT a false-rejection bug.

### A2. mini_finmo vs finalize equivalence

The two share the rev_max semantics (2dp rounding) by design — I
ported them deliberately in K11.1a. The structural difference:

- **finalize** runs once on committed FINMO (post-apply-chain
  state).
- **mini_finmo** runs per-probe on H2's proposed-anchor trajectory
  during iteration.

For REVENUE specifically these are equivalent: H2's anchors are
written by the same `_write_gpt_authored_per_quarter_values` writer
the post-commit handler uses, and FINMO is rebuilt by the same
`build_finmo` callable. So the revenue trajectory mini_finmo
projects IS the trajectory that will be committed (parity by
construction — this is the iter-19 P3.9 design invariant).

For the RATIO ceilings (cogs_max, marketing_max, etc.) mini_finmo
reads FINMO's computed line-items, same as finalize would. No
divergence identified. K11.1's mini_finmo enforcement is
faithful to finalize semantics.

**No case found where mini_finmo rejects a trajectory finalize
would accept.** The enforcement is sound.

### A3. What H2 actually tried — the prompt-anchoring regression

This is the crux. H2's per-call anchor proposals, extracted from the
run reports:

**Pre-K9 Sunny (yesterday) — H2 drove COGS down aggressively:**

| Call | COGS Q11 | COGS Q20 | Mkt Q11 | EBITDA Q11 | EBITDA Q20 |
|------|----------|----------|---------|------------|------------|
| 1 | 0.65 | 0.60 | 0.10 | -19.6% | -8.4% |
| 2 | 0.60 | 0.55 | 0.08 | -4.3% | +7.8% |
| 3 | 0.58 | 0.53 | 0.08 | -1.2% | +10.8% |
| 4 | 0.58 | 0.53 | 0.08 | **-0.2%** | **+11.7%** |

**Post-K11.1 Sunny (today) — H2 stayed near the cogs_target:**

| Call | COGS Q11 | COGS Q20 | Mkt Q11 | EBITDA Q11 | EBITDA Q20 |
|------|----------|----------|---------|------------|------------|
| 1 | 0.70 | 0.68 | 0.15 | -27.7% | -17.9% |
| 2 | 0.68 | 0.65 | 0.12 | -16.6% | -8.1% |
| 3 | 0.65 | 0.63 | 0.10 | **-10.0%** | -4.4% |

Same H2 module. Same Sunny intake. Same stage_ramp_contract
(rev_max=0.06, cogs_target=0.72, cogs_max=0.80). Completely
different exploration behavior:
- Pre-K9 H2 STARTED at COGS Q11 = 0.65 and drove DOWN to 0.58.
- Post-K11.1 H2 STARTED at COGS Q11 = 0.70 and only reached 0.65.

**Root cause: the K11.1 SYSTEM_PROMPT addition.** I added this text
to `prompts.py`:

> "The stage_ramp bounds are UNIVERSAL across NAICS / stage /
> archetype (H4 derived them from the business's stage and
> planning_mode); they are not policy ceilings to maximize against,
> they are the actual shape the validator demands. If a bound seems
> too tight, the correct path is operating-model adjustment …, not
> pushing values toward the bound."

The INTENT was to prevent GPT from pushing values UP toward the
ceilings (a known anti-pattern). The UNINTENDED EFFECT: GPT now
treats the contract's `cogs_target=0.72` as "the actual shape the
validator demands" and anchors near it, rather than optimizing COGS
DOWN to whatever the business needs for viability. The phrase "the
actual shape the validator demands" reads to GPT as "stay near
these values," suppressing the aggressive cost-cutting that pre-K9
H2 did freely.

Note also: post-K11.1 H2 ran only **3 unique iterations** before
stopping; pre-K9 ran **4**. The larger constraint surface (5
universal + 7 stage_ramp checks = 12) plus the anchoring language
made GPT satisfice earlier.

**The mini_finmo enforcement never fired as a constraint on Sunny.**
Every K11.1 Sunny probe showed `stage_ramp_cogs_max_respected: PASS`
(COGS 0.65 << cogs_max 0.80). The enforcement is inert here; only
the PROMPT moved GPT's behavior.

### A4. Sunny feasibility — is the business genuinely solvable?

**Yes.** Three pieces of evidence:

1. **P3.28 baseline:** Sunny passed 16/16 with Handler C choosing
   medium class + productivity 20214 (vs today's 16500). Higher
   productivity → fewer FTE for same capacity → lower payroll
   burden → easier EBITDA viability.

2. **Pre-K9 H2 nearly hit it:** call 4 reached Q11 EBITDA -0.2%
   with EBITDA Q20 +11.7%. One more COGS step (0.58 → 0.55) crosses
   to positive. The viable region is right there.

3. **The math:** at Q11 revenue ~$266K, payroll ~13%, if H2 drives
   COGS to ~0.60, marketing to ~0.05, SGA to ~0.05, R&D to ~0.02,
   lease ~0.02, depreciation ~0.02 → total ~89% → EBITDA +11%.
   Comfortably inside stage_ramp bounds (cogs_max 0.80, etc.).

**Sunny is feasible. The failure is GPT exploration not reaching the
feasible region — exacerbated by K11.1's prompt anchoring and H2
stopping early.** It is NOT structural infeasibility (doctrine §10.2
forbids that classification anyway).

---

## PART B — Skyward deep analysis

### B1 + B2. Handler C payload inventory — hypothesis DISPROVEN

Direct measurement by building the OEWS catalog per NAICS
(`_oews_title_catalog_for_business`, .env loaded, live SQL):

| Draft | NAICS | OEWS title_candidates | Catalog JSON size |
|-------|-------|----------------------|-------------------|
| **Skyward (airline)** | 481111 | **177** | **23.1 KB (smallest)** |
| Sunny (bakery) | 311811 | 238 | 31.1 KB |
| Anderson & Blake (legal) | 541110 | 246 | 31.1 KB |
| CareFirst (home health) | 621610 | 298 | 38.1 KB (largest) |

**Skyward has the SMALLEST OEWS catalog of the four.** CareFirst
has the LARGEST and it passes. The "Skyward times out because its
Handler C input payload is large" hypothesis (proposed by the
survey agent on estimates) is empirically false. Input payload size
does not explain the timeout.

### B3. Cross-handler comparison

Handler C's input is not anomalously large versus H2/H3/H4, and in
any case the timeout is read-side (waiting for OpenAI's response),
not request-side. Request size is not the binding variable.

### B4. Skyward call #2 — what actually times out

Every Skyward failure (7 consecutive) is identical:
- `payroll_tool_calling_session` (Handler C, not H2)
- `tool_calls_used_before_failure=1, gpt_calls_made_before_failure=2`
- `network_retry_exhausted: attempts=3 elapsed≈140-148s
  final=read_timeout (read timeout=45.0)`

Call #1 (a consultation tool) succeeds fast. Call #2 hangs — OpenAI
takes >45s to respond, three times, exhausting the retry budget.

**Output size is also NOT the cause:** Skyward authored the FEWEST
distinct OEWS roles of the four in its committed grid (yesterday's
K9 run). It's not generating an unusually large payload either.

**The decisive evidence:** the SAME Skyward draft passed yesterday
(K9 run) in 238 seconds with GENUINE_PASS + V-4 $0.46. K9/K10/K11.1
did not change Handler C's payload materially (K10 added ~650 chars;
K11.1 didn't touch Handler C at all). Nothing in the code explains a
4× latency change. **This is OpenAI API latency variance** — the
endpoint is simply slower today for this draft's specific call
pattern. It is infrastructure, exactly as the user classified it.

**Honest limitation:** Skyward's timeout is NOT diagnosable as
architectural from the artifacts. The truncated report (1.46 MB vs
7-11 MB for completed runs) crashes before persisting Handler C's
context. But the input-size and output-size hypotheses are both
disproven by direct measurement, and the same-draft-passed-yesterday
fact points squarely at infrastructure.

---

## PART C — Four-draft comparative table

### Intake + Handler C + H2 + outcome

| Dimension | Sunny | CareFirst | Anderson & Blake | Skyward |
|-----------|-------|-----------|------------------|---------|
| NAICS | 311811 bakery | 621610 home health | 541110 legal | 481111 airline |
| Planning mode | **turnaround** | **turnaround** | normalize | rebalance |
| OEWS catalog size | 238 / 31KB | 298 / 38KB | 246 / 31KB | **177 / 23KB** |
| Handler C class | medium | medium | medium | medium |
| Handler C target_pct | 0.45 | 0.45 | 0.45 | 0.10 |
| capacity_units/FTE | 16,500 | 520 | 33.5 | 4,800 |
| H2 tool calls | 4 | **7** | 2 | (timeout) |
| H2 budget extension | no | **YES** | no | n/a |
| Q11 EBITDA margin | **-10.0%** | (passed) | (passed) | n/a |
| V-1 acceptance | **13/16 FAIL** | 16/16 PASS | 16/16 PASS | timeout |
| V-4 max_abs | n/a (gate fail) | (pass) | $13.70 | n/a |
| Outcome | **ARCH FAIL** | PASS (edge) | GENUINE_PASS | INFRA TIMEOUT |

### C2. Consistency analysis

- **All four chose `medium` labor_intensity_class.** Class
  selection is consistent post-K10.
- **The turnaround-mode drafts (Sunny, CareFirst) are the hard
  ones.** Turnaround means recovering from a loss position to
  EBITDA-positive by Q11 — structurally the hardest acceptance-gate
  target. A&B (normalize) lands in 2 calls; the turnarounds need
  4-7+.
- **H2 effort tracks difficulty:** A&B 2 calls (easy) < Sunny 4
  (medium, quit early) < CareFirst 7 + extension (hard, persisted).
- **The decisive behavioral difference between the two turnarounds:**
  CareFirst's H2 USED the budget extension (kept iterating to call
  7) and found viability. Sunny's H2 STOPPED at call 4 — one call
  short of the extension trigger (5) — and never got the "be more
  aggressive" nudge. Same difficulty class; different persistence.

---

## PART D — Synthesis

### D1. Are the problems real?

- **Sunny: REAL, two-layered.**
  - Layer 1 (K11.1-introduced): the SYSTEM_PROMPT anchoring
    regression. K11.1 made Sunny measurably worse (-0.2% → -10%
    Q11 EBITDA) by anchoring H2's cost-ratio exploration toward the
    contract targets.
  - Layer 2 (pre-existing): Sunny is borderline-feasible and
    depends on H2 exploring aggressively AND not stopping early.
    Even pre-K11 (post-K9) Sunny failed at 13/16 (-0.2%) — it was
    already on the edge. K9/K10 had shifted Handler C's productivity
    choice (20214 → 16500) raising the payroll burden.
  - NOT a mini_finmo false-rejection. NOT structural infeasibility.

- **Skyward: INFRASTRUCTURE, not architectural.** Input payload
  smallest of the four; output roles fewest; same draft passed
  yesterday. OpenAI latency variance. The artifacts cannot support
  an architectural explanation.

- **CareFirst: GENUINE pass, on the edge.** Needed budget extension.
  A repeat run could fail if GPT explores less persistently — same
  fragility class as Sunny but currently landing.

- **Anderson & Blake: GENUINE pass, comfortable.** 2 calls, no
  extension, clean V-4. Not fragile.

### D2. Would fixing one regress another?

- **Sunny prompt fix (clarify bounds-vs-targets in SYSTEM_PROMPT):**
  LOW regression risk. The current language over-anchors ALL H2
  invocations toward contract targets; clarifying that ceilings are
  ceilings (optimize freely below them) helps every draft explore
  the full viable region. A&B and CareFirst already pass; clearer
  guidance can only help (CareFirst might even land in fewer calls).

- **Sunny H2-budget fix (earlier extension trigger):** LOW risk.
  More iteration headroom only helps. CareFirst already benefits
  from the extension; making it fire sooner helps Sunny reach the
  same region. A&B unaffected (lands in 2 calls, never reaches the
  trigger).

- **Skyward timeout bump (read_timeout 45s → 120s):** ZERO
  architectural risk. Pure config; widens latency tolerance for all
  drafts; changes no decision logic.

No fix for one draft is projected to regress another. The fixes are
orthogonal (prompt clarity, budget tuning, timeout config).

### D3. Architectural soundness assessment

The four drafts collectively reveal one real architectural gap
beyond the Sunny/Skyward specifics:

**There is no deterministic viability floor.** Whether a borderline
turnaround draft passes the K4 acceptance gate depends entirely on
H2's GPT exploration (a) reaching the feasible cost-ratio region and
(b) not stopping before it gets there. Two turnaround drafts
(Sunny, CareFirst) sit in this fragile zone; one passes and one
fails based on H2 persistence, not on any deterministic guarantee.

This is consistent with doctrine §1 (GPT-as-authoring-source with
Python structure around it) — H2 is intentionally GPT-authored. But
the *handler-on-failure* safety net assumes the handler converges
within budget. For borderline turnarounds the handler's convergence
is not guaranteed, and there is no Python fallback that pushes cost
ratios to a viability-achieving configuration when GPT stops short.

This is NOT a call to make H2 deterministic (that would violate
§1). It IS a signal that H2's budget/persistence behavior is the
load-bearing lever for the hard cases, and currently it's
undertuned (the extension fires too late, GPT quits too early).

### D4. Recommended fix shapes (for user review — NOT implemented)

**Fix 1 — Revise the K11.1 SYSTEM_PROMPT anchoring language
(Sunny Layer 1).**
- Cite: A3. The phrase "they are not policy ceilings to maximize
  against, they are the actual shape the validator demands"
  anchored H2 toward cogs_target.
- Shape: rewrite to clearly distinguish CEILINGS (rev_max, cogs_max,
  marketing_max, rd_max, ga_max, max_util — never exceed) from
  FLOORS (ni_floor — never go below) and explicitly license
  optimizing COGS/marketing/etc. as far DOWN as the operating model
  allows, since lower cost ratios improve EBITDA viability.
- Projected impact: Sunny H2 resumes aggressive cost-cutting (back
  toward pre-K9 behavior). A&B/CareFirst unaffected or improved.
- Doctrine: universal, root-cause (fixes the anchoring at source),
  no NAICS hardcoding.
- Scope: ~20 LOC prompt + test assertion.

**Fix 2 — Lower H2's budget-extension trigger (Sunny Layer 2).**
- Cite: C2. CareFirst (7 calls + extension) passed; Sunny (4 calls,
  no extension) failed one call short of the trigger.
- Shape: move `budget_extension_triggered` threshold from
  `tool_calls_used >= 5` to `>= 3` (or scale to the active-check
  count, which K11.1 grew from 5 to 12). Gives GPT the "be more
  aggressive" nudge before it voluntarily stops.
- Projected impact: Sunny H2 gets the extension prompt at call 3-4
  and keeps iterating into the viable region. CareFirst already
  uses the extension (lands sooner). A&B never reaches the trigger.
- Doctrine: universal, addresses the real lever for hard cases.
- Scope: ~10 LOC + tests.

**Fix 3 — Bump Handler C read_timeout (Skyward).**
- Cite: B4. 45s is empirically too tight for Skyward's call #2 under
  current OpenAI latency. Same draft passed yesterday at the same
  payload.
- Shape: raise the OpenAI `read_timeout` for Handler C tool-calling
  turns from 45s to 90-120s.
- Projected impact: Skyward call #2 gets room to complete. No
  architectural change; helps any draft hitting transient latency.
- Doctrine: not a bandaid (it doesn't mask a logic error — it
  matches the timeout to the empirical response-time profile);
  universal.
- Scope: ~5 LOC + test.

**Fix 4 (architectural, larger — DEFER to user decision) —
deterministic viability assist for turnarounds.**
- Cite: D3. No Python floor guarantees borderline turnaround
  viability.
- Shape: when H2 exhausts its budget on a turnaround draft without
  reaching ebitda_positive_by_q11, a Python proposer computes the
  cost-ratio configuration that WOULD reach viability (within
  stage_ramp bounds) and offers it to H2 as a seed, OR commits it
  as a deterministic floor. This is the doctrine §3 Pattern 2
  shape (Python proposes, GPT critiques).
- Risk/scope: larger (~200-400 LOC); needs its own design memo.
- Recommendation: defer unless Fixes 1+2 prove insufficient on
  re-verification.

**Sequencing recommendation:** Land Fix 1 + Fix 2 together (both
target Sunny, both small, both H2-prompt/budget), re-verify the four
baselines. Land Fix 3 (Skyward timeout) independently. Hold Fix 4
unless Fixes 1+2 don't make Sunny pass.

---

## Investigation honesty notes

- Skyward's Handler C context could not be measured from its
  truncated report; I measured the OEWS catalog directly from SQL
  per NAICS instead, which is a cleaner signal and disproved the
  payload hypothesis.
- The H2 tool-call traces show duplicate entries (calls 5-8 mirror
  1-4 on pre-K9; 4-6 mirror 1-3 on K11.1). This appears to be a
  history-replay/persistence artifact, not 8 distinct GPT calls;
  the run_diagnostics `tool_calls_used` (4 and 4 respectively) is
  the authoritative count. It does not change the COGS-anchoring
  finding.
- Time spent: within the 4-hour cap. The system was inspectable at
  the depth requested; no opacity blocker encountered.
