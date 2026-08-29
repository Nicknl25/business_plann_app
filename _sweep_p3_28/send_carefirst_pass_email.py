import os, smtplib, ssl
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()
host = os.getenv("EMAIL_HOST"); port = int(os.getenv("EMAIL_PORT") or 587)
user = os.getenv("EMAIL_USER"); pw = os.getenv("EMAIL_PASSWORD")
sender = os.getenv("EMAIL_FROM") or user
to = os.getenv("EMAIL_ALERTS_ADDRESS")

body = """P3.32 DRAFT 2 (CAREFIRST) GENUINE PASS - K4(b) DOCTRINE EMPIRICALLY DISPROVEN

Commit: 976488d phase_9_p3_32_draft_02_carefirst_genuine_pass_after_k1_f6
HEAD:   pushed to origin/intake-stable

DRAFT 2 (CareFirst Home Health Services) NOW PASSES V-1 THROUGH V-4.
This took FIVE prior fix iterations within K1 to land properly.

V-1 THROUGH V-4 VERIFICATION POST-F6
  V-1 Acceptance gate:   16/16 PASSED
                         Handler status: landed_verified_tool_call
                         Tool calls used: 5
  V-2 Model status:      OK (no fail-fast)
  V-3 FINMO trajectory:  built without error
  V-4 Reconciliation:    max_abs = 7.42 dollars (was 15362.83)
                         max_rel = 0.000036 (was 0.006880)
  Runtime:               204 seconds (was 460)

F6 RE-SYNC TRACE (REAL TIME EVIDENCE)
  payroll_state_resync trace:
    status: completed
    local_q1_payroll_before: 113678
    canonical_q1_payroll: 107440
    quarter_totals_mismatch_count: 20  (all 20 live quarters)
    applied_chain: apply_payroll_schedule_to_state

F6 detected the orchestrator stale local variable held a
schedule with Q1=113678 while the SQL canonical column had
the convergence runner output (Q1=107440). F6 saw the mismatch
on entry, called apply_payroll_schedule_to_state to re-apply
through the Mirror Flavor 1 apply chain, and the downstream
stages worked with canonical state.

ARCHITECTURAL FINDING — K4(b) DOCTRINE EMPIRICALLY DISPROVEN

Pre-F6 CareFirst was classified K4(b) genuinely infeasible at
intake — pre-revenue home health turnaround with Q5 NI margin
of -89% reaching Q11 NI margin of -40% was assumed structurally
impossible to bring positive by Q11.

K4(b) elimination in doctrine.md section 10.2 said: there is no
such thing as an infeasible plan from this system perspective.
If realism checks fail, the system hasnt found the path yet —
not the path doesnt exist.

This run empirically validates that doctrine correction.

WITHOUT touching any handler authority.
WITHOUT changing any contract or lever bounds.
WITHOUT adding any new handler.

JUST by closing the Payroll alignment leak (F6) so the handler
mini_finmo probes operate on canonical state — the handler
found a viable plan in 5 tool calls.

The 4-call best-effort failure pre-F6 was not because the path
didnt exist. It was because the path exploration was operating
on inconsistent state:
  - mini_finmo probe saw Payroll = 113678 / Q1 (local variable)
  - post-commit FINMO build saw Payroll = 107440 / Q1 (canonical)

GPT iterated against the wrong target. Once the target was
canonical, viability emerged in ONE extra call.

GENERALIZATION HYPOTHESIS
This pattern likely generalizes. Many of the K4 acceptance gate
failures in the P3.28 sweep (CareFirst, Elegant Threads 13/16,
Harborview 14/16) may resolve the same way — by canonical state
alignment unlocking handler convergence. The remaining sweep
will test this.

WORKBOOK ARTIFACTS PRESERVED
  docs/architecture/p3_32_sweep_workbooks/
    02_201d0ad1_CareFirst_FAIL_13_of_16.xlsx       (pre-F6)
    02_201d0ad1_CareFirst_GENUINE_PASS_postF6.xlsx (post-F6)

PROGRESS
  Draft 1 (Anderson & Blake)  - GENUINE_PASS (K1 cascade)
  Draft 2 (CareFirst)         - GENUINE_PASS (K1 F6 + run)
  Drafts 3-28                  - PENDING

NEXT
  Continue sweep with draft 3 (Skyward Express Airlines —
  previously GENUINE_PASS in P3.28; K1 F6 should not regress).
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = "[P3.32] Draft 2 (CareFirst) GENUINE PASS - K4(b) infeasibility doctrine empirically disproven"
msg["From"] = sender
msg["To"] = to

ctx = ssl.create_default_context()
with smtplib.SMTP(host, port) as s:
  s.starttls(context=ctx)
  s.login(user, pw)
  s.sendmail(sender, [to], msg.as_string())

print("Email sent.")
