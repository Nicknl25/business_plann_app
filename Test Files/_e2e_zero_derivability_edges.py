"""CW-016 (z) zero-answer derivability - GUARD-EDGE suite.

The rule this suite enforces (Nick, 2026-08-07): every guard gets its
EDGES tested up front - zero and empty are the classic ones. The
Thursday derivability guards treated "zero"/"none" as underivable
(figures filter is f > 0), so a truthful $0 never landed: the Ironbridge
client answered zero SEVEN times (turns 81-95), falsified "$1 a month"
to escape (turn 97), and the $0 correction (turn 127) was ALSO dropped
by the corrections-path guard while the ack claimed success. The $12
phantom lease then killed the build at finalize (capital-lease Q12
closing=5).

Production data shape: fin_before is the REAL Ironbridge draft
financials_json loaded from the DB (the exact dict the production
caller passes); messages are the LIVE persona messages verbatim.

RED expectation (pre-fix): every zero-edge case FAILS (write dropped).
GREEN expectation (post-fix): zero-edge cases land; every negative
control still drops.
"""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

from api_handlers.intake_consult import (  # noqa: E402
    _guard_underivable_financials_writes,
    _guard_underivable_stage_writes,
)

DRAFT = "814c623e"

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST") or "localhost",
    user=os.getenv("MYSQL_USER") or "root",
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB") or "biz_plan_revert",
    autocommit=True,
)
cur = conn.cursor()
cur.execute(
    "SELECT financials_json FROM intake_consult_drafts WHERE draft_id LIKE %s",
    (DRAFT + "%",),
)
IRONBRIDGE_FIN = json.loads(cur.fetchone()[0])
conn.close()

# The pre-capture state at the lease stage: the draft dict WITHOUT
# initial_lease (production fin_before before the field ever landed).
FIN_PRE_LEASE = {k: v for k, v in IRONBRIDGE_FIN.items() if k != "initial_lease"}
# The correction-turn state: the draft dict exactly as stored ($1 placeholder).
FIN_WITH_DOLLAR = dict(IRONBRIDGE_FIN, initial_lease=1.0)

LEASE_ASK = (
    "Now let's capture any leased or rented equipment or space beyond your "
    "main rent. What monthly amount should we use for any leased equipment, "
    "vehicles, servers, or additional space you use?"
)

results = []


def check(label, ok):
    results.append((label, ok))
    print(("PASS " if ok else "FAIL ") + label)


def stage_zero_lands(message, last_assistant=LEASE_ASK, field="initial_lease"):
    """Router writes 0 for the field on this turn; does it survive the guard?"""
    after = dict(FIN_PRE_LEASE)
    after[field] = 0.0
    out = _guard_underivable_stage_writes(
        fin_before=dict(FIN_PRE_LEASE),
        fin_after=after,
        user_message=message,
        last_assistant=last_assistant,
    )
    return out.get(field) == 0.0


# --- ZERO EDGES: the seven live Ironbridge phrasings, verbatim -------------
check("live t81 'Zero on a standing basis...'", stage_zero_lands(
    "Zero on a standing basis. We rent a lift or a dumpster by the job but "
    "that goes into the job cost, not overhead."))
check("live t83 'Yes, zero.'", stage_zero_lands(
    "Yes, zero.",
    last_assistant="Got it, thanks-so for ongoing planning, should I just put "
    "$0 here for additional leased equipment or space beyond your main rent?"))
check("live t85 'Record zero...'", stage_zero_lands(
    "Record zero. There is no other leased equipment and no extra space. "
    "That's the third time you've asked me."))
check("live t89 '$0 per month.'", stage_zero_lands("$0 per month."))
check("live t91 'truly none'", stage_zero_lands(
    "Correct - there are truly none. Zero additional monthly leases. "
    "Please move on to the next question."))
check("live t95 bare '0'", stage_zero_lands("0"))

# --- ZERO EDGES: the classic phrasings the live run didn't use ------------
check("edge 'none'", stage_zero_lands("None."))
check("edge 'nothing'", stage_zero_lands("Nothing beyond the main rent."))
check("edge 'n/a'", stage_zero_lands("n/a"))
check("edge 'we don't have any'", stage_zero_lands(
    "We don't have any equipment leases."))
check("edge bare 'no' answer", stage_zero_lands("No."))
check("edge affirmation to $0 proposal", stage_zero_lands(
    "Yes, that's right.",
    last_assistant="Should I just put $0 here for additional leased "
    "equipment or space beyond your main rent?"))

# --- CORRECTIONS PATH: live turn 127, verbatim ----------------------------
after = dict(FIN_WITH_DOLLAR, initial_lease=0.0)
out = _guard_underivable_financials_writes(
    fin_before=dict(FIN_WITH_DOLLAR),
    fin_after=after,
    user_message=(
        "One more. The monthly lease commitment beyond main rent is recorded "
        "as $1. That was me trying to get past a question that kept repeating "
        "- the real figure is zero. Set the monthly lease commitment to $0."
    ),
)
check("live t127 corrections-path $1 -> $0", out.get("initial_lease") == 0.0)

# --- NEGATIVE CONTROLS: everything the guards exist to stop ---------------
# 1. CW-015 #2 shape: correction turn consumed as the pending stage's
#    answer writes a stage-default zero. No zero content -> must drop.
#    ("aren't" is negation-shaped but NOT a zero statement.)
check("NEG stage-default zero on correction turn still drops", not stage_zero_lands(
    "Hold on, go back a minute - I gave you a bad number earlier. The "
    "maintenance agreements aren't 4,000 a month, they're 4,300.",
    last_assistant="For direct costs - things like materials, supplies - a "
    "reasonable starting point is about 70% of revenue. Does that match?",
    field="cogs_percent_of_revenue_direct",
))
# 2. CW-015 #1 shape: router-authored estimate over "about twelve".
after = dict(FIN_PRE_LEASE)
after["marketing_total_year1"] = 15800.0
out = _guard_underivable_stage_writes(
    fin_before=dict(FIN_PRE_LEASE),
    fin_after=after,
    user_message="we're at about twelve",
    last_assistant="For marketing, a reasonable starting point is about 6% "
    "of revenue. Does that broadly match?",
)
check("NEG router estimate $15,800 over 'twelve' still drops",
      out.get("marketing_total_year1") != 15800.0)
# 3. Zero admission must admit ONLY zero: message says zero, router
#    writes an underivable nonzero -> drops.
after = dict(FIN_PRE_LEASE)
after["initial_lease"] = 500.0
out = _guard_underivable_stage_writes(
    fin_before=dict(FIN_PRE_LEASE),
    fin_after=after,
    user_message="Zero on a standing basis.",
    last_assistant=LEASE_ASK,
)
check("NEG nonzero write on a zero turn still drops",
      "initial_lease" not in out)
# 4. Corrections path: zero-shaped message must not unlock a nonzero
#    underivable rewrite of a different field.
after = dict(FIN_WITH_DOLLAR, current_revenue=9_500_000.0)
out = _guard_underivable_financials_writes(
    fin_before=dict(FIN_WITH_DOLLAR),
    fin_after=after,
    user_message="Set the monthly lease commitment to $0.",
)
check("NEG corrections nonzero rescale on zero turn still drops",
      out.get("current_revenue") == IRONBRIDGE_FIN["current_revenue"])
# 5. The ask mentions "$0" but the reply is a correction, not an
#    affirmation -> assistant-side zero must NOT unlock.
check("NEG assistant-$0 + non-affirmation reply still drops", not stage_zero_lands(
    "Actually the number I gave you for payroll was wrong, it should be "
    "higher.",
    last_assistant="Should I just put $0 here for additional leased "
    "equipment or space?",
))

fails = [l for l, ok in results if not ok]
print()
print(f"{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
