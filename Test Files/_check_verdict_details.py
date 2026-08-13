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
from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance

for draft_id in sys.argv[1:]:
    v = verify_run_acceptance(conn, draft_id=draft_id)
    print(f"== {draft_id[:12]}: passed={v.get('passed')}")
    for c in v.get("checks") or []:
        if not c.get("passed"):
            print("  ", c.get("name"), "->", json.dumps(c.get("detail"), default=str)[:500])
conn.close()
