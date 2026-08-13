"""Verify the fresh Sunny_V3 canary draft: run complete, landed payroll
unchanged, provenance stamped with the full chain. Read-only."""
import json
import os

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, model_input_json, planning_run_json FROM intake_consult_drafts "
    "WHERE draft_id=%s", ("3e1c121816b74710912ccc586e879b8a",))
r = cur.fetchone()
mi = json.loads(r["model_input_json"] or "{}")
pr = json.loads(r["planning_run_json"] or "{}")
prov = (mi.get("solver_input") or {}).get("payroll_provenance") or {}
vals = next((row.get("values") for row in ((mi.get("sections") or {}).get("expenses") or [])
             if isinstance(row, dict) and row.get("label") == "Payroll"), [])
print("run status:", pr.get("status"))
print("landed annual (values[1]x4):", float(vals[1]) * 4 if len(vals) > 1 else None)
print("provenance stamped:", bool(prov))
print(json.dumps(prov, indent=1))
cur.close()
conn.close()

