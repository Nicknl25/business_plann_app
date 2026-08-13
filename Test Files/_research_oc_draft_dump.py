# RESEARCH ONLY: dump owner-comp-relevant state for draft 50658fff...
import json
import mysql.connector

DRAFT = "50658fff105e480c896f714fa519f22e"

conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, business_name, financials_json, people_json, messages_json "
    "FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,)
)
row = cur.fetchone()
if not row:
    print("DRAFT NOT FOUND")
    raise SystemExit(1)

fin = json.loads(row["financials_json"] or "{}")
ppl = json.loads(row["people_json"] or "{}")
msgs = json.loads(row["messages_json"] or "[]")

print("=== business:", row["business_name"])
print("\n=== financials_json owner/payroll keys ===")
for k in sorted(fin.keys()):
    if any(t in k for t in ("owner", "payroll", "compensation", "wage")):
        print(f"  {k} = {json.dumps(fin[k])[:600]}")

print("\n=== people_json (roles w/ wages) ===")
def walk(obj, path=""):
    if isinstance(obj, dict):
        if any(k in obj for k in ("annual_wage", "role_title", "position_title", "person_name")):
            print(f"  [{path}] " + json.dumps({k: obj.get(k) for k in (
                "person_name", "role_title", "position_title", "annual_wage",
                "wage_source", "months_until_hire", "responsibilities") if k in obj}))
        for k, v in obj.items():
            walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            walk(item, f"{path}[{i}]")
walk(ppl)
print("\n  people_json top-level keys:", sorted(ppl.keys()))

print("\n=== messages_json: total turns =", len(msgs), "===")
# print turns 90-125 with role + truncated content, flag pay-related
for i, m in enumerate(msgs):
    if not (85 <= i <= 125):
        continue
    role = m.get("role") or m.get("sender") or "?"
    content = str(m.get("content") or m.get("text") or "")
    flat = " ".join(content.split())
    pay_hit = any(t in flat.lower() for t in ("pay", "draw", "salary", "comp", "3,300", "3300", "2,000", "2000", "24,000", "24000"))
    marker = " <<< PAY" if pay_hit else ""
    print(f"[{i}] {role}: {flat[:400]}{marker}")
