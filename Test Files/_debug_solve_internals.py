"""Dump solve_review_plan internals for the restructure Q11 task."""
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
cur.execute("SELECT model_input_json FROM intake_consult_drafts WHERE draft_id=%s",
            ("3464962b16864c1a942d48c746dc48bb",))
mi = json.loads(cur.fetchone()["model_input_json"])
cur.execute("SELECT repair_guidance_json FROM intake_consult_drafts WHERE draft_id=%s",
            ("5dd5a32124c741c18f2cdc532d96cdc2",))
g = json.loads(cur.fetchone()["repair_guidance_json"])
bounds = next(it["bounds"] for it in g["restructure"]["history"] if it.get("stage") == "bounds")
cur.close()
conn.close()

import client_intake_and_finmo.post_intake_restructure.joint_solver as js
from client_intake_and_finmo.numeric_solver import solve_review_plan

# Monkeypatch to capture the exact payloads the joint solver builds,
# then run ONE rung with only the Q11 task and print attempts.
prepared = js._prepare_restructure_model(mi, bounds)
base_lv = js._base_levels(mi)
plan = js._lever_plan(prepared, bounds, base_lv, 1.2438)

import time as _t
lever_ids = sorted(plan["bounds"].keys())
rev_q11 = js._base_quarter_revenue(prepared, 11)
translated_updates = []
rows_by_lever = {
    str(r.get("lever_id") or "").strip(): r
    for r in ((prepared.get("sections") or {}).get("revenue") or [])
    if isinstance(r, dict)
}
for lever_id in lever_ids:
    b = plan["bounds"].get(lever_id, {}).get(11)
    if not b:
        continue
    lo, hi = float(b[0]), float(b[1])
    r = rows_by_lever.get(lever_id) or {}
    vals = r.get("values") or []
    base_q = float((vals[11] if len(vals) > 11 else 0.0) or 0.0)
    if lever_id in plan["new_line_of_lever"] or lever_id.endswith("::Unit Price"):
        fav = hi
    elif lever_id.startswith("revenue::"):
        fav = base_q
    else:
        fav = lo
    translated_updates.append({
        "lever_id": lever_id, "quarter_index": 11,
        "exact_value": round(fav, 6), "baseline_value": round(base_q, 6),
    })

review_plan = {
    "translated_action_packages": [{
        "action_id": "dbg",
        "solver_allowed_lever_ids": lever_ids,
        "required_target_metric_keys": ["net_income", "ebitda"],
        "quarter_target_metrics": [
            {"quarter_index": 11, "net_income": rev_q11 * 0.03, "ebitda": rev_q11 * 0.06}
        ],
        "translated_updates": translated_updates,
    }],
}
contract = {
    "pass_name": "restructure_viability",
    "runtime_deadline_monotonic": _t.monotonic() + 240.0,
    "solver_settings": {"aggressiveness": "structural"},
    "issue_target_packets": [{
        "repair_targets": [{
            "quarter": 11,
            "driver_paths": [
                {"lever": lid, "suggested_min_value": float(plan["bounds"][lid][11][0]),
                 "suggested_max_value": float(plan["bounds"][lid][11][1])}
                for lid in lever_ids if 11 in plan["bounds"].get(lid, {})
            ],
        }],
    }],
}
res = solve_review_plan(
    model_input_json=prepared, review_plan=review_plan,
    numeric_solver_contract=contract, fallback_exact_updates=[],
)
print("state:", res.get("execution_state"))
for att in res.get("attempts") or []:
    print("attempt:", json.dumps({k: att.get(k) for k in ("quarter_index", "optimizer_converged", "objective_value", "objective_improvement")}, sort_keys=True))
for qr in res.get("quarter_results") or []:
    print("quarter_result keys:", list(qr.keys())[:10] if isinstance(qr, dict) else qr)
    if isinstance(qr, dict):
        print(json.dumps(qr, default=str)[:1500])
ups = res.get("exact_updates") or []
for u in ups:
    print("update:", u.get("lever_id"), "q", u.get("quarter_index"), "=", round(float(u.get("exact_value") or 0), 4))
