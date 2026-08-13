"""One-shot push notification email for P3.41 NexGen guarded loop iter 3."""
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

subject = "[P3.41 NexGen loop] Iter 3 pushed (f168adf) -- R3 amendment, 3 opaque blobs"
body = """\
P3.41 NexGen guarded autonomous fix loop -- iter 3 landed.

  f168adf Contract 1 R3 amendment -- 3 producer-stamped opaque blobs
          added (NexGen E2E iter 3)

Three Optional[Dict[str, Any]] = None fields added to row classes that
were tripping extra='forbid' at runtime on the NexGen iter-3 rerun:

  - BalanceSheetRow.balance_sheet_stock_carryforward
      (finmo_bridge.py:544 -- any business with stock-level
      carryforward adjustments)
  - BalanceSheetRow.mapping_table_presence_applicability
      (finmo_bridge.py:3644 -- any business with Deferred Revenue
      (% of Revenue) lever; surfaced the iter-3 violation)
  - ExpenseRow.payroll_headcount_schedule
      (post_intake_headcount/schedule.py:2488 -- universal,
      any business has Payroll)

All universal producer paths -- not NexGen-specific. Same first-cut-
opaque-typing pattern as the pre-existing R3 blobs (capex_depreciation,
payroll_supported_capacity, capacity_shaping, balance_sheet_contextual
_seed, seed_provenance_json). R3's deferred sub-contract typing wave
now covers 8 blobs instead of 5.

Test suite: 1333 tests, 11 pre-existing failures (no regressions).

Running loop log (session-cumulative):
  6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
  502ca89 -- Contract 5c target_market_summary -> Optional (R-d-bis)
  4678159 -- Contract 6 raw_confidence_tier -> Optional (R-d-raw, iter 1)
  fabdc4b -- Contract 1 value_kind/input_semantics Literals + seed-
              parity guard (iter 2)
  f168adf -- Contract 1 R3 amendment, 3 opaque blobs (iter 3)

Next: restarting backend + re-running run_persisted_system_run.py
against the NexGen draft to see what surfaces next.
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
