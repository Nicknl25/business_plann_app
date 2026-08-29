"""One-shot push notification email for P3.41 NexGen guarded loop iter 8 (envelope unit-mismatch fix)."""
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

subject = "[P3.41 NexGen loop] Iter 8 pushed (d904ce0) -- envelope unit mismatch fixed + sibling sweep clean"
body = """\
P3.41 NexGen guarded autonomous fix loop -- iter 8 landed.

  d904ce0 Round-1 envelope check: read maintenance_rate (ratio) not
          maintenance_capex_percent against [0,1]; sweep sibling
          envelope checks; surfaced by NexGen E2E

NON-CONTRACT source fix. Semantic unit mismatch in
_check_envelope_violations -- the check read the percent-form field
against a ratio bound, dead-on-arrival for any valid maintenance-
capex band (NexGen surfaced 2.14 > 1.0).

FIX (option A): switched the field read to maintenance_rate (the
canonical ratio form every downstream consumer uses); kept the
[0,1] sanity floor. Producer is correct; check picked the wrong
field.

SWEEP (same function only, per directive):
  - mc check -- BUG, fixed.
  - rd check -- NONE BY DESIGN (R&D producer returns
    {r_and_d_enabled: bool, ...}, zero numeric fields).
  - bs check -- CLEAN (reads seed_value against >= 0; producer
    convention matches; days/ratio/currency all share the
    non-negative-magnitude invariant).

ESCALATION FLAG: the test file imports _check_envelope_violations
from THREE sibling set-tool modules NOT audited in this sweep:
  - set_stage_ramp_contract
  - set_payroll_schedule
  - set_drivers
They may harbor the same percent-vs-ratio shape. Worth a broader
round-1/round-2 set-tool envelope audit (your call on scope).

Test suite: 1348 tests (+10 new for the fix + sweep), 11 pre-
existing failures (no regressions). 3 existing tests updated to
assert the corrected field.

Running loop log (session-cumulative):
  6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
  502ca89 -- Contract 5c target_market_summary -> Optional
  4678159 -- Contract 6 raw_confidence_tier -> Optional (iter 1)
  fabdc4b -- Contract 1 value_kind/input_semantics Literals + parity (iter 2)
  f168adf -- Contract 1 R3 amendment, 3 row blobs (iter 3)
  66ecf40 -- Contract 1 ScheduleRow period-scope fields (iter 4)
  2cb2475 -- Contract 1 top-level solver_input Optional (iter 5)
  7262a25 -- Dead FINMO_SYNC guard names corrected (iter 6)
  8d93950 -- Round-1 set-tool TypeError + NameError fixes (iter 7)
  d904ce0 -- Round-1 envelope check unit mismatch fix + sweep (iter 8)

Next: restart backend + re-run NexGen draft to see what surfaces.
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
