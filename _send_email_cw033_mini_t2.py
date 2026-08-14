"""Push notification email for CW-033 turn 2 (mini's artifact audit)."""
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

subject = ("[CW-033 mini audit] A-115a/b HOLD, prove CLEAN - but 3 live "
           "defects found; STATUS -> awaiting-VS")
body = """\
mini's artifact audit of CW-033 turn 1 is pushed to origin/intake-stable.
STATUS -> awaiting-VS.

WHAT HELD (proven live with my own wordings, rows read not replies):
- The 58% cost-rate class is fixed for real: no price write, no
  retention stamp, the rate lands only as the client's declared shared
  cost group. Your [77] "no prices moved" restatement is also safe now.
- The capex "not recently, no" fix holds: $0 stored, the 380k excluded
  everywhere, and "no wait, it was 380,000" still lands.
- Wall corrections land cleanly (install 7 jobs/week, both stored
  fields agree - the old evaporation is gone).
- The provenance stamp on revenue drivers is confirmed decoration-only:
  nothing reads it, it cannot change any number. Keeping it is safe.
- The full gate prove is CLEAN: 61 legs, zero drift, zero unearned.

WHAT I FOUND (three real defects, all handed to VS with fix shapes):
1. THE BIG ONE: one reply told the client "I haven't changed any
   operations price" and then, in the same breath, "Got it - I'll
   update the hard goods ticket price to 99" - plus notes about rent
   and operating-cost changes the client never mentioned, and "Also
   recorded:" over three figures that were not written that turn.
   Nothing was actually written; the numbers on file are right. But the
   words lie. This is the same words-vs-state class this whole campaign
   exists to kill, on a reply path the earlier fixes never covered.
2. The new "redirect instead of write" guard can be slipped: say
   "we can do 7 jobs a week" WITHOUT the word "capacity" and the
   correction lands mid-interview anyway - the exact thing your
   retraction said should be prevented. Fix goes at the write door.
3. A client who says "40 a week" on a business measured monthly gets
   40-a-MONTH stored (reads back as 9.23 a week) while the receipt says
   "capacity 40". Wrong number, invisible to the client.

Also confirmed live: "none of it this year - but we did spend 15,000 on
a mower" loses the mower (stored $0). Fix shape ruled and handed over.

Registry housekeeping done per your revision: the retracted A-113
"never lands" row is closed with your ruling in the note; the "ack
claims a write that didn't happen" row STAYS OPEN because defect 1
above is exactly that class, alive today.

Nothing for you to do; VS has the four fixes next turn.
Full report: _mini_cw033_t1_audit_20260814.txt
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
