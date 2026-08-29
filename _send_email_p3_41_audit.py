"""Push notification email for P3.41 round-1 set-tool boundary audit (doc-only)."""
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

subject = "[P3.41 NexGen loop] Round-1 set-tool boundary audit catalog pushed (79ac6ef, doc-only)"
body = """\
P3.41 round-1 set-tool boundary audit -- discovery complete.

  79ac6ef Round-1 set-tool boundary audit catalog (doc-only commit)

Catalog: docs/architecture/round1_set_tool_boundary_audit.md

INVENTORY:
  3 round-1 set-tools (set_capex_rd_balance_seed, set_stage_ramp_
  contract, set_payroll_schedule). set_drivers explicitly out of
  round-1 scope (per runner comment).

FINDINGS (7 total):
  - RESOLVED (already pushed in iters 6/7/7/8): 4
  - JUDGMENT (Nick adjudicates): 1
      F-J1 -- iter 9 stage_ramp operational branch ignores the
              q11_to_q20_min_net_income_margin_floor policy. Four
              options laid out (lift-only / use-policy-directly /
              unify-with-glide / policy-is-wrong) with tradeoffs.
              No recommendation made.
  - CLEAN ready for batch-fix: 2
      F-C1 -- stage_ramp envelope check reads util_max/util_floor
              but producer emits max_util (no util_floor). Dead
              check on every emission. Same name-mismatch shape
              as the iter-6 FINMO guard.
      F-C2 -- payroll envelope check has 2 dead subblocks
              (roles/wages + schedule) reading fields ZERO
              producers emit anywhere in python/. Recommend
              minimum delete-dead-code; field-renamed version
              would trend toward JUDGMENT.
  - REACHABILITY flags: 0

CLEAN sub-checks verified (no fix): 7 sub-checks across all 3
set-tools confirmed structurally aligned with their producers
(see catalog section 2.4).

The iter-8 ESCALATION flag (3 unaudited sibling envelope
functions) is now resolved at this layer: all 3 audited, 2 found
dead/partial (F-C1 + F-C2), 1 was already fixed in iters 7-8.

Next: Nick adjudicates F-J1 and confirms scope for F-C1 + F-C2;
a separate batch-fix directive lands the green-lit set with
regression tests, then re-run NexGen E2E to confirm the round-1
boundary is clean.

Session-cumulative push log (10 commits):
  6a03377  Intake-remediation gate circumvention
  502ca89  Contract 5c target_market_summary -> Optional
  4678159  Contract 6 raw_confidence_tier -> Optional (iter 1)
  fabdc4b  Contract 1 Literals + parity (iter 2)
  f168adf  Contract 1 R3 amendment (iter 3)
  66ecf40  Contract 1 ScheduleRow period-scope (iter 4)
  2cb2475  Contract 1 solver_input Optional (iter 5)
  7262a25  FINMO_SYNC guard names (iter 6)
  8d93950  Round-1 set-tool TypeError + NameError (iter 7)
  d904ce0  Round-1 envelope unit mismatch (iter 8)
  79ac6ef  Round-1 audit catalog (doc-only; this push)
"""

msg = MIMEText(body)
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to

with smtplib.SMTP(host, port) as server:
    server.starttls()
    server.login(user, password)
    server.send_message(msg)

print(f"Sent push-notification email to {to}")
