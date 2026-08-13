# Replay gate

Catches every **known** issue in seconds, so a Cowork run only ever finds genuinely
new stuff.

```
VS ships a fix  ->  replay gate (seconds)  ->  GREEN: every known issue clear, spend the Cowork run
                                          ->  RED:   names the fixed bug that regressed
                                                     or the invariant that broke; bounce to VS
```

## Run it

From `C:\dev\business_plann_app`, with the venv interpreter:

```bat
replay_gate\gate.bat                 :: gate the build (fast tier)
replay_gate\gate.bat --tier full     :: + the live-judge legs
replay_gate\gate.bat --list          :: the leg list
replay_gate\gate.bat --prove         :: prove every leg on its own broken baseline
replay_gate\gate.bat --only R04,I09  :: one or a few legs
```

Exit codes: `0` GREEN · `1` RED · `2` SETUP FAILED (the gate is wrong, not the build).

## What's in it

**REGRESSION legs — one per fixed bug.** Each replays the scenario that broke and
asserts the fix still holds. Each carries the commit that fixed it and the commit
where it was still live.

**INVARIANT legs — one per structural rule.** Fired at the surface where the rule
applies. Same proof discipline.

`--list` prints the current registry. As of writing: 14 regression pins, 11
invariants, 3 of which need the live judge.

## The proof rule

**A leg is only trusted if it goes RED on the commit where its bug was live and
GREEN on the fix.** `--prove` checks exactly that, per leg, one leg at a time, in
clean subprocesses:

```
leg   bug                              baseline  on base   on now   proof
R01   completed-financials-freeze      5b5ffbb   RED       GREEN    PROVEN
R05   capex-zero                       7b9f481   GREEN     GREEN    QUARANTINE
      -> PASSED on its own broken baseline - fixture path
```

A leg that can't go red on its own baseline is **quarantined**: excluded from the
gate verdict and named in the report, never silently trusted. Pass the quarantine
list through to keep the gate honest while you fix the leg:

```bat
replay_gate\gate.bat --quarantine R05,R09
```

One leg at a time matters. Several of these bugs were fixed in a single "slate"
commit, so running the whole suite at a shared baseline goes red for many reasons
at once and attributes nothing. Per-leg isolation is what makes a red mean
*that* bug.

Baseline worktrees are created and cached on demand under
`C:\dev\bpa_gate_baselines\<sha>` — only `python/` is checked out (the whole
import surface; a full checkout of ~9,600 files per baseline would make proving
slow enough that nobody runs it), and `.env` is copied in because it is
gitignored and the app resolves it from `parents[2]`.

## Adding a leg when a new bug gets fixed

Append to `REGRESSIONS` in `legs.py` (or `INVARIANTS` in `invariants.py`):

```python
Leg("R15", "REGRESSION", "the-bug-slug",
    "what must stay true",
    fix_commit="abc1234",        # the commit that fixed it
    baseline="def5678",          # fix_commit^ - where it was still live
    run=_my_leg,                 # run(ctx) -> (ok, evidence)
    issue="CW-027"),
```

Then `--prove --only R15`. If it doesn't go red on `def5678`, it's on a fixture
path — fix it before trusting it. That's the whole discipline: the gate grows one
proven leg per fixed bug, permanently.

## Design commitments

- **Real production chain.** Turn-driving legs enter at
  `api_handlers.intake_consult._run_financials_turn_and_sync` — the exact function
  a live financials turn hits, doors and all. Pure-function legs call the real
  handler/controller functions. No fixture path: a fixture passes on the broken
  build, which is the failure mode this gate exists to prevent.
- **The surface assertion is mandatory.** Before any leg runs, the gate asserts
  `_next_financials_stage(fin) is None`. Entering anywhere else exits `2` rather
  than reporting a meaningless green.
- **Stored fields, never the ack.** Assertions read `operating_model_json`,
  `financials_json`, `people_json` back out of the draft. There is also an
  explicit invariant (`I07`) that the figure the app *claims* it recorded is the
  figure actually sitting in the stored field.
- **Autocommit everywhere.** MySQL REPEATABLE READ pins a snapshot at the first
  read of a transaction, so a non-autocommit connection re-reading a draft after
  the turn wrote it serves the stale pre-turn row forever — a false RED on a build
  that landed the value fine. Every connection is autocommit; readback uses a
  separate one.
- **Cheap.** Recorded router doubles stand in for the LLM call only; everything
  downstream is real. The fast tier makes no GPT calls at all.
- **No silent caps.** Legs not run (live tier) and legs quarantined are both
  printed under the verdict. A GREEN with reduced coverage says so.
- **Separate from the persona-run app.** Its own package, its own throwaway
  drafts. It cannot contaminate a naive full run.

## The honest boundary

This gate catches **known** issues. It structurally cannot catch a bug nobody has
found — there is no scenario and no assertion for one. That is what the full
Cowork run is for. Keep the split:

- **gate** = every known issue, seconds, before the run
- **Cowork** = the unknown, thorough, after the gate is green

Don't grow the gate toward being Cowork. Grow it one proven leg per fixed bug.
