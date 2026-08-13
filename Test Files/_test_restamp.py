"""Directly exercise the hook's re-stamp call against the authoritative
re-run row, then re-verify the draft."""
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

draft_id = "8bc7c339c9e24689861d62c75f3109bf"
run_id = "924d896a325846fb816c6d9edb3bd048"
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
from client_intake_and_finmo.intake_consult_draft import persist_adaptation_cascade_outcome

out = persist_adaptation_cascade_outcome(
    conn,
    draft_id=draft_id,
    planning_run_id=run_id,
    plan_confidence="restructured_viable_candidate",
    cascade_diagnostics={"tier_landed": 0, "source": "restructure_rerun_restamp"},
)
print("stamp result:", out)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT plan_confidence, cascade_landed_tier FROM planning_runs WHERE planning_run_id=%s",
    (run_id,),
)
print("row now:", cur.fetchone())
from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance
v = verify_run_acceptance(conn, draft_id=draft_id, planning_run_id=run_id)
print("VERDICT passed:", v.get("passed"), "failed:", v.get("failed_checks"))
cur.close()
conn.close()
