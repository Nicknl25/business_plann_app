"""One-shot push notification email for P3.41 NexGen guarded loop iter 7 (real bug fixes)."""
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

subject = "[P3.41 NexGen loop] Iter 7 pushed (8d93950) -- 2 real round-1 set-tool defects fixed"
body = """\
P3.41 NexGen guarded autonomous fix loop -- iter 7 landed.

  8d93950 Round-1 set-tool fixes: maintenance-capex explicit kwargs
          (TypeError) + derive balance_sheet_seed contract-row
          whitelist from schema (NameError); surfaced by NexGen E2E

Two real Python defects at the round-1 amalgamated set-tool boundary.
Both pre-existing latent bugs in never-clean-E2E code; iters 1-6
unblocked the path through to this stage where they finally fired.

BUG 1 -- TypeError. _maintenance_capex was spreading **builder_inputs
(6 keys) into a callee with only 4 keyword-only params (no
model_input_json acceptance). Fixed to explicit kwargs matching the
R&D sibling's working pattern.

  Audit (per directive): grep -rnE '**builder_inputs' across python/
  returns ONLY this single site. No other set-tool builders affected.

BUG 2 -- NameError. _BALANCE_SHEET_SEED_CONTRACT_ROW_FIELDS was
referenced in _slim_balance_sheet_seed_proposal_for_contract but
never defined anywhere in the codebase. Fixed by deriving the
whitelist from the authoritative balance_sheet_contextual_seed
contract schema via a new _balance_sheet_seed_contract_row_fields()
helper (cached at function-attribute level). Derived field set:
{applicable, lever_id, rationale, seed_value, value_kind} -- the
4 metadata fields (naics_provenance, decision_source, naics_6,
source_of_truth) are correctly excluded.

Single-source-of-truth pattern: the whitelist cannot drift from the
contract (same lesson as the seed-parity guard).

Test suite: 1338 tests (+5 new regression tests), 11 pre-existing
failures (no regressions).

Running loop log (session-cumulative):
  6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
  502ca89 -- Contract 5c target_market_summary -> Optional (R-d-bis)
  4678159 -- Contract 6 raw_confidence_tier -> Optional (R-d-raw, iter 1)
  fabdc4b -- Contract 1 value_kind/input_semantics Literals + parity (iter 2)
  f168adf -- Contract 1 R3 amendment, 3 row blobs (iter 3)
  66ecf40 -- Contract 1 ScheduleRow period-scope fields (iter 4)
  2cb2475 -- Contract 1 top-level solver_input Optional (iter 5)
  7262a25 -- Dead FINMO_SYNC guard names corrected (iter 6)
  8d93950 -- Round-1 set-tool TypeError + NameError fixes (iter 7)

Next: restart backend + re-run run_persisted_system_run.py against
the NexGen draft to see what surfaces next.
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
