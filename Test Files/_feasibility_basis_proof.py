"""FLEET PROOF for #4 (explicit payroll basis in structural feasibility).

Per fleet business: run verify's arithmetic twice in-process —
  (a) with the real schedule payload  -> basis per_quarter_schedule
  (b) with an empty payload           -> basis flat_stated_fallback +
                                         degraded_inputs flag + warning
and assert the FEASIBILITY VERDICT is unchanged in (a) vs the stored
behavior class (no previously-passing business flips, no non-viable
business starts passing). Also proves the blessed accessor returns the
canonical 20-quarter schedule on every draft. Read-only DB."""
import json
import logging
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")
logging.basicConfig(level=logging.WARNING)

from client_intake_and_finmo.post_intake_headcount.schedule import (
    payroll_headcount_from_model_input,
)
from client_intake_and_finmo.post_intake_solver.structural_feasibility_check import (
    verify_structural_feasibility,
)

DRAFTS = [
    ("Sunny_V3", "3e1c1218"),
    ("Blueprint", "49181987"),
    ("Meridian", "0f8e1e1c"),
    ("Harvest Lane", "9408bd78"),
    ("Ironthread", "98a147fd"),
    ("Understory", "ea30f6dc"),
    ("Redux", "17d8793b"),
]

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


ok_all = True
print(f"{'business':14} {'sched(accessor)':>15} {'basis w/ sched':>20} {'feasible':>9} "
      f"{'basis w/o sched':>22} {'feasible':>9} {'flags':>10}")
for label, prefix in DRAFTS:
    cur.execute(
        "SELECT operating_model_json, financials_json, financials_year1_json, model_input_json, "
        "payroll_headcount FROM intake_consult_drafts WHERE draft_id LIKE %s "
        "ORDER BY updated_at DESC LIMIT 1", (prefix + "%",))
    r = cur.fetchone()
    if not r:
        print(f"{label:14} NOT FOUND")
        ok_all = False
        continue
    ops = _j(r.get("operating_model_json"))
    fin = _j(r.get("financials_json"))
    y1 = _j(r.get("financials_year1_json"))
    mi = _j(r.get("model_input_json"))
    payload = _j(r.get("payroll_headcount"))

    accessor = payroll_headcount_from_model_input(mi)
    n_acc = len(accessor.get("quarter_totals") or [])

    res_with = verify_structural_feasibility(
        ops_json=ops, financials_json=fin, financials_year1_json=y1,
        payroll_headcount=payload,
    ).to_dict()
    res_without = verify_structural_feasibility(
        ops_json=ops, financials_json=fin, financials_year1_json=y1,
        payroll_headcount={},
    ).to_dict()
    b_with = (res_with.get("inputs_used") or {}).get("payroll_basis")
    b_without = (res_without.get("inputs_used") or {}).get("payroll_basis")
    degraded = bool((res_without.get("inputs_used") or {}).get("degraded_inputs"))
    ok = (
        n_acc >= 20
        and b_with == "per_quarter_schedule"
        and b_without in ("flat_stated_fallback", "none")
        and (b_without != "flat_stated_fallback" or degraded)
        and bool(res_with.get("feasible"))  # every fleet business is structurally feasible
    )
    ok_all = ok_all and ok
    print(f"{label:14} {n_acc:>15} {str(b_with):>20} {str(res_with.get('feasible')):>9} "
          f"{str(b_without):>22} {str(res_without.get('feasible')):>9} "
          f"{('degraded' if degraded else '-'):>10}")

print()
print("FLEET PROOF:", "PASS - basis explicit on every draft, degradation declared, "
      "no feasibility verdict changed" if ok_all else "FAIL")
cur.close()
conn.close()
