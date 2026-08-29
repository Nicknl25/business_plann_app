import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv("C:/dev/business_plann_app/.env")

body = """CW-024 slate pushed: 7b9f481..582cef7 (intake-stable)

All 9 items in prevention shapes + red-proof suite:
- Correction doors (total_team_payroll / remove_role) + fold + receipt
- Group-of-N person rows unrepresentable (dedupe vs rest-of-team)
- Retention answer consumer (30/34 overrides 0.80 default)
- Acceptance-mismatch hold; park needs explicit stop-intent
- Fallback COGS = fitted band (bandless proposal deleted)
- Price ceiling = durable market fact in dollars (acceptance never moves it)
- Volume options capped at 100% of stored capacity
- Client-copy pass + forbidden-vocabulary lint; #89/#95 receipt fixes
- Stage-flow prose-kill: the actual turn-38 chain (answer_readonly prose
  claiming a write that never happened) is now unrepresentable

Verification per the red-proof standard:
- _redproof_cw024_slate.py: 0/13 on 7b9f481 (stash), 13/13 on the slate
- _lint_client_copy.py: 23 hits on baseline, 0 after
- Regressions: recalc 18/18, run-entry 5/5, walls 11/11, cause-split
  10/10, demand judge 11/11, fitted COGS 10/10

Next: backend restart + Sunny_V3 canary, then the Cedar Ridge corrected
re-run and the posture/framing research report.
"""

host = os.environ["EMAIL_HOST"]
port = int(os.environ.get("EMAIL_PORT", "587"))
user = os.environ["EMAIL_USER"]
pw = os.environ["EMAIL_PASSWORD"]
to = os.environ["EMAIL_ALERTS_ADDRESS"]

msg = MIMEText(body)
msg["Subject"] = "PUSH: CW-024 slate (all 9, prevention) + red-proofs 13/13 - 582cef7"
msg["From"] = user
msg["To"] = to

with smtplib.SMTP(host, port) as s:
    s.starttls()
    s.login(user, pw)
    s.sendmail(user, [to], msg.as_string())
print("email sent to", to)
