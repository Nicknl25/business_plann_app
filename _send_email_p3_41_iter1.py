"""One-shot push notification email for P3.41 NexGen guarded loop iter 1 + STOP report."""
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

subject = "[P3.41 NexGen loop] Iter 1 pushed (4678159) + HALTED on iter 2 STOP (value_kind Literal)"
body = """\
P3.41 NexGen guarded autonomous fix loop -- 1 iter applied, then HALTED.

ITER 1 -- COMPLETE (clean PSL2):
  4678159 Contract 6 CascadeResolverPayload raw_confidence_tier
          -> Optional (R-d-raw, NexGen E2E iter 1)

  Universality verified: producer paths at
  post_intake_industry_baseline/lookup.py:299/:319/:483 emit
  raw_confidence_tier=None for ANY business hitting the no-coverage /
  generic-default / cohort-alternating fallback paths -- not
  NexGen-specific. Paired confidence_tier Literal stays pinned
  (resolves to "generic_default" on no-coverage). Test suite: 1327
  tests (+3 new), 11 pre-existing failures (no regressions).

ITER 2 -- HALTED on STOP CONDITION:
  Boundary: AMALGAMATED_SESSION -> MODEL_INPUT
  Field: sections.revenue.0.value_kind
  Error: "expected Input should be 'direct_number', 'ratio' or
          'day_count' (and 37 more error(s)), got 'count'"
  Contract: finmo_model_input_contract.py:122
            ValueKind = Literal["direct_number", "ratio", "day_count"]

  Why STOP (multiple triggers):
    1. Literal narrowing on enum vocabulary -- §0 territory. Adding
       'count' to the Literal is exactly the value-constraint
       relaxation the directive bans.
    2. 38 total error(s) suggests systematic mismatch, NOT an
       isolated row -- this is a vocabulary gap, not a None case.
    3. Contract docstring explicitly says (line 118-122) "Single
       enum across all row types -- per spec T4, the original
       directive's separate per-row-type value_kind enums did not
       match production." Prior analysis settled on 3 values; the
       universe of value_kind values is wider.
    4. post_intake_mapping.py:3314/3319/3331/3336 SQL CASE
       statements treat at least 9 value_kind values as known:
       'currency', 'quarter_currency', 'money', 'count', 'day_count',
       'integer', 'ratio', 'percentage', 'percent', 'rate',
       'interest_rate'. The contract's 3-value Literal is far
       narrower than the system's actual vocabulary.
    5. Could mask a category-2 bug: 'count' might be a real
       producer-side bug -- e.g., headcount rows being labeled
       'count' when they should be 'direct_number'. Need to
       investigate upstream producer (not just contract) before
       deciding.

  Nick decides direction. Options at a glance:
    (a) Widen the Literal (§0 violation -- not recommended without
        explicit policy waiver)
    (b) Find the upstream producer that emits 'count' and either
        rename or convert before the boundary (producer-side fix)
    (c) Investigate whether 'count' is a real bug

  Running log of fixes this session (across the full directive):
    6a03377 -- Intake-remediation gate circumvention (P3.41 prep)
    502ca89 -- Contract 5c target_market_summary -> Optional (R-d-bis)
    4678159 -- Contract 6 raw_confidence_tier -> Optional (R-d-raw)

  Each fix passed the universality test in producer-path terms:
    - 5c R-d-bis: intake_consult.py:10863 pops target_market_summary
      for any business persisted through the unified consult
    - 6 R-d-raw: lookup.py:299/:319/:483 emit raw_confidence_tier
      =None for any business hitting fallback paths

  None of the fixes were NexGen-specific accommodations -- all are
  universal contract corrections.

NEXT: awaiting Nick's call on the value_kind STOP before any further
contract change. NO autonomous action will be taken in the interim.
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
