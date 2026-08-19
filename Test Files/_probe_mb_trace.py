"""Find the margin_band trace for the canary run: which source did the
runner record, and what inputs did it hash? Read-only."""
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
    "SELECT planning_run_json, planning_runtime_json FROM intake_consult_drafts WHERE draft_id=%s",
    ("e3e1cedd7f354006a0b1b1271ed87600",),
)
r = cur.fetchone()

for col in ("planning_run_json", "planning_runtime_json"):
    raw = r.get(col) or ""
    s = raw if isinstance(raw, str) else json.dumps(raw)
    for token in ("margin_band_trace", "coherence_stamp_reused", "executive_margin_band_judgment", "_coherence"):
        idx = s.find(token)
        print(f"{col}: {token} -> {'FOUND at ' + str(idx) if idx >= 0 else 'absent'}")
        if idx >= 0 and token == "margin_band_trace":
            print("   context:", s[idx:idx + 400].replace("\\n", " ")[:400])
cur.close()
conn.close()
