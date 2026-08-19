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
    "SELECT planning_runtime_json, planning_context_summary_json, planning_run_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
)
row = cur.fetchone() or {}
for col in ("planning_runtime_json", "planning_context_summary_json", "planning_run_json"):
    raw = row.get(col)
    d = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or {})
    txt = json.dumps(d)
    print(col, "keys:", list(d.keys())[:25] if isinstance(d, dict) else type(d))
    for needle in ("restructure_directive_trace", "restructure_pricing", "restructure"):
        i = txt.find(needle)
        print("  ", needle, "->", txt[max(0, i - 80):i + 300].replace("\\n", " ") if i >= 0 else "ABSENT")
cur.close()
conn.close()
