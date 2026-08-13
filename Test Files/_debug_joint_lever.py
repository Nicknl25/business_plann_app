"""Single-lever probe: does moving fresh Unit Price at Q11 through the
solver's own apply-path actually move Q11 net income?"""
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
cur.execute(
    "SELECT repair_guidance_json FROM intake_consult_drafts WHERE draft_id=%s",
    ("5dd5a32124c741c18f2cdc532d96cdc2",),
)
g = json.loads(cur.fetchone()["repair_guidance_json"])
bounds = next(it["bounds"] for it in g["restructure"]["history"] if it.get("stage") == "bounds")
cur.close()
conn.close()

from client_intake_and_finmo.post_intake_restructure.joint_solver import (
    _prepare_restructure_model,
)
from client_intake_and_finmo.quarter_grid import apply_exact_lever_updates_to_model_input
from client_intake_and_finmo.post_intake_restructure.fast_evaluator import build_fast_finmo

prepared = _prepare_restructure_model(mi, bounds)

# Find the fresh Unit Price lever id + baseline at Q11.
lever_id = None
base_q11 = None
for r in ((prepared.get("sections") or {}).get("revenue") or []):
    if (isinstance(r, dict) and r.get("driver") == "Unit Price"
            and "fresh" in str(r.get("lob") or "").lower()):
        lever_id = str(r.get("lever_id") or "")
        base_q11 = float((r.get("values") or [0] * 21)[11])
        break
print("lever:", lever_id, "base_q11:", base_q11)


def ni_q11(mi_x):
    fin = build_fast_finmo(mi_x)
    rows = {int(float(r.get("quarter_index"))): r for r in fin.get("quarter_rows") or [] if isinstance(r, dict)}
    r = rows.get(11) or {}
    return float(r.get("net_income") or 0.0), float(r.get("revenue") or 0.0)


print("baseline NI/rev q11:", ni_q11(prepared))
for mult in (1.15, 1.35):
    updated = apply_exact_lever_updates_to_model_input(
        model_input_json=prepared,
        exact_updates=[{"lever_id": lever_id, "quarter_index": 11, "exact_value": base_q11 * mult}],
    )
    # What does the row ACTUALLY hold after the apply?
    for r in ((updated.get("sections") or {}).get("revenue") or []):
        if str(r.get("lever_id") or "") == lever_id:
            print(f"x{mult}: row q11 after apply:", (r.get("values") or [0] * 21)[11])
            break
    print(f"x{mult}: NI/rev q11:", ni_q11(updated))
