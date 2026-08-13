"""One-shot push notification email for P3.41 NexGen guarded loop iter 2."""
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

subject = "[P3.41 NexGen loop] Iter 2 pushed (fabdc4b) -- Literal completion + seed-parity guard"
body = """\
P3.41 NexGen guarded loop -- Iter 2 pushed.

  fabdc4b Contract 1 value_kind/input_semantics Literals -- complete
          pass-through vocabulary + seed-parity guard (surfaced by
          NexGen E2E iter 2)

Different fix mechanism than the prior Optional flips: this CORRECTS
an incompletely-scoped Literal (not a §0 loosening). The original
Contract 1 trace (spec T4) read only finmo_bridge's hardcoded
fallback returns and missed the producer's PASS-THROUGH path that
returns the mapping table's value_kind / input_semantics VERBATIM.

INVENTORY:
  Pass-through Literals corrected (5):
    ValueKind, RevenueInputSemantics, ExpenseInputSemantics,
    BalanceSheetInputSemantics, ScheduleInputSemantics
  Closed producer-only Literals left untouched:
    ContractVersion, CanonicalLeverVocabulary, named_range,
    RevenueRow.driver

EXTRACTED VOCABULARY (live DB + finmo_bridge):
  ValueKind UNION: count, currency, day_count, quarter_currency,
                   ratio, direct_number (6 values, was 3)
  Per-section input_semantics: 5-7 values each (was 4-7)

SEED-PARITY GUARD (THE KEY PIECE):
  tests/test_p3_40_contract_1_seed_parity.py -- 6 tests.
  DB-half queries live post_intak_mapping_lookup and asserts seed
  subset of Literal (graceful skip on no MySQL).
  Source-parse half regex-scans finmo_bridge:255-322 and asserts
  fallback subset of per-section Literal.
  CI fails LOUDLY with the missing values named, instead of silently
  breaking on a future E2E run when the seed gains a new value.

NOT changed (universality + §0 discipline):
  - §0 sub-contracts (5b/c/d) stay bare-str (free-varying business
    content -- different policy by design)
  - Producer code (correct; contract was incomplete)
  - _PERCENT_INPUT_SEMANTICS frozenset (separate behavior question,
    noted in commit summary)
  - driver Literal (hardcoded by template, not pass-through)

Test suite: 1333 tests (+6 new), 11 pre-existing failures (no
regressions). Existing fixtures use values already in the completed
Literals -- nothing to flip.

Running log of fixes this session (full directive):
  6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
  502ca89 -- Contract 5c target_market_summary -> Optional (R-d-bis)
  4678159 -- Contract 6 raw_confidence_tier -> Optional (R-d-raw)
  fabdc4b -- Contract 1 ValueKind + per-section input_semantics
              Literal completion + seed-parity guard (R-pt-vocab)

NEXT: re-running run_persisted_system_run.py against the NexGen
draft. Continuing the guarded loop per protocol.
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
