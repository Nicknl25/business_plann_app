# WORK ITEM STAGES — the single visible answer to "is it done?"

This file exists because "done" meant different things to each agent and
Nick was left adjudicating: on 2026-08-13 mini said the gate was clean
(true) and VS said not yet (also true — nothing had run live), and there
was no one place that said both. Every work item now carries three
stages, so "done" is always qualified and the next step is always named.

    GATE   — the proof harness is clean (replay gate: legs, goldens, floor)
    LIVE   — exercised on the real stack (backend restart, canary, E2E)
    COWORK — cleared to spend a real Cowork run on

WHO FLIPS WHAT (ownership, mirrors the agent boundaries):
  - GATE   is MINI's to flip. Only mini blesses the gate; VS never does.
  - LIVE   is VS's to flip, and only on evidence: a canary that completed
           on the shipped build plus the feature's own live exercise.
  - COWORK is AUTOMATIC: it is `cleared` when GATE=blessed and
           LIVE=passed, `blocked` otherwise. Nobody sets it by hand.

STATUS VOCABULARY (deliberately small):
  GATE:   blessed | clean-unblessed | failing | n/a
  LIVE:   passed | pending | failing | n/a
  COWORK: cleared | blocked

RULES
  - A stage may only be flipped by its owner, with the evidence named on
    the same line. "passed" with no evidence file is not a status.
  - Regression re-opens stages: any app-code change sets LIVE back to
    pending (the canary law), which re-blocks COWORK automatically.
  - Every new work item gets a block here when it starts, not when it
    finishes.

---

## per-line-COGS  (WS1a confidence gate + WS1b N-line COGS + WS2 retention)

    GATE:   blessed   — Nick 2026-08-13, on mini's round-10 audit: prove
                        clean 50/50, freeze audited independently (DB
                        poisoned, digests reproduced, frozen payloads
                        sha256-matched to live, mutated lookup moved the
                        digest). Evidence: _prove_20260813_*.txt,
                        VS_NOTES rounds 8-10.
    LIVE:   passed    — VS 2026-08-13, on three pieces of evidence:
                        (a) backend restarted on the shipped build
                        (c77094a), ONE :5050 listener, pid 28944;
                        (b) SUNNY_V3 CANARY completed through production
                        (post_intake_finalize_validation_completed) AND
                        the single-line floor proven live: the pre-ship
                        run (08-12 17:07, old code) vs today's post-ship
                        run of draft 6feac758 differ in 22 of 35,519
                        compared leaves, ALL 22 date-derived, ZERO
                        otherwise; 0 COGS% rows emitted on both sides.
                        The digests moved only because the forecast
                        anchor is wall-clock. Evidence:
                        _handoff/logs/canary_20260813.txt;
                        (c) MULTI-LINE E2E on a clone of the real
                        Thistledown two-line draft: 2 COGS% rows, Sigma
                        == blend on all 20 quarters (worst rel gap
                        0.00000), finmo cogs == Sigma on 20 quarters,
                        and the WORKBOOK carries two real per-line COGS
                        formula rows with the total as =SUM(D9:D10) over
                        them, each line reading
                        ='Model Inputs'!<line revenue>*'Model Inputs'!<line COGS%>.
                        Evidence: _handoff/logs/multiline_e2e_20260813.txt,
                        workbook "Thistledown Cycle and Service --
                        08-13-2026 10-48-37.xlsx".
    COWORK: cleared   — GATE blessed + LIVE passed. Nick's 4-stream
                        garden centre is the intended first run (the case
                        WS1b was built for, and the first N>2 exercise).

    NEXT STEP: none for this item — it is done for the gate, done live,
    and cleared for a Cowork run. Thistledown's unanswered question
    ("shouldn't bikes and repairs be different?") now answers itself:
    bike sale 52%, repair 22%, two rows in the client's workbook.

---

## handoff-watcher  (VS<->mini loop automation)

    GATE:   blessed   — mini's audit 9/9 behaviours + 5/5 probes, re-run
                        after every change. Evidence:
                        Test Files/_audit_handoff_watcher.py
    LIVE:   passed    — driving real turns since 2026-08-12: rounds 8-10
                        ran through it end to end (VS freeze -> mini
                        audit -> prove -> flip). Loop harness 8/8:
                        Test Files/_e2e_handoff_loop.py
    COWORK: n/a       — internal tooling; no client run to spend.

---

## proactive-stream-discovery  (NOT STARTED — research first)

    GATE:   n/a       — nothing built.
    LIVE:   n/a
    COWORK: blocked
    NEXT STEP: research the shape (where category knowledge comes from,
    how to ask about EXISTENCE without proposing new revenue, how a
    discovered stream lands as a real LOB through the confidence gate).
    Report before building. Scoped AFTER per-line COGS lands live.
