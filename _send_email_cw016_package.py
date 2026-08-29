"""One-shot push notification email for the CW-016 package commit."""
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

subject = "[CW-016] Zero-derivability blocker + lease tolerance + 4 correction fixes pushed (3049bca)"
body = """\
CW-016 package pushed to intake-stable.

  3049bca CW-016 package: zero derivability + lease rounding tolerance
          + 4 correction-path fixes

1. (z) BLOCKER (my own guard bug): honest "zero" answers were
   categorically underivable (figures filter f>0) - seven re-asks, the
   client falsified $1 to escape, the $0 correction dropped too.
   Explicit zero/negation now derives 0 on BOTH guards. 18/18 edge
   suite on the live Ironbridge messages verbatim, red->green.
2. Capital-lease term-end check: tolerance now DERIVED from rounding
   math (unit/2 x quarters + unit), never a flat constant - the $5
   residue that killed the Ironbridge plan is inside the bound (7 @
   Q12); a $20 genuine residue still fails. Exact failure reproduced
   red, green after.
3. (i2) post_gap<=1% => reconcile at any pre_gap - stated revenue can
   no longer be dragged to $11,228,731 by a repair that landed the
   model exactly ON the client's P&L. Propagate cases preserved.
4. (h) empty-request change-claim prose replaced by honest inability
   ack ("updating ... to $4,300" can no longer be said while nothing
   was written).
5. Ask-turn ack no longer renders "$0 (0%)" while its own clarifier is
   pending.
6. (g) stated-price triplet landing: "36 agreements at $4,300 a month
   is $1,857,600 a year" now lands price AND capacity deterministically
   on attempt 1 (relative near-price band; raw/effective counts).

Canary: Sunny_V3 full system run completed with workbook on this exact
code; finalize validation (incl. the new lease tolerance) clean.
Backend restarted on 3049bca, single :5050 listener verified.

Open: INTAKE_CONSTANTS_LEDGER audit (research-first, rulings before
any conversion) is in progress and will be reported for review.
"""

msg = MIMEText(body)
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to

with smtplib.SMTP(host, port) as s:
    s.starttls()
    s.login(user, password)
    s.sendmail(sender, [to], msg.as_string())
print("email sent to", to)
