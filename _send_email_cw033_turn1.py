"""Push notification email for CW-033 turn 1 (VS)."""
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

subject = "[CW-033 turn 1] A-113 retraction complied, A-115 fixed + live-proven, prove CLEAN - pushed (3e16e5e), awaiting mini"
body = """\
CW-033 turn 1 (VS) pushed to origin/intake-stable: 6911cb8, 123f532,
b438b0b, f020a34, 3e16e5e. STATUS -> awaiting-mini.

YOUR MID-TURN RETRACTION WAS SEEN AND COMPLIED WITH. The post-stage
capacity write path I had already built (and live-proven) is REMOVED:
a mid-interview ops-lever correction now gets zero writes and an
honest redirect leading the reply ("I haven't changed any operations
capacity from here - those numbers were set in the operations step"),
with the forward move suppressed so no fabricated receipt can ride
the same message. The reconcile-to-stated-revenue epsilon is reverted
(design, per your ruling); the anchor factor now stamps provenance
into the drivers (keep-or-drop is yours - one hunk).

KEPT AND FIXED, per the honesty exception (your TASK 3):
- A COGS rate can never type as a unit price; the price-retention
  gate cannot fire off a COGS correction, and the recovery
  restatement no longer self-triggers. Live-proven on the real
  Thornfield [75]/[77] turns.
- "Not recently, no" stores capex 0; the excluded 380k is a
  reference, the equipment base books once. Live-proven on [89].
- The ack contradiction (recorded-and-unrecorded in one message) is
  fixed at the note composer.

A-116 ADJUDICATED: ON-PATH, on the app's own written contract
(corrections-admitted block, INTAKE_FLOW_CONTRACT, the misroute
guard) - and it is already fixed and pinned (registry #115, gate legs
R02/R15). No new build owed.

BOARD CONFIRMED: A-115 top (now fixed, closes on artifact evidence),
then A-112 / A-106 / A-079 / A-103; CW-023 owner-pay is exactly
"unverified pending a completed build"; one orphan flagged
(owner_draw_ceiling, open/major, on nobody's list).

Discovery spec delivered for your review: docs/STREAM_DISCOVERY_SPEC.md
(discovery-not-upsell, end-of-ops, lands through the confidence gate;
five open questions inside).

Verification: full prove 61 legs / 54 behavioural / 0 DRIFT /
0 UNEARNED / CLEAN; Sunny_V3 canary green after every app edit (4);
live proof green on the post-retraction expectations. The first prove
caught my own refusal discipline recreating the CW-026 freeze on
single-row and row-less drafts - fixed, R01/I01 back to PROVEN.

Three rulings waiting on you (detail in HANDOFF TASK + VS_NOTES):
(a) does the retraction extend to the pre-existing CW-032/CW-017b
    landing doors for the same off-path family;
(b) keep or drop the anchor_reconcile provenance stamp;
(c) the standing naturalization-of-deterministic-receipts question.
"""

msg = MIMEText(body)
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to

with smtplib.SMTP(host, port) as s:
  s.starttls()
  s.login(user, password)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent to", to)
