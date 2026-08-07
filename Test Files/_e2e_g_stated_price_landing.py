"""CW-016 (g) stated-price triplet landing - targeted RED/GREEN.

Live turns 121-123: the client's price correction ("The model still has
those agreements at $4,000 a month. It's $4,300. Thirty-six active
agreements at $4,300 a month is $1,857,600 a year") drew an
acknowledgement but the router emitted NO ops write, and the no-touch
capacity landing could never fit it - it only tries the STORED (stale)
price. Took three attempts live.

Production data shape: ops_json is the REAL Ironbridge draft
operating_model_json from the DB, with the maintenance price reset to
its pre-correction $4,000; the message is live turn 121 verbatim.
RED (pre-fix): nothing lands. GREEN: maintenance price -> 4300 and
capacity -> 45 (= 36 effective / 0.8 util), stream $1,857,600; the
$385,000 projects product untouched.
"""
import copy
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

from api_handlers.intake_consult import _reconcile_driver_correction  # noqa: E402

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST") or "localhost",
    user=os.getenv("MYSQL_USER") or "root",
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB") or "biz_plan_revert",
    autocommit=True,
)
cur = conn.cursor()
cur.execute(
    "SELECT operating_model_json FROM intake_consult_drafts WHERE draft_id LIKE %s",
    ("814c623e%",),
)
OPS_FINAL = json.loads(cur.fetchone()[0])
conn.close()

# Pre-correction state: the stale $4,000 price the live run was stuck on.
OPS_STALE = copy.deepcopy(OPS_FINAL)
OPS_STALE["lob_models"][1]["products"][0]["unit_price"] = 4000

T121 = (
    "Before I submit - the maintenance price correction I gave you earlier "
    "never took. The model still has those agreements at $4,000 a month. "
    "It's $4,300. Thirty-six active agreements at $4,300 a month is "
    "$1,857,600 a year, and with the project side at $9,240,000 that's how "
    "I get to my revenue."
)

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# The live no-touch shape: router emitted no ops write (after == before).
ops_after, note = _reconcile_driver_correction(
    ops_before=copy.deepcopy(OPS_STALE),
    ops_after=copy.deepcopy(OPS_STALE),
    user_message=T121,
)
maint = ops_after["lob_models"][1]["products"][0]
proj = ops_after["lob_models"][0]["products"][0]
check("t121 lands maintenance unit_price 4300", maint.get("unit_price") == 4300.0)
check("t121 lands capacity 45 (36 effective / 0.8 util)",
      abs(float(maint.get("units_per_period_capacity") or 0) - 45.0) < 1e-6)
check("t121 stream matches client arithmetic $1,857,600",
      abs(4300.0 * float(maint["units_per_period_capacity"]) * 12 * 0.8 - 1_857_600.0) < 1.0)
check("projects product untouched ($385,000 / cap 32)",
      proj.get("unit_price") == 385000 and proj.get("units_per_period_capacity") == 32)
check("stream_note narrates dollars",
      isinstance(note, dict) and "$1,857,600" in str(note.get("stream_note") or ""))

# NEGATIVE: an unrelated financial answer with figures must land nothing.
ops_after2, note2 = _reconcile_driver_correction(
    ops_before=copy.deepcopy(OPS_STALE),
    ops_after=copy.deepcopy(OPS_STALE),
    user_message=(
        "The other fifteen run about $988,000 a year in wages - two "
        "superintendents, three PMs, the carpentry and drywall crews and the "
        "bookkeeper. So all in with the three of us, payroll's right at "
        "$1,450,000."
    ),
)
check("NEG payroll answer lands nothing",
      ops_after2 == OPS_STALE and note2 is None)

# NEGATIVE: a no-figure turn is untouched.
ops_after3, note3 = _reconcile_driver_correction(
    ops_before=copy.deepcopy(OPS_STALE),
    ops_after=copy.deepcopy(OPS_STALE),
    user_message="What's next?",
)
check("NEG no-figure turn lands nothing", ops_after3 == OPS_STALE and note3 is None)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
