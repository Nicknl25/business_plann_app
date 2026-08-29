"""One-shot push notification email for P3.41 NexGen guarded loop iter 4."""
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

subject = "[P3.41 NexGen loop] Iter 4 pushed (66ecf40) -- ScheduleRow period-scope fields"
body = """\
P3.41 NexGen guarded autonomous fix loop -- iter 4 landed.

  66ecf40 Contract 1 ScheduleRow -- add 4 period-scope Optional
          fields (NexGen E2E iter 4)

Inventory oversight in the original Contract 1: ScheduleRow was the
sole row class missing the 4 period-scope template fields. Producer
_full_quarter_scope (finmo_bridge.py:244) stamps these on every row
template universally. Fix mirrors the same 4 Optional fields onto
ScheduleRow that already exist on Revenue/Expense/BalanceSheet:
  - valid_quarter_indices: Optional[List[int]] = None
  - valid_period_columns: Optional[List[str]] = None
  - total_period_count: Optional[int] = None
  - writable_full_quarters_only: Optional[bool] = None

Universal producer path -- not NexGen-specific. No R3 sub-contract
typing implied (scalars + flat lists, not opaque nested dicts).

Test suite: 1333 tests, 11 pre-existing failures (no regressions).

Running loop log (session-cumulative):
  6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
  502ca89 -- Contract 5c target_market_summary -> Optional (R-d-bis)
  4678159 -- Contract 6 raw_confidence_tier -> Optional (R-d-raw, iter 1)
  fabdc4b -- Contract 1 value_kind/input_semantics Literals + seed-
              parity guard (iter 2)
  f168adf -- Contract 1 R3 amendment, 3 opaque blobs (iter 3)
  66ecf40 -- Contract 1 ScheduleRow period-scope fields (iter 4)

Consecutive Optional-style fixes: 2 (iter 3 + iter 4); iter 2 broke
the chain. Under the 5+ checkpoint threshold; continuing.

Next: restart backend + re-run run_persisted_system_run.py against
the NexGen draft to see what surfaces next.
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
