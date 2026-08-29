"""One-shot push notification email — Fix #1 cascade landing MVP scope."""
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

subject = "[Fix #1] Cascade landing MVP scope pushed (162721d)"
body = """\
Pushed to origin/intake-stable:
  162721d Fix #1: cascade landing MVP scope + executive load boundary scope

Documentation-only commit (scope notes, no code). 2 files:
  - docs/architecture/fix_1_cascade_landing_mvp_scope.md (new)
  - docs/architecture/fix_1_executive_load_boundary_scope.md

Scope note maps the adaptation cascade + specs the Sunny MVP:

  1. Two loops in series. The amalgamated restructure cascade
     (post_intake_amalgamated/protocol/) is built + LIVE
     (runner.py:1865). The post-cascade completion
     (post_intake_solver/orchestrator.py) is a gate/finalize
     pass that runs after -- and is where Sunny dies.

  2. Judge seam degrades, not deleted. responder.py is fully
     wired; "GPT pulled" == synthetic-veto-to-floor when no
     OPENAI_API_KEY (responder.py:468-469). SessionDriver has
     NO non_viable terminal state -- it always floors a plan.

  3. Death point: finalize solver_target_residual hard-fail
     (finalize_post_intake.py:858), re-raised under
     CONVERGENCE_TEST_MODE (orchestrator.py:3608-3609). The
     realism gate is caught/advisory, not fatal.

  4. KEY ANSWER: landing Sunny's non_viable verdict is
     DETERMINISTIC Python, not GPT. The standard already
     computes non_viable (standard.py:100-101) + is wired
     advisory at acceptance (gate.py:790-802). MVP = reframe
     the one finalize assert into a committed low-confidence
     landing + stamp cascade_landed_tier/plan_confidence.
     GPT judgment (confirm/veto/choose) is the full executive,
     deferred -- irrelevant to a business non-viable by physics.

Only docs committed; local scratch (logs, _send_email iters,
_l4_batch, _sweep dirs, run_api scripts) left untracked per
your call.

Shutting down for the night.
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
