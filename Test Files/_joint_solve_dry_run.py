"""Offline proof: run_restructure_joint_solve (SciPy joint solve) on
Understory's real failed model with the real authored bounds."""
import json
import os
import sys
import time

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
    "SELECT model_input_json, planning_runtime_json, operating_model_json, financials_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    ("3464962b16864c1a942d48c746dc48bb",),
)
row = cur.fetchone()
mi = json.loads(row["model_input_json"])
runtime = json.loads(row["planning_runtime_json"])
ops = json.loads(row["operating_model_json"])
fin = json.loads(row["financials_json"])
# Real bounds (draft 5dd5a321 authored per-line margins).
cur.execute(
    "SELECT repair_guidance_json FROM intake_consult_drafts WHERE draft_id=%s",
    ("5dd5a32124c741c18f2cdc532d96cdc2",),
)
g = json.loads(cur.fetchone()["repair_guidance_json"])
bounds = next(it["bounds"] for it in g["restructure"]["history"] if it.get("stage") == "bounds")
cur.close()
conn.close()

from client_intake_and_finmo.post_intake_restructure.joint_solver import (
    run_restructure_joint_solve,
)
from client_intake_and_finmo.post_intake_restructure.searcher import candidate_to_directive

planning_mode = str(runtime.get("planning_mode") or "").strip() or None
naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None

t0 = time.perf_counter()
result = run_restructure_joint_solve(
    base_model_input=mi, bounds=bounds,
    business_naics_6=naics, ops_json=ops, financials_json=fin,
    planning_mode=planning_mode,
)
elapsed = time.perf_counter() - t0
print(f"JOINT SOLVE: found={result['found']} in {elapsed:.1f}s")
for line in result["trace"]:
    print("  ", line)
score = result.get("score") or {}
print("failed_binding:", score.get("failed_binding"))
for q in ("q5", "q11", "q20"):
    print(f"landed {q}:", (score.get("landed") or {}).get(q))
print("\ncandidate:", json.dumps(result["candidate"], indent=1, sort_keys=True))
if result["found"]:
    d = candidate_to_directive(
        result["candidate"], bounds, result["base_levels"],
        base_model_input=mi,
        line_margins=result.get("line_margins") or None,
        payroll_burden_factor=float(result.get("payroll_burden_factor") or 1.0),
    )
    print("\ndirective team payroll (wages):", d["team"]["annual_payroll"])
    print("directive rent:", d["facility"]["quarterly_rent_target"])
    print("directive cogs:", d["cost_structure"]["cogs_percent_of_revenue"])
    print("directive mix:", json.dumps(d["revenue_mix"], sort_keys=True)[:900])
