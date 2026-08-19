# RESEARCH ONLY: first owner-comp capture + people-section wage capture
import json
import mysql.connector

DRAFT = "50658fff105e480c896f714fa519f22e"

conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,))
msgs = json.loads(cur.fetchone()["messages_json"] or "[]")

print("=== turns 62-66 FULL ===")
for i in range(62, 67):
    m = msgs[i]
    print(f"\n--- [{i}] {m.get('role')} ---")
    print(str(m.get("content") or "")[:1200])

print("\n=== people-section wage turns (search '2,000'/'24,000'/'wage'/'pay' in turns 0-61) ===")
for i, m in enumerate(msgs[:62]):
    c = str(m.get("content") or "")
    low = c.lower()
    if any(t in low for t in ("2,000", "24,000", "wage", "pay myself", "salary")):
        print(f"\n--- [{i}] {m.get('role')} ---")
        print(" ".join(c.split())[:700])
