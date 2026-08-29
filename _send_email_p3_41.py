"""One-shot push notification email for P3.41 gate-circumvention commit."""
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

subject = "[P3.41] Intake-remediation gate circumvention pushed (6a03377)"
body = """\
Intake-remediation gate circumvention -- TEMPORARY flag-gated bypass
pushed to intake-stable.

  6a03377 Intake-remediation gate circumvention -- temporary E2E-unblock (flag-gated)

Bypasses the 2 known-broken summary gates so E2E can flow through to
post-intake for Fix #2 / Fix #1 verification:
  - target_market_summary (financials.py + intake_submit_service.py)
  - key_people_summary (financials.py + intake_submit_service.py)

Flag default: _SKIP_INTAKE_REMEDIATION_GATES = True.
MUST be set False before any production submission path is exercised.
Proper fix lives in the intake-remediation workstream
(Contract 5d R-d / Contract 5c R-d-bis).

Tests:
  - 1322 tests in suite (+4 new), 11 pre-existing failures (no regressions)
  - 4 new tests in tests/test_intake_remediation_gate_circumvention.py

Next: executing run_persisted_system_run.py against the NexGen draft
to verify post-intake contract layer accepts a production-shaped draft
end-to-end (Part 2 of the directive).
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
