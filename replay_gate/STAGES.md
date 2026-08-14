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
    LIVE:   failing   — RETRACTED 2026-08-13 23:20 on CW-032 Alderfen:
                        the in-stage surface fails (3 artifact-backed
                        filings incl. 2 blockers). VS's conversation
                        check ran at the WALL; the client corrects IN
                        THE STAGE, which has no line-scoped field. The
                        engine + wall-door remain proven. Was: VS 22:15, on the FIXED build (CW-031
                        batch, gate blessed 61 legs / 0 DRIFT / R43):
                        (a) backend on HEAD, ONE :5050 listener;
                        (b) Sunny_V3 canary completed AND byte-identical
                        to the pre-batch canary (FINMO 76336ce0...,
                        MODEL_INPUT c4292f8e... - 14 rounds of intake
                        surgery moved a single-line draft ZERO bytes);
                        (c) multi-line E2E: 2 COGS rows, Sigma==blend
                        all 20q, workbook =SUM over per-line rows;
                        (d) NEW - CONVERSATION-DRIVEN live check (the
                        path the old E2E skipped): fresh Ravenwood
                        clones through the real router - separation
                        lands basis=declared per line; the uniform-rate
                        ask converts a yes into a DECLARED group whose
                        receipt speaks the stored values; an unmatched
                        figure gets an honest no-record; stated dollars
                        land as the right fraction. LIVE RESULT: CLEAN.
                        Evidence: _live_cw031_round9_turns output,
                        canary + E2E task logs 2026-08-13 22:0x.
    COWORK: blocked   — auto-reblocked on the CW-032 filings. Nick's 4-stream
                        garden centre is the intended first run (the case
                        WS1b was built for, and the first N>2 exercise).

    NEXT STEP: none — done for the gate, done live, cleared for the
    4-stream garden-center Cowork (the first N>2 run on the FIXED
    intake half). Post-batch: the inference scan (section F of the
    boundary seed) as its own task.
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
