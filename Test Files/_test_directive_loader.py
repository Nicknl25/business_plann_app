"""Replicate the runner's restructure-directive loader against a draft."""
import os
import sys
import json
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
    "SELECT repair_guidance_json FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
)
row = cur.fetchone() or {}
raw = row.get("repair_guidance_json")
guidance = (
    json.loads(raw) if isinstance(raw, str) and raw.strip()
    else (raw if isinstance(raw, dict) else {})
)
active = ((guidance or {}).get("restructure") or {}).get("active_directive")
print("guidance type:", type(raw).__name__)
print("restructure key present:", "restructure" in (guidance or {}))
print("active_directive is dict:", isinstance(active, dict))
if isinstance(active, dict):
    print("feasible:", active.get("feasible"))
    print("LOADER WOULD FIRE:", bool(isinstance(active, dict) and active.get("feasible")))
    print("team:", (active.get("team") or {}).get("annual_payroll"))
cur.close()
conn.close()
