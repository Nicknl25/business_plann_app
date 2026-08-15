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

    GATE:   blessed   — mini 2026-08-14, post CW-032 batch: the R31 DRIFT
                        (ruled opening-PPE depreciation, Nick ratified)
                        proven PURE leaf-by-leaf at BOTH boundaries before
                        re-baselining (gate build: Q1 delta exactly 750 =
                        15,000/20; solver checkpoint: exactly 1,000 =
                        20,000/20; zero non-depreciation movers; date-anchor
                        confound isolated with a pre/pre control). R31
                        re-blessed at baseline 5716ba4; frozen-input +
                        byte-floor goldens re-based; prove CLEAN 61 legs /
                        0 DRIFT / 0 UNEARNED. Evidence:
                        _mini_cw032_drift_purity_20260814.txt,
                        _prove_20260814_mini_cw032_turn1.txt.
                        Was: Nick 2026-08-13, on mini's round-10 audit
                        (_prove_20260813_*.txt, VS_NOTES rounds 8-10).
    LIVE:   passed    — VS 2026-08-14, on HEAD 8c173cc (the CW-032 batch,
                        gate re-blessed same day):
                        (a) backend restarted on HEAD 13:29:25, ONE
                        :5050 listener (pid 12688);
                        (b) Sunny_V3 byte-floor canary (6feac758)
                        completed through production, both SHAs
                        IDENTICAL to the re-blessed post-depreciation
                        goldens (FINMO 97117892..., MODEL_INPUT
                        e813c118...), same-day caveat satisfied:
                        _canary_cw032_live_byte_floor_20260814.txt;
                        (c) multi-line E2E GREEN: client's four-rate
                        sentence -> live wall router -> real system-run
                        -> four COGS driver rows on Model Inputs, FINMO
                        exactly ONE 'Cost of Goods Sold' row that IS
                        the four-term roll-up, zero per-line P&L rows,
                        _assert_workbook_cogs_rows PASSES on the
                        delivery-record binding, Q1 depreciation carries
                        the straight-line share:
                        _live_cw032_multiline_e2e_20260814.txt;
                        (d) THE IN-STAGE CONVERSATION CHECK (the surface
                        CW-032 Alderfen failed on) GREEN on fresh
                        rewound 4-line clones: S1 all four client rates
                        (46/73/17/3) land in ONE message, stage
                        COMPLETES on the derived blend 42.2%, reply is
                        the receipt not the Alderfen refusal; S2
                        collapse stores /shared/ on exactly the named
                        rows basis=declared; S3 single-line write keeps
                        the per-line recovery shape, no false receipt:
                        _live_cw032_instage_20260814.txt.
                        (Was: RETRACTED 2026-08-13 23:20 on the CW-032
                        Alderfen in-stage failure; the fix batch closed
                        it and this pass re-exercised that surface.)
    COWORK: cleared   — automatic: GATE=blessed + LIVE=passed
                        (2026-08-14). Nick's 4-stream garden centre is
                        the intended first run (the case WS1b was built
                        for, and the first N>2 exercise).

    NEXT STEP: Nick re-runs the garden center to SEE it — four COGS
    driver rows on Model Inputs and the one summing P&L line. After
    that Cowork run: the inference scan (section F of the boundary
    seed) as its own task, and proactive stream discovery research
    (block below).

---

## deal-breaker-batch  (A1 price/util last-figure-wins, A2 net-N-as-capacity, A3 stated-capacity wall, A4 mid-market copy, E1/E2 cadence receipt + say-do)

    GATE:   blessed   — mini 2026-08-15, turn F VERDICT green (ca0c072):
                        A1/A2/A4 spot-check audit (turn B), A3
                        neighbor-check audit CONFIRMED w/ independent
                        40-draft PRE/POST sweep + 12 mover-neighbor legs
                        (turn D, f39a051), E1/E2 spot-check audit (turn
                        F); floor R31+R32 GOLDEN on every turn.
    LIVE:   passed    — VS 2026-08-15, per the spot-check verification
                        law (no canary owed): live PRE red -> POST green
                        artifacts on the real shapes — A3 F&F turn-96
                        137%-of-capacity PASS -> FAIL at 1.58x + 40-draft
                        live sweep (4cf365f); E1/E2 live PRE/POST on a
                        Sumac clone (f6ea787, _live_turnE_PRE/_POST);
                        A1/A2/A4 red-proof on stored ops values / rendered
                        summary (Test Files/_redproof_dealbreaker_turnA.py);
                        backend restarted on HEAD ca0c072 12:00, ONE
                        :5050 listener.
    COWORK: cleared   — automatic: GATE=blessed + LIVE=passed
                        (2026-08-15). ONE confirming run scoped to the
                        fixes (agenda rank 1), then discovery.

    NEXT STEP: Nick's confirming Cowork run (verify A1/A2/A3/receipt
    live + per-line COGS still end-to-end). New findings get TRIAGED
    (deal breaker vs wont-fix) for Nick — not auto-fixed.

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
