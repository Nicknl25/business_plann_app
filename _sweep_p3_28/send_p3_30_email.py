import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.30 SOURCE-OF-TRUTH DUALITY AUDIT - COMPLETE

Memo: docs/architecture/p3_30_source_of_truth_duality_audit.md
HEAD: 9b7c445 (pushed to origin/intake-stable)

Per P3.30 directive: Options A/B/C from P3.29 explicitly
rejected. This memo identifies which dualities are structural
(eliminate redundancy or make derived) vs engine-level (Excel
vs Python algebra on shared inputs).

HEADLINE:
- ONE JSON-level duality exists: Payroll (Type 2 derived view
  across 3 surfaces).
  * S1 payroll_headcount.rows (canonical detail)
  * S2 payroll_headcount.quarter_totals.payroll (aggregate)
  * S3 model_input.expenses.Payroll.values (model-input copy)
  GPT exhaustion handler can write S3 directly without touching
  S1/S2 (expenses::Payroll is in GPT_AUTHORED_LEVER_IDS at
  handler.py:54). CareFirst P3.25 mechanic: S3 = 107,440
  (handler-written), S1 still = 142,725 (Handler C's prior
  number). Validator reads finmo_json built from S3; workbook
  reads SUMIFS over S1; divergence ships.

- Every OTHER FINMO line is Type 3 (same JSON source, two
  engines compute it). Excel formula vs Python
  calculate_finmo_model. Divergence vectors here are
  implementation discipline: rounding, MIN/MAX clamping,
  derived-driver-policy normalization. Not architectural
  duality.

AUDIT SOURCE TIMING: confirmed sound. Audit Source numbers and
FINMO formulas both frozen into the workbook in the same
synchronous build pass. No in-pipeline window where finmo_json
could change between writes. CareFirst is NOT a timing issue;
it is a write-state inconsistency BEFORE workbook generation.

STRUCTURAL FIX SEQUENCE (PROPOSED, NO CODE CHANGES):

1. NOW: Remove expenses::Payroll from GPT_AUTHORED_LEVER_IDS
   (handler.py:54). ~5 LOC. Closes active vector immediately.

2. NEXT: Make S3 a derive-on-read view by honoring
   derived_driver flag in every model_input writer; derive S2
   from S1 on read so S1 is the only persistable write surface
   for payroll dollars. ~80 LOC. Eliminates structural vector
   permanently. Risk: Medium (need to audit every apply_*
   writer to respect derived_driver).

3. THEN (optional Tier 3): Per-line Excel/Python formula
   alignment + persist normalized model_input_json instead of
   un-normalized form. ~30 LOC per line, ~25 lines. Closes
   engine-duality vectors (Pinnacle 3 ppb class).

DOCTRINE QUESTION FOR USER:
finmo_json column persists Python's output (rounded + with
derived_driver_policies applied). model_input_json column
persists the un-normalized form the workbook reads. If we
persist the NORMALIZED model_input_json, all engine-duality
vectors collapse to "Excel formula tolerance" without adopting
Option A. ~40 LOC follow-on. Worth considering before/with
step 3.

User direction required for step 1/2/3 sequencing.
"""

msg = MIMEText(body)
msg["Subject"] = "P3.30 duality audit: only Payroll is structural; everything else is engine-discipline"
msg["From"] = sender
msg["To"] = to
ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())
print("email sent to", to)
