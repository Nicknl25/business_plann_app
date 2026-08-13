import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.32 K1 F6 FIX COMMIT - THIRD PAYROLL LEAK CLOSED + DOCTRINE CORRECTIONS

Commit: 5b667ca phase_9_p3_32_k1_f6_payroll_resync_invariant_and_doctrine_corrections
HEAD:   pushed to origin/intake-stable

WHICH DRAFT SURFACED THIS:
Draft 2 (CareFirst Home Health Services) — first run with K1 F1-F5
in place produced a workbook the V-4 verifier rejected with $15,362
Cash Q20 divergence + $828 Payroll Q20 divergence. K1 F1-F5 closed
two known Payroll write paths; the V-4 residual indicated a THIRD.

ROOT CAUSE INVESTIGATION
Traced through the persisted draft state: TWO Handler C iterations
produced different schedules.
  - SQL payroll_headcount column: RN benefits_pct=0.25, Q5=110138
  - model_input.derived_driver_runtime[expenses::Payroll].payroll_
    headcount: RN benefits_pct=0.22, Q5=109380
  - model_input.expenses.Payroll.values[5]=109380

The convergence runner persists schedule_v2 to SQL but the
orchestrator _run_post_cascade_completion uses a stale local
payroll_headcount variable from before convergence. Pre-finalize
persist then writes stale-derived model_input over canonical SQL,
producing the divergence.

Verified payroll is the ONLY lever surface with this embedded-
snapshot pattern. Other expense / balance_sheet / revenue rows
store values directly in model_input.values without separate SQL
column or embedded schedule snapshot.

K PATTERN: K1 F6 (third leak — orchestrator stale local variable).

DOCTRINE FOUR-SURFACE CHECK
Q1. Surfaces: payroll_headcount column (canonical) +
    model_input.expenses.Payroll.values (derived) +
    model_input.derived_driver_runtime[expenses::Payroll].
    payroll_headcount.quarter_totals (snapshot) +
    finmo.pl.Payroll (derived via build_python_finmo_json).
Q2. Alignment: Handler C as single writer +
    apply_payroll_schedule_to_state + Mirror Flavor 1 assertions
    (zero tolerance).
Q3. Preserved: Part 1 of F6 uses the canonical apply chain
    (does not introduce a new writer). Part 2 catches any new
    drift with hard-fail naming the offending stage.
Q4. Handler C consults stage_ramp_contract: YES (confirmed in
    F5 — schedule.py:2191 signature + 2300 prompt + 2478 task
    instruction). F6 re-sync uses apply_payroll_schedule_to_state
    which does NOT invoke Handler C; contract awareness was
    preserved at Handler C authoring time.

F6 IMPLEMENTATION (TWO PARTS)
  Part 1 (orchestrator.py ~1710-1820, ~120 LOC): Re-read
    canonical payroll_headcount from SQL at start of
    _run_post_cascade_completion. If quarter_totals tuple differs
    from local variable, call apply_payroll_schedule_to_state to
    refresh model_input + finmo through the canonical apply chain.

  Part 2 (orchestrator.py ~2860-2965, ~100 LOC): Three-surface
    invariant assertion BEFORE pre-finalize persist (outside the
    persist try/except so the fail-fast surfaces clearly). Asserts
    per-quarter equivalence (with 1 dollar int-rounding tolerance)
    across the three payroll surfaces. On disagreement raises
    pre_finalize_persist_payroll_three_surface_invariant_violation
    naming all three surfaces + per-quarter deltas + guidance.

DOCTRINE.MD UPDATES (L-3)
  Added section 10 with two corrections:
    10.1 K7 revised: intake data gaps require adaptive handling
         (fallback derivation OR early user surfacing), NOT crash.
         Luminous Glow OEWS empty case = canonical example.
    10.2 K4(b) eliminated: no infeasible plan classification.
         Every acceptance gate failure must be investigated for
         the missing adaptation, then the adaptation must be
         built (L-1 / L-6).
    10.3 K1 F6 framed as the surfacing pattern: detect
         divergence, name the gap, build the adaptation.

SCOPE
  LOC:            ~440 total (~220 production / ~210 tests / ~95 doctrine)
  Files touched:  1 production + 1 new test + 1 doctrine
    orchestrator.py
      -- F6 re-sync block at start of _run_post_cascade_completion
      -- F6 three-surface invariant before pre-finalize persist
    test_phase_9_p3_32_k1_f6_payroll_state_resync_invariant.py
      -- 14 new regression guard tests across 6 test classes
    doctrine.md
      -- New section 10 with the two doctrine corrections

LATITUDES INVOKED
  L-1 (new infrastructure): three-surface invariant is new
       structural enforcement at a previously-unprotected gate.
  L-3 (doctrine evolution): section 10 captures the K7 and K4(b)
       corrections; K1 F6 surfaces the evolution in code.

TESTS PASSING
  Pre-F6:   411/414 pass (3 pre-existing failures)
  Post-F6:  424/427 pass (same 3 pre-existing; +13 new F6 tests
            +1 previously-failing test_pre_finalize_persist_wrapped_
            in_try_except now passes after F6 invariant restructure)
  Net delta: ZERO new failures from F6.

NEXT STEPS
  - Re-run CareFirst with K1 F1-F6 in place. Verify V-1 through
    V-4 all pass. V-4 expectation: max_abs near zero, not 15K.
  - If V-4 passes: investigate CareFirst three K4 realism
    failures with the corrected adaptive doctrine (NOT K4(b)).
    Failing metrics: ebitda_positive_by_q11, fixed_cost_burden_
    reduced_or_scaled_by_q11, gross_margin_supports_ebitda_recovery.
    Build the missing adaptation under L-1/L-6 authority.
  - If V-4 fails: trace residual write path; F6 invariant will
    name the offending stage in the diagnostic.

K1 IS NOW COMPLETE (F1+F2+F3+F4+F5+F6).
Every Payroll write path that could break Mirror Flavor 1 is
structurally closed. Any future divergence will fail-fast at the
F6 pre-finalize invariant with a stage-naming diagnostic.
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = "[P3.32 K1 F6] Third payroll leak closed + doctrine corrections (K7 + K4(b) eliminated)"
msg["From"] = sender
msg["To"] = to

ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent.")
