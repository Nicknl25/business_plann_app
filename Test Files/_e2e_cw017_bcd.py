"""CW-017 (b)(c)(d) - targeted suites on the live Vanguard shapes.

(c) ops-side derivability guard: the 196 leak (280 x 0.70 echoed into
    product 2's capture) drops as underivable; every stated capture
    survives, replayed verbatim.
(b) cross-section correction routing: the mid-financials utilization
    correction that was refused three times live now lands through the
    consequence contract; non-corrections and ambiguous references
    don't fire.
(d) cadence-aware capacity ack labels: "weekly capacity" no longer
    claimed for a 1-period/year product.
"""
import copy
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

from api_handlers.intake_consult import (  # noqa: E402
    _apply_cross_section_driver_correction,
    _guard_underivable_ops_lever_writes,
)
from client_intake_and_finmo.capture_receipt import numeric_receipt, receipt_summary  # noqa: E402

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
    ("98552970%",),
)
OPS_FINAL = json.loads(cur.fetchone()[0])
conn.close()

results = []


def check(label, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + label)


# ============ (c) the 196 leak ============
# Pre-leak state: accounts product captured (280 cap, 0.70 util at the
# time); project product exists with no capacity yet.
OPS_PRE = copy.deepcopy(OPS_FINAL)
OPS_PRE["lob_models"][0]["products"][0]["utilization_rate"] = 0.70
for leaf in ("units_per_period_capacity", "units_per_week_capacity", "utilization_rate"):
    OPS_PRE["lob_models"][1]["products"][0].pop(leaf, None)

T21 = ("Concurrent doesn't tell you anything on this side - a project package "
       "might be a week or it might be five months. I count them over the year. "
       "We can quote and fill 160 project packages in a year without hurting "
       "the account work.")
LEASE_ASK21 = ("Thinking about your current operation and how many of those project "
               "packages you can realistically have active at the same time?")

# The leak: router writes 196 (= 280 x 0.70, product 1's derived count).
after = copy.deepcopy(OPS_PRE)
after["lob_models"][1]["products"][0]["units_per_period_capacity"] = 196.0
out = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(OPS_PRE), ops_after=after,
    user_message=T21, last_assistant=LEASE_ASK21,
)
check("(c) 196 leak DROPS (underivable first capture)",
      "units_per_period_capacity" not in out["lob_models"][1]["products"][0])

# The stated value survives.
after2 = copy.deepcopy(OPS_PRE)
after2["lob_models"][1]["products"][0]["units_per_period_capacity"] = 160.0
out2 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(OPS_PRE), ops_after=after2,
    user_message=T21, last_assistant=LEASE_ASK21,
)
check("(c) stated 160 capacity SURVIVES",
      out2["lob_models"][1]["products"][0].get("units_per_period_capacity") == 160.0)

# t23 correction, verbatim: 160 / 1 period / 75% all survive.
T23 = ("No - stop. Where did 196 come from? I never said 196 anything. That's "
       "not a number in my business. The project side is: capacity 160 packages "
       "a year, one period a year, and we run about 75% of it, so 120 packages "
       "actually delivered.")
after3 = copy.deepcopy(OPS_PRE)
p3 = after3["lob_models"][1]["products"][0]
p3["units_per_period_capacity"] = 160.0
p3["operating_periods_per_year"] = 1.0
p3["utilization_rate"] = 0.75
out3 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(OPS_PRE), ops_after=after3,
    user_message=T23, last_assistant="",
)
p3o = out3["lob_models"][1]["products"][0]
check("(c) t23 correction fully survives (160 / 1 period / 0.75)",
      p3o.get("units_per_period_capacity") == 160.0
      and p3o.get("operating_periods_per_year") == 1.0
      and p3o.get("utilization_rate") == 0.75)

# Stated price survives; invented price drops.
after4 = copy.deepcopy(OPS_PRE)
after4["lob_models"][1]["products"][0]["unit_price"] = 21000.0
out4 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(OPS_PRE), ops_after=after4,
    user_message="Average project package is about 21,000.", last_assistant="",
)
check("(c) stated price 21,000 survives",
      out4["lob_models"][1]["products"][0].get("unit_price") == 21000.0)
after5 = copy.deepcopy(OPS_PRE)
after5["lob_models"][1]["products"][0]["unit_price"] = 25000.0
out5 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(OPS_PRE), ops_after=after5,
    user_message="Average project package is about 21,000.", last_assistant="",
)
check("(c) invented price 25,000 reverts to prior stated 22,500",
      out5["lob_models"][1]["products"][0].get("unit_price") == 22500)

# Utilization first-capture default is tolerated (scoped rule).
after6 = copy.deepcopy(OPS_PRE)
after6["lob_models"][1]["products"][0]["utilization_rate"] = 1.0
out6 = _guard_underivable_ops_lever_writes(
    ops_before=copy.deepcopy(OPS_PRE), ops_after=after6,
    user_message="We just fill what comes in the door.", last_assistant="",
)
check("(c) utilization first-capture default tolerated",
      out6["lob_models"][1]["products"][0].get("utilization_rate") == 1.0)

# ============ (b) cross-section correction ============
OPS_XSEC = copy.deepcopy(OPS_FINAL)
OPS_XSEC["lob_models"][0]["products"][0]["utilization_rate"] = 0.70  # the stale value

T67 = ("Hold on, before that - I need to fix something from earlier. I told you "
       "70% utilization on the account side. That's wrong, I was thinking of two "
       "years ago. We run 75% of the 280-account capacity, so 210 active "
       "accounts in a typical month.")
r = _apply_cross_section_driver_correction(ops_json=OPS_XSEC, user_message=T67)
check("(b) live t67 utilization correction LANDS",
      r is not None and r[0]["lob_models"][0]["products"][0]["utilization_rate"] == 0.75)
check("(b) ack names the change", r is not None and "75%" in r[1])

T69 = "Set the utilization rate on the Active account product to 0.75."
r2 = _apply_cross_section_driver_correction(ops_json=copy.deepcopy(OPS_XSEC), user_message=T69)
check("(b) live t69 explicit directive LANDS",
      r2 is not None and r2[0]["lob_models"][0]["products"][0]["utilization_rate"] == 0.75)

# NEG: an ordinary financials answer must not fire.
r3 = _apply_cross_section_driver_correction(
    ops_json=copy.deepcopy(OPS_XSEC),
    user_message="Rent is $16,500 a month for the 48,000 square feet, the "
    "counter, the yard and the panel shop.",
)
check("(b) NEG rent answer does not fire", r3 is None)
# NEG: correction language without a product reference must not fire.
r4 = _apply_cross_section_driver_correction(
    ops_json=copy.deepcopy(OPS_XSEC),
    user_message="Actually change that to $38,000 a month.",
)
check("(b) NEG no-product correction does not fire", r4 is None)

# ============ (d) cadence-aware ack label ============
# The live turn-24 shape: all three fields captured in ONE turn.
OPS_D = copy.deepcopy(OPS_PRE)
OPS_D["lob_models"][1]["products"][0].pop("operating_periods_per_year", None)
before_d = {"ops": OPS_D}
after_d = copy.deepcopy(before_d)
pd = after_d["ops"]["lob_models"][1]["products"][0]
pd["units_per_week_capacity"] = 160.0
pd["units_per_period_capacity"] = 160.0
pd["operating_periods_per_year"] = 1.0
rec = numeric_receipt(before=before_d, after=after_d)
summary = receipt_summary(rec, limit=6)
check("(d) no 'weekly capacity' claim for a 1-period/year product",
      "weekly capacity" not in summary)
check("(d) cadence label says annual", "annual capacity" in summary)

print()
fails = results.count(False)
print(f"{len(results) - fails}/{len(results)} passed")
sys.exit(1 if fails else 0)
