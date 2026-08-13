"""One-shot push notification email for P3.41 Contract 5c R-d-bis fix."""
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

subject = "[P3.41] Contract 5c R-d-bis contract-typing fix pushed (502ca89)"
body = """\
Contract 5c R-d-bis CONTRACT-TYPING portion -- RESOLVED.

  502ca89 Contract 5c target_market_summary -> Optional (R-d-bis contract-typing fix, surfaced by NexGen E2E)

Asymmetry resolved: Contract 5d had typed key_people_summary as
Optional[str] = None from the start; Contract 5c was missing the
symmetric disposition for target_market_summary. Now mirrored.

Surfaced by the NexGen E2E run (2026-05-30) where the contract fired
at target_market_json_contract.py:256 against real production payload
(field absent per intake_consult.py:10863 pop, commit e57ff49
single-source-of-truth pattern).

Changes:
  - target_market_json_contract.py: str -> Optional[str] = None
    with mirrored 13-line comment block referencing 5d
  - _p3_40_contract_5c_fixtures.py: default flipped to OMITTED
    (production POST-POP), include_target_market_summary toggle added
  - test_p3_40_contract_5c_target_market_json.py: rename +2 mirror
    tests (None, absent, populated)
  - p3_40_contract_5c_target_market_json_spec.md §8 R-d-bis SPLIT
    (contract-typing RESOLVED, gate still DEFERRED)
  - p3_40_contract_layer_closeout.md §3 + §5 + §6 + §7 updated
    (14 DONE + 4 ASSESSED + 47 DEFERRED + 0 NOT PURSUED = 65)

Test suite: 1324 tests (+2 net new), 11 pre-existing failures (no
regressions).

GATE portion still DEFERRED to intake-remediation workstream
(_SKIP_INTAKE_REMEDIATION_GATES flag still True per P3.41 6a03377).
Same Option 3 fix applies symmetrically to key_people_summary
(Contract 5d R-d gate portion).

Next: re-running run_persisted_system_run.py against NexGen draft
to see if the next contract fires further downstream, or if E2E
runs clean through to workbook generation.
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
