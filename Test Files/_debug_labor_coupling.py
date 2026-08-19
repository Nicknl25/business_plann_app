import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT model_input_json FROM intake_consult_drafts WHERE draft_id=%s",
    ("3464962b16864c1a942d48c746dc48bb",),
)
mi = json.loads(cur.fetchone()["model_input_json"])
cur.close()
conn.close()

from client_intake_and_finmo.post_intake_restructure.searcher import apply_candidate
from client_intake_and_finmo.post_intake_restructure.fast_evaluator import build_fast_finmo

cand = {"lines": {"fresh gourmet mushrooms/fresh mushrooms": {"volume_m11": 2.2, "volume_m20": 2.2}}}
mi2 = apply_candidate(mi, cand)

def payroll_row_q(mi_x, q):
    for r in ((mi_x.get("sections") or {}).get("expenses") or []):
        if isinstance(r, dict) and str(r.get("label")) == "Payroll":
            return r.get("values", [None] * 21)[q]
    return None

def cap_q(mi_x, q):
    for r in ((mi_x.get("sections") or {}).get("revenue") or []):
        if (isinstance(r, dict) and r.get("driver") == "Capacity"
                and "fresh" in str(r.get("lob") or "").lower()):
            return r.get("values", [None] * 21)[q], r.get("derived_driver")
    return None, None

print("model_input payroll row q11: base:", payroll_row_q(mi, 11), "candidate:", payroll_row_q(mi2, 11))
print("model_input fresh Capacity q11: base:", cap_q(mi, 11), "candidate:", cap_q(mi2, 11))

fin = build_fast_finmo(mi2)
rows = {int(float(r.get("quarter_index"))): r for r in fin.get("quarter_rows") or [] if isinstance(r, dict)}
q11 = rows.get(11) or {}
print("FINMO q11: revenue:", q11.get("revenue"), "payroll:", q11.get("payroll"))
print("payroll_headcount policy present:", bool((mi.get("derived_driver_policies") or {})))
print("derived_driver_policies keys:", list((mi.get("derived_driver_policies") or {}).keys())[:6])
