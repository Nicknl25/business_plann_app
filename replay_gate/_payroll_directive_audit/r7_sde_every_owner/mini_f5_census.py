"""mini F5 census (read-only): live drafts with an owner-titled row carrying a
numeric wage AND financials.owner_compensation empty/0 -> at HEAD ab5256d the
Valuation sheet added back NOTHING for them. Also: two-owner drafts."""
import json, os, sys, re
sys.path[:0] = ['.', 'python', 'python/client_intake_and_finmo']
from dotenv import load_dotenv; load_dotenv('.env')
from intake_submission import get_mysql_connection
from client_intake_and_finmo.owner_pay import owner_pay_total, owner_rows
conn = get_mysql_connection(); cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, client_id, created_at, people_json, financials_json FROM intake_consult_drafts")
n=0; f5=[]; two=[]; owner_any=0; mirror_only=0
for r in cur.fetchall():
    n+=1
    try: ppl=json.loads(r.get("people_json") or "{}")
    except Exception: ppl={}
    try: fin=json.loads(r.get("financials_json") or "{}")
    except Exception: fin={}
    t=owner_pay_total(ppl, fin)
    m=fin.get("owner_compensation")
    try: mv=float(m)
    except (TypeError, ValueError): mv=None
    if t["source"]=="people_rows":
        owner_any+=1
        if mv is None or mv==0:
            f5.append((r["draft_id"][:8], r["business_name"], str(r["created_at"])[:16], t["owners"], t["annual_total"], m))
        if t["owners"]>=2:
            two.append((r["draft_id"][:8], r["business_name"], str(r["created_at"])[:16], t["owners"], t["annual_total"], m))
    elif t["source"]=="legacy_mirror":
        mirror_only+=1
print(f"drafts scanned: {n}")
print(f"[owner row with numeric wage]: {owner_any}")
print(f"[F5: owner row + mirror empty/0]: {len(f5)}")
for x in f5: print("   ", x)
print(f"[two-or-more owner rows with wages]: {len(two)}")
for x in two: print("   ", x)
print(f"[legacy: no owner row wage, mirror>0 only]: {mirror_only}")
conn.close()
