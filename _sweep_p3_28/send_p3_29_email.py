import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.29 WORKBOOK GENERATION AUDIT - COMPLETE

Memo: docs/architecture/p3_29_workbook_generation_audit.md
HEAD: ab8e675 (pushed to origin/intake-stable)

Headline:
TIMING IS SOUND. Single workbook render at end of pipeline,
reads finalized state from persisted draft row
(intake_consult.py:7615-7623). No piecemeal sheet writes.

INPUT LINEAGE IS VULNERABLE. The FINMO sheet is formula-rebuilt
from Model Inputs sheet, which is formula-rebuilt from schedule
sheets, which are built from model_input_json + payroll_headcount
+ debt_schedule. These JSON sources are INDEPENDENT of
finmo_json (what the validator consumed). Anywhere they
disagree, FINMO and Audit Source diverge.

The Audit Source sheet (hidden) renders finmo_json hardcoded
values. The Checks sheet baseline rows compare FINMO vs Audit
Source and emit 'CHANGED' (informational, does NOT fail Model
Status). The duality is BY DESIGN - post-delivery editing
workflow - but the same architecture lets upstream Pattern P1
bugs ship on day 1, silently labeled CHANGED.

CareFirst P3.25 is the canonical example:
  Chain A (validator/Audit Source): Payroll Q1 = 107,440
  Chain B (workbook FINMO):         Payroll Q1 = 142,725
  Q11 EBITDA: validator +4,835 vs FINMO ~-32,599
Model Status: OK (16/16). User opens workbook: catastrophe.

7 divergence vectors (V-1 through V-7) cataloged in Q4.

Three structural fix options proposed (Q5):
  A. Hardcode FINMO to finmo_json (eliminate duality, ~500 LOC)
  B. Enforce Chain A == Chain B at persist time via assertion
     extension (~50-150 LOC per surface)
  C. FINMO renders finmo_json directly; schedule sheets keep
     edit-driven flow (~250 LOC; hybrid)

Doctrine question gates the choice:
  'Is the post-delivery editing workflow load-bearing?'
  If YES: Options B or C only.
  If NO:  Option A delivers the deterministic guarantee.

Immediate cheap win (already in P3.28 audit Section 6):
  Remove expenses::Payroll from GPT_AUTHORED_LEVER_IDS
  (handler.py:54). ~20 LOC, Low risk. Closes V-1 today.

User direction required.
"""

msg = MIMEText(body)
msg["Subject"] = "P3.29 workbook audit: timing sound, lineage vulnerable to Mirror Flavor 1"
msg["From"] = sender
msg["To"] = to
ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())
print("email sent to", to)
