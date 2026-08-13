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
    LIVE:   FAILING  — VS 2026-08-13, RETRACTED on live evidence from
                        CW-031 Ravenwood (draft 1070c6a5). The engine
                        half IS proven (canary: 22/35,519 leaves, all
                        date-derived; workbook: 2 real per-line rows,
                        total =SUM over them). The INTAKE half was
                        NEVER exercised: _ws1b_multiline_e2e.py STAMPS
                        cogs_percent_of_line_revenue onto the rows and
                        then runs the system-run, so it proves
                        rows->engine->workbook and never
                        conversation->rows.
                        LIVE DEFECT: the four per-line percents were
                        PROPOSED to the client in prose (plant 55, hard
                        goods 60, install 38, design 6) but NONE landed
                        on the product rows; only the blended 47%
                        persisted. Per-line is therefore INACTIVE by
                        the all-or-nothing rule and the workbook will
                        carry ONE blended row - contradicting what the
                        client was told in writing.
                        SUSPECTED CAUSE: the message and the write each
                        resolve the COGS baseline independently (two
                        judge calls); the write's call failed the
                        all-or-nothing line-name match and degraded to
                        blend-only SILENTLY.
    COWORK: blocked   — auto-reblocked: LIVE is failing. Nick's 4-stream
                        garden centre is the intended first run (the case
                        WS1b was built for, and the first N>2 exercise).

    NEXT STEP: (1) fix the write so the SHOWN proposal is the WRITTEN
    one (resolve once, or make the degradation loud, never silent);
    (2) re-fixture the multi-line E2E to drive the COGS stage through
    the conversation instead of stamping rows; (3) mini re-fixtures
    R29 to assert survival into persisted ops json. Only then does
    LIVE flip again. Thistledown's unanswered question
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
