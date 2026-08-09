"""Keystone - trigger the system run for a REAL draft (rerun POST,
never passing planning_run_id: the run names the NEW run) and wait."""
import os
import sys

import requests
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
BASE = "http://127.0.0.1:5050"
prefix = sys.argv[1]

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, client_id FROM intake_consult_drafts WHERE draft_id LIKE %s",
    (prefix + "%",))
row = cur.fetchone()
draft_id, client_id = row["draft_id"], row["client_id"]
print(f"triggering system run for {draft_id}")
resp = requests.post(f"{BASE}/api/intake-consult/system-run", json={
    "draft_id": draft_id, "client_id": client_id,
}, timeout=1800)
print(f"HTTP {resp.status_code}")
try:
    body = resp.json()
    print({k: body.get(k) for k in ("status", "planning_run_status", "error", "message") if k in body})
except Exception:
    print(resp.text[:800])
cur.execute(
    "SELECT planning_run_status, planning_failure_reason FROM intake_consult_drafts "
    "WHERE draft_id=%s", (draft_id,))
print(cur.fetchone())
