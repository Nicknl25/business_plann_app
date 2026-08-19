"""Compare planning_runs stamps: the restructure re-run vs its first pass."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
draft_id = sys.argv[1] if len(sys.argv) > 1 else "2c60f62fc636430eac3388d32933ea88"
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT planning_run_id, created_at, plan_confidence, cascade_landed_tier "
    "FROM planning_runs WHERE draft_id=%s ORDER BY created_at",
    (draft_id,),
)
rows = cur.fetchall()
for r in rows:
    print(r["created_at"], r["planning_run_id"][:14],
          "confidence:", r["plan_confidence"], "tier:", r["cascade_landed_tier"])
# The re-run's planning_run_json cascade payloads:
cur.execute(
    "SELECT planning_run_json FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
)
pr = json.loads(cur.fetchone()["planning_run_json"])
for key in ("adaptation_cascade", "controller_resolution_state", "resolution_summary"):
    v = pr.get(key)
    if isinstance(v, dict):
        print(key, "keys:", list(v.keys())[:8])
        print("  ", json.dumps({k: v.get(k) for k in list(v.keys())[:5]}, default=str)[:400])
    else:
        print(key, "->", str(v)[:120])
cur.close()
conn.close()
