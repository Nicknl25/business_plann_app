"""One-shot push notification email for P3.41 NexGen guarded loop iter 6 (guard fix)."""
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

subject = "[P3.41 NexGen loop] Iter 6 pushed (7262a25) -- dead FINMO_SYNC guard names corrected"
body = """\
P3.41 NexGen guarded autonomous fix loop -- iter 6 landed.

  7262a25 FINMO_SYNC postcondition guard -- correct required-columns
          to producer names (quarter_index/ebitda/ending_cash);
          surfaced by NexGen E2E

Not a contract change. Not a producer change. Guard column-name
correction in post_intake_initial_grid/runner.py.

Root cause: the FAIL_FINMO_SCHEMA_MISSING guard was wired in commit
3ff70c8 with required-columns names that never matched producer
output. The guard was dead -- would have failed every clean run;
never fired before because no E2E reached FINMO_SYNC cleanly until
the contract-layer iters 1-5 unblocked the path.

  Required (pre-fix): {period, revenue, gross_profit, op_income, cash_end}
  Required (post-fix): {quarter_index, revenue, gross_profit, ebitda, ending_cash}

  - period      -> quarter_index   (canonical integer period index)
  - op_income   -> ebitda          (engine's operating-profitability line;
                                    no EBIT field exists in the engine)
  - cash_end    -> ending_cash     (engine's cash-waterfall result)
  - revenue, gross_profit unchanged (already matched)

Verified: period/op_income/cash_end appear ZERO times as producer keys
anywhere in python/ (grep + runtime dump on NexGen first row -- 75
keys total, none of those 3 present). Inventory doc
(p3_33_phase35_fail_fast_inventory.md item 17) updated in lockstep.

Strengthening, not loosening: post-fix the guard will actually catch
an empty/malformed FINMO build (its original intent) instead of
always-failing on the wrong keys.

Test suite: 1333 tests, 11 pre-existing failures (no regressions).

Running loop log (session-cumulative):
  6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
  502ca89 -- Contract 5c target_market_summary -> Optional (R-d-bis)
  4678159 -- Contract 6 raw_confidence_tier -> Optional (R-d-raw, iter 1)
  fabdc4b -- Contract 1 value_kind/input_semantics Literals + parity (iter 2)
  f168adf -- Contract 1 R3 amendment, 3 row blobs (iter 3)
  66ecf40 -- Contract 1 ScheduleRow period-scope fields (iter 4)
  2cb2475 -- Contract 1 top-level solver_input Optional (iter 5)
  7262a25 -- FINMO_SYNC guard column-name correction (iter 6)

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
