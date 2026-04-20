# Session Handoff 4.18.26 Post-Intake E2E

## Purpose

This file is a direct Codex-to-Codex handoff for the current `business_plann_app`
state as of `2026-04-18`.

If the chat session is lost or a new Codex instance takes over, read this file
before touching post-intake planning code or launching E2E runs.

This file is intentionally operational and specific. It explains:

- what the app is doing after intake,
- what architecture shift we just made,
- what the new system is supposed to do,
- what JSON payloads now matter,
- how live E2E is supposed to be run,
- what success/failure means for current validation.

---

## The App In Plain English

This app takes messy client/business intake, converts it into a financial model,
and then repairs that model after intake so the final plan is realistic,
viable, and commercially believable.

The post-intake system exists because client input is often broken.

Important rule:

- intake is not binding,
- realism and viability are more important than preserving intake numbers,
- the system may materially deviate from intake if that is what it takes to
  produce a viable plan.

The final output should not be "what the client originally typed."
It should be "a viable business plan derived from the client situation."

---

## What Matters Most Right Now

The main work is **post-intake convergence**, not intake collection.

The repo already has intake and quarter-grid generation working well enough to
get us to planning. The current mission is to make post-intake reliably
converge.

The user does **not** want a half-finished, multi-stage retry maze.
The user wants one practical post-intake system that:

1. sees the whole business,
2. makes business decisions with GPT,
3. uses Python deterministically where possible,
4. uses solver/numeric execution to apply changes,
5. repeats until issues are truly reduced and the plan is viable.

---

## The Architectural Shift We Just Made

### Old Problem

The old post-intake flow had fragmented solver/convergence ownership across
multiple outer concepts such as:

- realism resolution,
- cash strategy,
- stabilizer,
- guarantee.

Even when we reduced some of those loops, the system still felt like a
collection of partial solvers rather than one real convergence engine.

That created:

- too many loops,
- too many GPT calls,
- duplicated reasoning,
- slow cycles,
- unclear ownership,
- not enough real progress.

### New Direction

We shifted toward a **single convergence engine** where:

- realism,
- cash posture / cash strategy,
- planning mode,
- stabilizer logic,
- business type / business model context

all exist as inputs into **one loop**, not as separate heavyweight outer solver
passes.

### Practical Meaning

The desired loop is:

1. Python measures the current business state.
2. Python builds a compact deterministic packet.
3. GPT sees the whole business plus the repair guidance.
4. GPT chooses strategy, targets, levers, and bands.
5. Solver executes.
6. Python recalculates, scores, and persists.
7. GPT verifies and adjusts on the next cycle as needed.

That is the system we are trying to stabilize.

---

## Roles By Component

### GPT

GPT is the strategist and verifier.

GPT should own:

- business judgment,
- tradeoffs,
- realism posture,
- planning mode interpretation,
- cash posture decisions,
- target intent,
- lever selection,
- tolerance/buffer judgment,
- verification judgment.

GPT should **not** be asked to do deterministic bookkeeping that Python can do.

### Python

Python should own deterministic work.

Python should own:

- issue measurement,
- quarter scope,
- actual vs target gap calculations,
- scoring,
- grade calculations,
- packet building,
- lever scaffolding,
- min/max guidance where deterministically supportable,
- persistence,
- timing / logging / state management.

Python should constrain the field, not replace GPT's business reasoning.

### Solver

Solver should do numeric execution only.

The system has been moving toward using `numpy` arrays for the 20-quarter path
so solver execution is faster and more direct.

---

## The Key New JSON Payloads

Two new post-intake JSON columns matter now. These were introduced so we stop
reusing giant intake blobs and stop sending GPT accumulated historical garbage.

### 1. `planning_convergence_json`

This is the lightweight, current-cycle convergence snapshot.

It is meant to hold the operational convergence state in a compact way, such as:

- current cycle/stage/status,
- quality score,
- quality grade,
- quality pass flag,
- remaining hard issue count,
- cycle progress status,
- score delta,
- issue counts,
- current deterministic convergence summary,
- current accepted cycle summary.

This should be overwritten/refreshed cycle by cycle rather than becoming a
historical dump.

### 2. `repair_guidance_json`

This is the most important new GPT-facing repair packet.

It is meant to be compact and current-cycle only.
It should not accumulate prior cycle payloads.

Core contents include:

- `scope_quarters`
- `metric_pressure_packets`
- `lever_band_scaffold`

#### `metric_pressure_packets`

These tell GPT:

- which metric is under pressure,
- which quarter(s) are failing,
- current value,
- direction of needed change,
- severity,
- minimum change estimate,
- equilibrium target,
- suggested floor target,
- suggested ceiling target.

#### `lever_band_scaffold`

These tell GPT:

- which levers are available,
- quarter timing,
- baseline window,
- suggested minimum value,
- suggested maximum value,
- usage hints,
- and now should also include ranking / priority cues where useful.

This packet exists so GPT does not have to guess blindly after the first cycle.

---

## Current Convergence Philosophy

We have been moving away from "exact perfection or fail" and toward
quarter-aware viability plus forecast quality scoring.

### Hard Floors Still Matter

The plan cannot pass if it fails on catastrophic conditions such as:

- broken accounting tie,
- severe ongoing-concern failure,
- unacceptable liquidity collapse,
- materially impossible business shape.

### Quality Score / Grade Also Matters

The current intended direction is:

- score the plan quarter by quarter,
- allow some tolerance,
- avoid requiring fake perfect exactness,
- close issues when they are materially resolved, not merely mathematically
  perfect.

The user explicitly wants a forecast-quality mindset, not a perfectionist
controller that loops forever.

The important nuance is:

- quarter-aware scoring matters,
- one bad quarter cannot be hidden by 19 good quarters,
- issue closure should respect quarter-level reality.

---

## How The New System Is Supposed To Perform

### Intended Runtime Behavior

From cycle 1, GPT should see the whole problem:

- business type,
- business model,
- planning mode,
- cash posture,
- realism context,
- business trajectory,
- open issues,
- current financial shape,
- repair guidance packet.

Then GPT should produce a structured plan, not vague text.

The intended contract is roughly:

- strategy class / rationale,
- primary targets,
- lever selection,
- lever bands,
- tolerance guidance,
- quarter-aware repair intent.

### Targeting Philosophy

The user does **not** want over-specified targets on every line.
The user wants:

- primary targets on key lines,
- realism preserved,
- cash strategy important,
- planning mode important,
- tolerance/buffer respected,
- intake subordinated to realism when needed.

### Numeric Guidance Philosophy

One of the major upgrades is using Python to compute measured pressure after a
cycle so GPT is no longer guessing.

The current intended design is:

1. GPT makes the first strategic attempt.
2. Python/solver/finmo show what is still failing.
3. Python computes directional and band guidance.
4. GPT uses that measured guidance on the next cycle.

This should reduce randomness and shorten convergence time.

---

## What We Are Running E2E For

The goal of the live E2E work is **not** merely to make the app run.
The goal is to prove the post-intake system actually converges.

### Current E2E Mission

We are trying to prove:

1. the upgraded post-intake system runs end to end,
2. SQL updates truthfully during runtime,
3. the repair packets are being used,
4. cycle time is reasonable,
5. issue counts actually move,
6. the business becomes more viable rather than just different.

### Required Validation Standard

The user wants:

- two complete successful live E2E runs,
- on two different large/sophisticated business types,
- with viable outputs,
- and with persistence behaving correctly.

### Important Operational Rule

If a run goes **two planning cycles with zero issue resolution**, stop treating
that as acceptable drift and inspect the system.

The user explicitly wanted that as a practical stop-and-check rule because
hours of non-moving cycles are unacceptable.

---

## Live E2E Setup: Do Not Start Flask

This matters a lot.

The user already runs the backend locally on `5050`.
Do **not** waste time trying to start or restart Flask if the user says it is
already running.

Assume:

- backend already running on `http://127.0.0.1:5050`
- user wants Codex to use that backend directly
- starting Flask from scratch was too slow and too disruptive in prior runs

### Rule

If the user says backend is already running on `5050`, use it.
Do not re-bootstrap the API unless there is an actual backend failure.

---

## Preferred E2E Entry Points

### A. Persisted post-intake run (preferred when bypassing intake)

This is the preferred route when we want to bypass intake and start from an
existing persisted draft/client setup:

```powershell
python "Test Files\run_persisted_system_run.py" --client-id <client_id> --base-url http://127.0.0.1:5050
```

This runner is important because it can load an existing persisted
`intake_consult_drafts` row and start the system run without redoing intake.

Important behavior:

- it should create/use a fresh run/draft path for visibility,
- it should let us observe a new SQL line / new runtime path,
- it should be the main route for post-intake E2E while the convergence system
  is being stabilized.

### B. Full intake-based live run (secondary)

If we do need to exercise the full intake path, the runner is:

```powershell
python "Test Files\run_dual_agent_intake.py" "Create a large shipping business similar to UPS" --base-url http://127.0.0.1:5050
```

But the current preferred approach for post-intake debugging is usually the
persisted system run because it is faster and bypasses intake noise.

---

## What Specifically To Watch During E2E

When monitoring a live run, pay close attention to:

- whether cycles are actually starting,
- whether SQL is updating,
- whether `planning_convergence_json` is refreshing,
- whether `repair_guidance_json` is refreshing,
- whether issue counts move,
- whether cycle times are staying reasonable,
- whether escalation / progress status is real or cosmetic.

The user watches SQL through Excel/data-model tooling and expects runtime state
to be truthful there.

If the app is progressing but SQL is stale, that is still a serious problem.

---

## Known Friction Points

### 1. Cycle Time

This has been one of the biggest pain points.

A major prior problem was that GPT payloads had become too bloated because too
much historical or large-row content was being sent repeatedly.

That is why the dedicated compact JSONs matter so much now.

### 2. False Or Weak Escalation

There has been frustration that escalation existed in name but did not create
real movement.

The user wants escalation/progress enforcement to be meaningful, not cosmetic.

### 3. No-Progress Loops

If the system goes multiple cycles without actually reducing issues, the system
is not "thinking harder." It is wasting time and money.

### 4. Python/GPT Power Struggle

The user strongly prefers:

- GPT as judge/strategist,
- Python as deterministic support,
- not Python over-governing business judgment.

That means Python should not choke the loop just because it dislikes a proposal
style. Python should help structure the field and measure outcomes.

---

## Exact Files To Inspect First In A New Session

If resuming this work, inspect these files first:

- `context/system_overview_update_4.18.26.md`
- `context/session_handoff_4.18.26_post_intake_e2e.md`
- `python/api_handlers/intake_consult.py`
- `python/client_intake_and_finmo/intake_consult_draft.py`
- `Test Files/run_persisted_system_run.py`
- `Test Files/run_dual_agent_intake.py`
- `scripts/run_live_e2e_monitor.py`
- `scripts/validate_numeric_cutover.py`

Search terms that matter:

- `planning_convergence_json`
- `repair_guidance_json`
- `_run_planning_system_for_draft_unified`
- `metric_pressure_packets`
- `lever_band_scaffold`
- `planning_quality_score`
- `planning_quality_grade`
- `planning_cycle_progress_status`

---

## What "Good" Looks Like In The Next Session

The next Codex session should aim to do this:

1. use the backend already running on `5050`,
2. run the persisted post-intake E2E path,
3. confirm the compact repair/convergence packets are refreshing correctly,
4. confirm cycle time stays materially better than the old bloated path,
5. confirm issue counts actually move,
6. stop and inspect if two cycles produce zero issue resolution,
7. continue iterating until the system is producing reliable convergence.

The target outcome is not "the run executed."
The target outcome is "the post-intake convergence system actually works and
can be trusted."

---

## Final Reminder To Future Codex

Do not drift back into the old habit of treating post-intake as a collection of
independent outer-stage solver loops.

The user wants:

- one real convergence engine,
- compact GPT packets,
- truthful SQL,
- realism over intake,
- GPT making the business decisions,
- Python doing the deterministic support work,
- faster cycles,
- fewer wasted retries,
- real convergence.

If you need to choose between "preserving legacy complexity" and "keeping the
one-loop system clear and practical," choose the clear one-loop system.
