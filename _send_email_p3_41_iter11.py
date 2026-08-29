"""One-shot push notification email for P3.41 NexGen guarded loop iter 11."""
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

subject = "[P3.41 NexGen loop] Iter 11 pushed (1ff58a6) -- payroll stub decoupled from legacy gate"
body = """\
P3.41 round-1 payroll-stub decoupling landed (option 3).

  1ff58a6 Round-1 payroll stub: decouple set_payroll_schedule from
          the legacy sequence-controller gate (option 3); shared
          ungated stub helper; gate preserved for legacy callers
          -- NexGen E2E iter 11

Doctrine-aligned fix. The legacy sequence-controller gate stays on
the shim (estimate_payroll_headcount_schedule_with_gpt) for its
legacy controller callers; the canonical amalgamated round-1 entry
(set_payroll_schedule(contract=None)) now reaches the same stub via
a shared ungated helper.

Changes:
  - lookup.py: NEW build_pending_payroll_stub() helper (single source
    of the stub shape + metadata stamps; ungated).
  - schedule.py: shim keeps its gate; body delegates to the helper.
  - set_payroll_schedule.py: round-1 path calls the helper directly
    when no test seam supplied.

LATENT BUG NOTED (NOT fixed): the original shim used .setdefault()
for decision_source / contract_version stamps, but the underlying
build_empty_payroll_headcount_payload already sets both to other
values -- so those stamps were no-ops in the original code. The
"amalgamated_session_pending" label the docstring describes was
never actually applied. Faithful single-source extraction preserves
that quirk; tightening to direct-assignment semantics is a separate
disposition for Nick.

Tests: 6 new in tests/test_p3_41_payroll_stub_iter11.py covering
helper-runs-ungated / metadata-threading / structural-shape /
canonical-entry-no-longer-blocked / shim-gate-preserved / parity.

Test suite: 1365 tests (+6 new), 10 pre-existing failures (one
pre-existing error in test_p3_40_contract_1_adapter resolved as a
side effect of unrelated module reloads; baseline no-worse).

Heads-up: we're now in the P3.33 amalgamation transition layer. The
real payroll authoring is at step 5 (amalgamated session, not yet
built). Next STOP may be a transition seam rather than a latent bug.
If we hit a deeper "amalgamated session isn't built out enough"
wall, that's a different kind of decision than the loop has hit so
far -- will report it that way if it surfaces.

Running loop log (session-cumulative, 12 commits):
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
  79ac6ef  Round-1 audit catalog (doc-only)
  3279f49  Round-1 audit batch F-J1+F-C1+F-C2 (iter 10)
  1ff58a6  Payroll stub decoupling (iter 11, this push)

Next: restart backend + re-run NexGen E2E.
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
