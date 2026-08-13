import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
draft_id = sys.argv[1]
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT planning_run_id, created_at, updated_at, plan_confidence, cascade_landed_tier, "
    "acceptance_verdict_json IS NOT NULL AS has_verdict "
    "FROM planning_runs WHERE draft_id=%s ORDER BY created_at",
    (draft_id,),
)
for r in cur.fetchall():
    print(r["created_at"], r["planning_run_id"],
          "conf:", r["plan_confidence"], "tier:", r["cascade_landed_tier"],
          "verdict_row:", bool(r["has_verdict"]), "updated:", r["updated_at"])
cur.execute(
    "SELECT planning_run_json FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
)
pr = json.loads(cur.fetchone()["planning_run_json"])
print("draft planning_run_json.planning_run_id:", pr.get("planning_run_id"))
cur.close()
conn.close()
