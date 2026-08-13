"""One-shot push notification email for P3.41 NexGen guarded loop iter 5."""
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

subject = "[P3.41 NexGen loop] Iter 5 pushed (2cb2475) -- top-level solver_input"
body = """\
P3.41 NexGen guarded autonomous fix loop -- iter 5 landed.

  2cb2475 Contract 1 FinmoModelInputContract -- add solver_input
          Optional (NexGen E2E iter 5)

Top-level FinmoModelInputContract was missing solver_input. Producer
finmo_bridge.py:3227-3230 unconditionally stamps it via
next_payload.setdefault("solver_input", {}) and populates with
driver_movement_envelope + finmo_output_target sub-payloads.
Universal across all businesses going through
build_python_model_input_json.

Producer-scope verification: enumerated every next_payload top-level
mutation across finmo_bridge.py -- solver_input is the only top-
level field missing from the contract; all other producer-stamped
top-level fields are already declared.

Fix: solver_input: Optional[Dict[str, Any]] = None mirroring the
pattern of the two pre-existing derived_driver_* opaque fields.
R3's sub-contract typing wave now covers 9 blobs (8 row + 1 top).

Test suite: 1333 tests, 11 pre-existing failures (no regressions).

Running loop log (session-cumulative):
  6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
  502ca89 -- Contract 5c target_market_summary -> Optional (R-d-bis)
  4678159 -- Contract 6 raw_confidence_tier -> Optional (R-d-raw, iter 1)
  fabdc4b -- Contract 1 value_kind/input_semantics Literals + seed-
              parity guard (iter 2)
  f168adf -- Contract 1 R3 amendment, 3 row opaque blobs (iter 3)
  66ecf40 -- Contract 1 ScheduleRow period-scope fields (iter 4)
  2cb2475 -- Contract 1 top-level solver_input Optional (iter 5)

Consecutive Optional-style fixes since iter 2: 3 (iter 3 + 4 + 5).
Under the 5+ checkpoint threshold; continuing.

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
