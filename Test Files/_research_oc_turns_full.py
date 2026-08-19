# RESEARCH ONLY: full text of key turns + locate owner-comp stage question
import json
import mysql.connector

DRAFT = "50658fff105e480c896f714fa519f22e"

conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute("SHOW COLUMNS FROM intake_consult_drafts")
cols = [r["Field"] for r in cur.fetchall()]
print("=== draft columns ===")
print(cols)

cur.execute(
    "SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,)
)
row = cur.fetchone()
msgs = json.loads(row["messages_json"] or "[]")

print("\n=== turns containing the owner-comp stage question or first owner-pay capture ===")
for i, m in enumerate(msgs):
    c = str(m.get("content") or "")
    if "pay yourself" in c.lower() or "owner pay" in c.lower():
        role = m.get("role")
        print(f"\n--- [{i}] {role} ---")
        print(c[:1500])

print("\n=== FULL key turns 97, 101, 111, 112, 113 ===")
for i in (97, 101, 111, 112, 113):
    m = msgs[i]
    print(f"\n--- [{i}] {m.get('role')} ---")
    print(str(m.get("content") or "")[:3000])
