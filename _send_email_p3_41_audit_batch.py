"""One-shot push notification email for P3.41 round-1 audit batch."""
import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

host = os.environ["EMAIL_HOST"]
port = int(os.environ.get("EMAIL_PORT", "587"))
user = os.environ["EMAIL_USER"]
password = os.environ["EMAIL_PASSWORD"]
sender = user
to = os.environ["EMAIL_ALERTS_ADDRESS"]

subject = "[P3.41 NexGen loop] Audit batch pushed (3279f49) -- F-J1 + F-C1 + F-C2"
body = """\
P3.41 round-1 set-tool audit batch landed.

  3279f49 Round-1 set-tool audit batch: F-J1 de-hardcode operational
          ni_floor (also fixes iter 9), F-C1 fix stage_ramp envelope
          max_util naming, F-C2 delete dead payroll envelope arms

F-J1 -- De-hardcoded the operational net_income_margin_floor producer
in post_intake_contracts/runner.py:1688+. The 20-quarter floor array
is now derived entirely from validator_rules (planning-mode-policy
values). ZERO hardcoded floor numbers in executable code; the only
0.0 literal is the explicitly-named universal_viability_floor
constant per post_intake_mapping.py:2956 doctrine.

BEHAVIOR REPORT (per directive's policy q5_q10_operational question):

  Mode               | Old Q5-Q10 | New Q5-Q10 | Old Q11-Q20 | New Q11-Q20
  -------------------|------------|------------|-------------|-------------
  rebalance          | 0.02       | 0.05       | 0.02        | 0.07
  turnaround         | 0.02       | clamp-dep* | 0.02        | 0.00
  normalize          | 0.02       | 0.02       | 0.02        | 0.05  <-- NexGen
  growth_investment  | 0.02       | clamp-dep* | 0.02        | 0.05
  preservation       | 0.02       | 0.05       | 0.02        | 0.10

  * turnaround / growth_investment set operational_requires_nonneg
    =False -> Q5-Q10 becomes -0.05 (LOOSER than old hardcoded 0.02).

NexGen specifically is on `normalize` mode: Q5-Q10 unchanged at 0.02
(matches old hardcode); Q11-Q20 tightens 0.02->0.05 (fixes iter 9 by
construction).

If preserving the 2% Q5-Q10 operational baseline for turnaround and
growth_investment is desired, that's a SEED change (set
profitability_floor_q5_q10_operational = 0.02 for those modes in the
planning_mode_policy table) -- NOT a producer hardcode. Nick's call;
the producer de-hardcode landed regardless.

F-C1 -- stage_ramp envelope: util_max -> max_util rename + util_floor
removal + dead consistency-check deletion. Producer-aligned now.

F-C2 -- payroll envelope: 2 dead arms (roles/wages + schedule) deleted
(zero producer occurrences for either set of field names). Only the
LIVE target_payroll_percent_of_revenue arm remains. Adding equivalent
invariants on the real payroll_headcount_grid is a separate design
task -- out of scope.

Test suite: 1359 tests (+11 net: +15 new in test_p3_41_round1_audit_
batch.py, -4 stale dead-check tests removed). 11 pre-existing failures
unchanged (no regressions).

Running loop log (session-cumulative, 11 commits):
  6a03377  Intake-remediation gate circumvention
  502ca89  Contract 5c target_market_summary -> Optional
  4678159  Contract 6 raw_confidence_tier -> Optional (iter 1)
  fabdc4b  Contract 1 Literals + parity (iter 2)
  f168adf  Contract 1 R3 amendment (iter 3)
  66ecf40  Contract 1 ScheduleRow period-scope (iter 4)
  2cb2475  Contract 1 solver_input Optional (iter 5)
  7262a25  FINMO_SYNC guard names (iter 6)
  8d93950  Round-1 set-tool TypeError + NameError (iter 7)
  d904ce0  Round-1 envelope unit mismatch (iter 8)
  79ac6ef  Round-1 audit catalog (doc-only)
  3279f49  Round-1 audit batch F-J1+F-C1+F-C2 (this push)

Next: restart backend + re-run NexGen E2E.
"""

msg = MIMEText(body)
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to

with smtplib.SMTP(host, port) as server:
    server.starttls()
    server.login(user, password)
    server.send_message(msg)

print(f"Sent push-notification email to {to}")
