"""A-122 control: clone a COMPLETED draft as-is (full model, status completed,
NOT submitted, no planning run) under a fresh draft_id/client_id so it can go
through the real submit door. Usage: <source_draft_id> <tag>"""
import json, os, sys, uuid
from dotenv import load_dotenv; load_dotenv()
import mysql.connector
src_id, tag = sys.argv[1], sys.argv[2]
conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306))
cur = conn.cursor(dictionary=True)
cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (src_id,))
src = cur.fetchone(); cur.close()
assert src, "source missing"
clone_id = tag + uuid.uuid4().hex[: 32 - len(tag)]
client_id = tag.upper() + uuid.uuid4().hex[:10].upper()
overrides = {"draft_id": clone_id, "client_id": client_id, "status": "completed",
  "submitted_at": None, "intake_submission_id": None,
  "planning_run_id": None, "planning_run_status": None, "planning_stage": None, "planning_status": None}
columns = [c for c in src.keys() if c != "id"]
values = [overrides.get(c) if c in overrides else src[c] for c in columns]
cur = conn.cursor()
cur.execute(f"INSERT INTO intake_consult_drafts ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})", tuple(values))
conn.commit(); cur.close()
print(clone_id, client_id)
