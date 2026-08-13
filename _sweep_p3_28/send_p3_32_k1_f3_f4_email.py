import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.32 K1 F3+F4 FIX COMMIT - LEAK B CLOSED

Commit: 61a4433 phase_9_p3_32_k1_f3_f4_close_leak_b_solver_payroll_exclusion
HEAD:   pushed to origin/intake-stable

K1 IS NOW FULLY APPLIED (F1+F2 + F3+F4).
The two Payroll-authority leaks from P3.31 audit are STRUCTURALLY
CLOSED. Every write path to expenses::Payroll now routes through
Handler C (post_intake_headcount.schedule.estimate_payroll_
headcount_schedule_with_gpt + its apply chain).

WHICH DRAFT SURFACED THIS:
  Leak B was identified by the P3.31 audit (not a sweep failure).
  Realism config in 6 lookup.py rows listed expenses::Payroll in
  primary_levers/secondary_levers; restoration target-solver
  wrote to those levers directly, bypassing Handler C.

K PATTERN: K1 (Leak B — target-solver bypass via realism config).
  Fix shape per P3.31 §5: F3+F4 second commit (~50 LOC).

DOCTRINE 3-SURFACE CHECK:
  Q1. What surfaces hold the conceptual data?
      payroll_headcount.{rows,quarter_totals,assumptions} canonical;
      model_input.expenses::Payroll + finmo.pl.Payroll + finmo.
      quarter_rows.payroll all DERIVED via Handler C apply chain.
  Q2. How are they kept aligned?
      Handler C as single writer + the apply chain's Mirror
      Flavor 1 assertions (zero tolerance).
  Q3. Does this fix preserve alignment?
      YES. Excluding Payroll from solver authority means the
      deterministic solver cannot break alignment by writing
      only to model_input.

SCOPE:
  LOC:            ~210 total (~85 production / ~125 tests)
  Files touched:  3 production + 1 new test + 1 test update
    target_solver.py    -- exclusion frozenset + dispatch +
                           entry validation
    restoration_loop.py -- bounds resolver skip (defense in depth)
    lookup.py           -- 6 realism rows: removed Payroll from
                           primary_levers (4 rows) +
                           secondary_levers (2 rows)
    test_phase_9_p3_32_k1_f3_f4_solver_payroll_exclusion.py
                        -- 15 new regression guard tests
    test_phase_9_p3_32_k1_payroll_authority_closure.py
                        -- added sys.path bootstrap

LATITUDES INVOKED:
  L-2 (adjacent refactor): F4 touched ALL 6 realism rows with
       Payroll in lever lists, not just the ones from active
       sweep failure data. Same doctrine gap; closing them
       together prevents future surprises.

DEFENSE IN DEPTH:
  - Solver-side exclusion (F3): solve_for_target raises
    CashPassLeverViolation if any caller passes Payroll in
    driver_lever_ids. Catches accidents.
  - Bounds resolver skip (F3): restoration_loop drops Payroll
    levers from the primary_levers iteration before they reach
    the solver. Makes the entry validation a backstop, not a
    user-facing error.
  - Realism config sync (F4): in-code defaults have no
    Payroll listings. SQL bootstrap upsert syncs on next API
    restart.
  - K1 F1+F2 commit (already landed): exhaustion handler
    cannot author Payroll. Combined with this commit, NO
    non-Handler-C path can touch Payroll.

TESTS PASSING:
  Pre-K1 baseline:      384/387 (3 pre-existing failures —
                        test_lease_balance_is_floored_at_zero,
                        test_ppe_is_derived_from_opening_balance_
                        capex_and_depreciation,
                        test_model_input_json_round_trips_all_
                        controller_write_sections; unrelated)
  Post K1 F1+F2:        394/397 (same 3 pre-existing; +10 new)
  Post K1 F3+F4 (NOW):  409/412 (same 3 pre-existing; +15 new
                                  K1 F3+F4 tests pass)
  Net delta:            ZERO new failures from K1.

K1 F5 STATUS:
  K1 F5 (~50 LOC, Med risk) is CONDITIONAL per P3.31 §5
  sequencing rationale: "Worth running F1-F4 first and observing
  the sweep before deciding." Will revisit if F1-F4 leave
  residual cases during the draft sweep.

NEXT STEPS:
  - Start API server with CONVERGENCE_TEST_MODE=true.
  - Begin draft 1 (Anderson & Blake Legal Associates — known
    cash_buffer K3 pattern from P3.28).
  - Design + build K3 cash buffer repair handler (L-1, L-6
    authorized — ~150-300 LOC new dedicated handler with
    authority over cash policy + funding levers + appropriate
    expense levers).
  - Continue sweep sequentially through all 28 drafts.
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = "[P3.32 K1 F3+F4] Leak B closed - solver Payroll exclusion + realism config sync"
msg["From"] = sender
msg["To"] = to

ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent.")
