import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.32 V-4 VERIFIER TOOLING - COMMITTED + PUSHED

Commit: d6d0caa phase_9_p3_32_v4_workbook_verifier_tooling
HEAD: pushed to origin/intake-stable

L-4 LATITUDE INVOKED (tooling investment compounds across sweep).

WHAT WAS BUILT:
  Test Files/v4_workbook_verifier.py (270 LOC)

  Excel COM-based V-4 reconciliation verifier:
    1. Opens workbook via win32com Excel.Application
    2. CalculateFull() + Save() to populate cached formula values
    3. Reads "Persisted Baseline Reconciliation" rows from Checks
       sheet via openpyxl data_only=True
    4. Computes |delta| vs (ABS_TOLERANCE=$50, REL_TOLERANCE=0.01%)
       per directive thresholds
    5. Pass/fail per workbook + aggregate summary

  Pattern mirrors existing workbook_model_status.py.
  Graceful fallback when Excel COM unavailable.

BASELINE FINDING ON P3.28's 19 PRODUCED WORKBOOKS:

  17/19 PASS V-4 (typical max_abs < $20, max_rel < 0.01%)
   2/19 FAIL V-4:

     [KNOWN] CareFirst Home Health Services
       File: 201d0ad18ae243dba933703d19cda4df.xlsx
       max_abs=$48,235.49 (Cash Q20)
       P3.25 Mirror Flavor 1 — already documented.

     [NEW LATENT FALSE_PASS] Caring Hands Home Health Services
       File: 4207488106054d72afbe16480e1de100.xlsx
       max_abs=$44,929.05 (Cash Q20)
       Payroll diverges $2,809 Q20 -> Cash diverges $44,929 Q20.
       P3.28 reported this as GENUINE_PASS (run 8, 16/16 score,
       6 tool calls). V-2 inference from runner returncode +
       score was insufficient. V-4 recalc surfaces it instantly.

This single new finding validates the P3.28 §5 audit's #1
sequencing recommendation ("First — fix the workbook V-4
verifier; without it, every future sweep is blind to Pattern P1
regressions") and confirms P3.31 Leak A diagnosis (GPT
exhaustion handler is still authoring Payroll directly,
bypassing Handler C — same vector as CareFirst).

The V-4 verifier is now operational for every subsequent
sweep verdict. No more inferred GENUINE_PASS classifications.

NEXT STEPS PER DIRECTIVE:
  1. Apply K1 fix (F1+F2 commit 1): remove expenses::Payroll
     from GPT_AUTHORED_LEVER_IDS + restoration_loop mirror +
     handler prompt template. ~40 LOC.
  2. Apply K1 fix (F3+F4 commit 2): add expenses::Payroll to
     target-solver _CASH_PASS_OWNED_LEVER_IDS analog +
     annotate realism config primary_levers. ~50 LOC.
  3. Re-run V-4 against the regression set + start draft 1.
  4. Build K3 cash buffer repair handler (L-1, L-6 authorized)
     as drafts surface that pattern.

Sweep continues sequentially through 28 drafts.
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = "[P3.32] V-4 verifier tooling committed - latent CARE HANDS FALSE_PASS surfaced"
msg["From"] = sender
msg["To"] = to

ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent.")
