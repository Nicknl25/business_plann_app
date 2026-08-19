# -*- coding: utf-8 -*-
"""RESEARCH: dump Fetch & Fluff draft 50658fff transcript + financials fields."""
import json, sys, io
import mysql.connector

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!",
                               database="biz_plan_revert", charset="utf8mb4")
cur = conn.cursor(dictionary=True)
cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", ("50658fff%",))
row = cur.fetchone()
if not row:
    print("NO DRAFT FOUND")
    sys.exit(0)
print("COLUMNS:", sorted(row.keys()))
msgs = json.loads(row.get("messages_json") or "[]")
print("N_MESSAGES:", len(msgs))
out = []
for i, m in enumerate(msgs):
    role = m.get("role")
    txt = str(m.get("content") or m.get("text") or "")
    out.append(f"--- [{i}] {role} ---\n{txt}\n")
open(r"C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\ff_transcript.txt",
     "w", encoding="utf-8").write("\n".join(out))
print("transcript written")

fin = json.loads(row.get("financials_json") or "{}")
print("FIN KEYS:", sorted(fin.keys()))
for k in ("current_revenue", "expected_revenue", "payroll", "labor_cost", "owner_compensation"):
    if k in fin:
        print(k, "=", fin.get(k))
coh = fin.get("coherence") or fin.get("_coherence") or {}
print("COHERENCE STATE KEYS:", sorted(coh.keys()) if isinstance(coh, dict) else type(coh))
open(r"C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\ff_financials.json",
     "w", encoding="utf-8").write(json.dumps(fin, indent=2, default=str))
print("financials written")
