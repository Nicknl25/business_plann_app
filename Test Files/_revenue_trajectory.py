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
cur.execute("SELECT finmo_json FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
fm = json.loads(cur.fetchone()["finmo_json"])
rows = {int(float(r.get("quarter_index"))): r for r in fm.get("quarter_rows") or [] if isinstance(r, dict)}
revs = [round(float((rows.get(q) or {}).get("revenue") or 0)) for q in range(1, 21)]
print("quarterly revenue Q1-Q20:")
for q, v in enumerate(revs, start=1):
    print(f"  Q{q}: {v:,}")
flat_pairs = sum(1 for i in range(1, 20) if revs[i] == revs[i - 1])
print("flat quarter-pairs:", flat_pairs)
cur.close()
conn.close()
