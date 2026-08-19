# -*- coding: utf-8 -*-
"""RESEARCH: run vitals + model json for draft 50658fff."""
import json, sys, io
import mysql.connector

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
SCRATCH = r"C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad"

conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!",
                               database="biz_plan_revert", charset="utf8mb4")
cur = conn.cursor(dictionary=True)

cur.execute("SHOW TABLES LIKE 'run_vitals%'")
tables = [list(r.values())[0] for r in cur.fetchall()]
print("VITALS TABLES:", tables)

cur.execute("SELECT draft_id, revenue_model_json, operating_model_json FROM intake_consult_drafts WHERE draft_id LIKE '50658fff%'")
row = cur.fetchone()
did = row["draft_id"]
print("draft:", did)
for col in ("revenue_model_json", "operating_model_json"):
    v = row.get(col)
    open(SCRATCH + "\\ff_" + col + ".json", "w", encoding="utf-8").write(v or "null")
    print(col, "len", len(v or ""))

# messages full keys for late turns
cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s", (did,))
msgs = json.loads(cur.fetchone()["messages_json"])
out = []
for i in range(104, len(msgs)):
    out.append(f"=== [{i}] keys={sorted(msgs[i].keys())}\n" + json.dumps(msgs[i], indent=1, default=str)[:3000])
open(SCRATCH + "\\ff_msgs_meta.txt", "w", encoding="utf-8").write("\n\n".join(out))
print("msgs meta written")

for t in tables:
    cur.execute(f"SHOW COLUMNS FROM {t}")
    cols = [c["Field"] for c in cur.fetchall()]
    print(t, "COLS:", cols)
    # try to find rows for this draft
    where = None
    for c in ("draft_id", "intake_draft_id"):
        if c in cols:
            where = c
            break
    if where:
        cur.execute(f"SELECT COUNT(*) n FROM {t} WHERE {where}=%s", (did,))
        print(t, "rows for draft:", cur.fetchone()["n"])
