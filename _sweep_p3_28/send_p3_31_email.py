import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.31 HANDLER FIELD OWNERSHIP AUDIT - COMPLETE

Memo: docs/architecture/p3_31_handler_field_ownership_audit.md
HEAD: 3606753 (pushed to origin/intake-stable)

HEADLINE: Leak landscape is narrow and concentrated on ONE
field (expenses::Payroll), with TWO unauthorized writers.

LEAK A - GPT exhaustion handler's GPT_AUTHORED_LEVER_IDS
         includes 'expenses::Payroll' (handler.py:54).
         This is the active P3.25 CareFirst vector.

LEAK B - Restoration target-solver writes whatever lever_id
         appears in failing realism rows' primary_levers.
         Multiple realism rows list expenses::Payroll
         (lookup.py:544, 605, 1005, 1116). Solver bypasses
         Handler C deterministically.

EVERY OTHER HANDLER HAS CLEAN AUTHORITY:
  - Stage ramp handler: stage_ramp_contract.* (16 fields)
  - Funding handler: 5 funding levers (debt + equity + distributions)
  - Handler C: payroll_headcount.* + apply chain
  - Cash strategy proposer: SHARED with funding handler
    (Python-first / handler-on-failure pattern, intentional)

ALREADY-FENCED:
  - Convergence runner: filtered via _extract_controller_lever_
    catalog (excludes expenses::Payroll at line 5498,5509)
  - Target-solver excludes _CASH_PASS_OWNED_LEVER_IDS (6
    funding/cash levers)

ROUTING MECHANISM: P3.26 Commit 2's route_payroll_feasibility_
to_handler_c is the canonical shape. Closing the leaks needs
the same primitive wired at restoration-exhaustion + handler-
exhaustion call sites. No new mechanism needed.

PROPOSED FIX SEQUENCE (NO CODE CHANGES IN THIS ITER):

  F1+F2  (~40 LOC, Low risk)  Commit 1
    Remove 'expenses::Payroll' from GPT_AUTHORED_LEVER_IDS
    + _DRIVER_KEY_TO_LEVER_ID + restoration_loop.py mirror
    + prompt template. Closes Leak A.

  F3+F4  (~50 LOC, Low risk)  Commit 2
    Add 'expenses::Payroll' to target-solver exclusion
    frozenset (mirror of _CASH_PASS_OWNED_LEVER_IDS shape)
    + annotate realism primary_levers entries that reference
    payroll. Closes Leak B.

  F5     (~50 LOC, Med risk)  Commit 3 (conditional)
    Wire restoration-exhaustion to Handler C when failing
    metrics include payroll-touching primary_levers. Only
    needed if F1-F4 leave residual cases. Worth running
    F1-F4 first and observing the sweep before deciding.

  F6     (~2 LOC, no risk)    Trivial, any time
    Update doctrine §6 to match code reality (8 PNL levers
    not 12).

TOTAL ~140 LOC across 2-3 commits.

RECOMMENDATION: NO GOVERNOR. Two leaks on one field do not
justify a centralized catalog-enforcement layer. Per-handler
catalog tightening is the cleaner shape. If a future audit
surfaces 5+ leak fields across 3+ handlers, governor case
grows; today it does not.

User direction required for F1-F5 sequencing.
"""

msg = MIMEText(body)
msg["Subject"] = "P3.31 handler ownership audit: narrow leak (Payroll only); ~140 LOC fix"
msg["From"] = sender
msg["To"] = to
ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())
print("email sent to", to)
