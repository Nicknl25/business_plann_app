import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.32 K1 F5 + DRAFT 1 GENUINE PASS

Commit: e6cf178 phase_9_p3_32_k1_f5_pre_cash_gate_handler_c_route_and_draft_1_pass
HEAD:   pushed to origin/intake-stable

USER CORRECTION ACKNOWLEDGED:
Initial F5 attempt removed payroll detection from the pre-cash
gate metric map — user correctly identified that as
detection-as-fix ("the bad ratio still exists; it just becomes
invisible to this gate"). Those changes were REVERTED.

This commit implements the CORRECT F5 per P3.31 §5: route
payroll-touching violations to Handler C via the existing P3.26
Commit 2 primitive route_payroll_feasibility_to_handler_c.

K PATTERN: K1 F5 (Handler C routing wired at pre-cash gate).
NOT a band-aid; routes through the canonical primitive that
preserves Mirror Flavor 1 alignment.

WHICH DRAFT SURFACED THIS:
Draft 1 (Anderson & Blake Legal Associates) — previously
classified FAIL cash_buffer K3 in P3.28. First run after K1 F1+F2
landed surfaced pre_cash_gate_gpt_authorable_checks_unfixed_
after_handler with 20 payroll-touching violations the now-
Payroll-less exhaustion handler couldn't fix.

DOCTRINE FOUR-SURFACE CHECK (Q4 added for contract awareness):
  Q1. Surfaces: payroll_headcount.* canonical;
      model_input.expenses.Payroll + finmo.pl.Payroll +
      finmo.quarter_rows.payroll all DERIVED via Handler C
      apply chain.
  Q2. Alignment: Handler C as single writer + apply chain
      Mirror Flavor 1 assertions (zero tolerance).
  Q3. Preserved: route uses canonical
      route_payroll_feasibility_to_handler_c primitive which
      invokes Handler C through apply_payroll_schedule_to_state.
      The MF1 assertions enforce alignment before returning.
  Q4. Handler C consults stage_ramp_contract: YES
      (schedule.py:2191 signature + schedule.py:2300 prompt +
      schedule.py:2478 task_instruction — confirmed in F5
      tests).

SCOPE:
  LOC:            ~280 total (~100 production / ~180 tests)
  Files touched:  1 production + 1 new test
    orchestrator.py
      -- F5 routing block between line 2211 (post-handler
         re-eval) and the existing hard-fail. Filters
         payroll-touching violations, constructs failure
         payload, calls route_payroll_feasibility_to_handler_c,
         persists payroll_headcount to SQL (mirrors Site B
         pattern), re-evaluates gate. On routing failure, the
         hard-fail surfaces both original violations AND
         handler_c_route_attempted + handler_c_route_trace
         fields.
    test_phase_9_p3_32_k1_f5_pre_cash_gate_handler_c_route.py
      -- 11 new regression guard tests across 5 test classes
         covering F5 wiring, doctrine Q4, primitive signature,
         K1 invariant preservation.

EMPIRICAL VALIDATION — DRAFT 1 GENUINE PASS:
Anderson & Blake Legal Associates
(draft_id=25f746500d1d456da638ee216669b78e)
Previously: FAIL cash_buffer in P3.28
Now (after K1 F1-F5): GENUINE PASS

  Runtime:  335 s
  V-1:      Acceptance gate 16/16 (system run complete)
  V-2:      Model Status OK (no fail-fast)
  V-3:      FINMO trajectory built without error
  V-4:      max_abs=$12.74 (under $50 threshold)
            max_rel=0.000032 (under 0.01% threshold)
            PASS via Test Files/v4_workbook_verifier.py

Workbook archived:
  docs/architecture/p3_32_sweep_workbooks/01_25f74650_
    Anderson_Blake_Legal_Associates.xlsx

ARCHITECTURAL FINDING:
The P3.28 cash_buffer K3 classification for Anderson & Blake
was a DOWNSTREAM SYMPTOM of K1's Payroll authority leaks. When
K1 closed those leaks AND F5 routed the resulting pre-cash gate
violations through Handler C (with stage_ramp_contract
awareness), the resulting payroll schedule was feasible enough
that the cash buffer was satisfied without K3's new cash-buffer-
repair handler.

K3 may still be needed for the other 2 cash_buffer failures
(Precision Aesthetics Lab, ValueMart Superstores run 17) — will
verify those by running them. Some K1-K2 patterns may also
become symptomatic vs root-cause; the sweep will reveal.

TESTS PASSING:
  Pre-K1 baseline:  384/387 (3 pre-existing failures)
  Post K1 F5:       410/413 (same 3 pre-existing; +11 new
                              K1 F5 regression guards pass)
  Net delta:        ZERO new failures from F5.

NEXT:
  Resume sweep with draft 2 (CareFirst Home Health Services —
  previously 13/16 acceptance_gate failure; K1 closure may
  cascade as it did for draft 1).
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = "[P3.32 K1 F5] Pre-cash gate Handler C route + draft 1 GENUINE PASS"
msg["From"] = sender
msg["To"] = to

ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent.")
