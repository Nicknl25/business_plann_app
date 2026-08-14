"""Push notification email for CW-033 turn 3 (VS)."""
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

subject = ("[CW-033 turn 3] mini's four fixes landed (M1/M2/M3 + capex "
           "carve-out), live-proven, canary clean, prove CLEAN - pushed "
           "(02effe1 + flip), awaiting mini")
body = """\
CW-033 turn 3 (VS) pushed to origin/intake-stable: 02effe1 (the four
fixes + instruments) plus the STATUS-flip commit.
STATUS -> awaiting-mini.

ALL FOUR OF MINI'S FIXES ARE LANDED AND LIVE-PROVEN:

M1 - the interview reply speaks only from the receipt. Your A4b turn
now reads: the honest redirect, "Got it.", and the rent question.
The fabricated "I'll update ... to 99" ack, the phantom rent /
other-operating-costs notes, and the false "Also recorded:" of three
on-file values are all structurally gone (four emitting layers, each
fixed at its own gate).

M2 - the ops boundary now lives at the WRITE DOOR. "7 jobs a week"
with no lever keyword gets the redirect mid-interview and writes
nothing; the wall landing (7/7) is untouched.

M3 - a stated cadence is never silently re-based. "40 a week, not 34"
on Sumac's contract row now stores 173.33/period with the week twin
reading exactly 40, and the receipt says "capacity 40 a week (about
173.3 per operating period as this line is modeled)". Ambiguous
cadences ask instead of guessing.

CAPEX - "none of it this year - but we did spend 15,000 on a mower"
now stores 15,000; the excluded 380,000 lands nowhere; a plain no
still stores 0.

Proof: pre-fix RED on exactly the fix checks, 24/24 green after, four
ablations each red on its own checks alone, live W1-W5b green on a
server postdating every edit. Sunny_V3 canary: system_run_complete,
484s, zero errors, workbook delivered (delivery record #22 bound by
draft_id). Full prove: 61 legs - 54 behavioural, 5 structural-absence,
2 golden, 0 DRIFT, 0 UNEARNED, CLEAN (table identical to mini's, no
leg regressed).

Nothing needs your hands - mini audits next.
"""

msg = MIMEText(body)
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to

with smtplib.SMTP(host, port) as s:
    s.starttls()
    s.login(user, password)
    s.sendmail(sender, [to], msg.as_string())
print("sent to", to)
