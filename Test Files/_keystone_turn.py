"""Keystone confirmation - post ONE turn to a REAL draft via the
production API and print the assistant's reply + key DB state after.

Usage: _keystone_turn.py <draft_prefix> "<message>"
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
BASE = "http://127.0.0.1:5050"
prefix = sys.argv[1]
message = sys.argv[2]

# autocommit=True: without it the first SELECT pins a REPEATABLE READ
# snapshot and the post-turn read shows PRE-turn state (the documented
# poller trap - it burned this very script).
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

resp = requests.post(f"{BASE}/api/intake-consult", json={
    "draft_id": draft_id, "client_id": client_id, "message": message,
}, timeout=600)
print(f"HTTP {resp.status_code}")
body = resp.json()
print("--- assistant ---")
print(str(body.get("assistant_message") or "")[:3000])
print("--- state after ---")
cur.execute(
    "SELECT financials_json, operating_model_json, people_json "
    "FROM intake_consult_drafts WHERE draft_id=%s", (draft_id,))
r2 = cur.fetchone()
fin = json.loads(r2["financials_json"] or "{}")
ops = json.loads(r2["operating_model_json"] or "{}")
ppl = json.loads(r2["people_json"] or "{}")
st = fin.get("_coherence") or {}
print(f"revenue={fin.get('current_revenue')} "
      f"payroll(base/cur/tot)={fin.get('baseline_payroll_year1')}/"
      f"{fin.get('current_payroll')}/{fin.get('payroll_total_year1')} "
      f"adj={fin.get('payroll_adjustment')}")
print(f"cogs pct={fin.get('cogs_percent_of_revenue')} cur={fin.get('current_cogs')} "
      f"basis={fin.get('cogs_basis')!r}")
print(f"coherence status={st.get('status')!r} "
      f"class={((st.get('margin_band_judgment') or {}).get('labor_intensity_class'))!r} "
      f"gap={st.get('gap_open')} walls={json.dumps(st.get('walls'))}")
lines = [(l.get("lob_name"), p.get("product_name"), p.get("unit_price"),
          p.get("units_per_period_capacity"), p.get("utilization_rate"))
         for l in (ops.get("lob_models") or []) for p in (l.get("products") or [])]
print(f"ops={lines}")
print(f"people={[(p.get('role_title'), p.get('annual_wage')) for p in (ppl.get('people') or [])]} "
      f"rest={ppl.get('rest_of_team_payroll_year1')}")
cur.close()
conn.close()
