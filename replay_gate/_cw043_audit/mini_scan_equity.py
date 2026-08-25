"""scan every stored draft's balance-sheet rows for Owner's Capital / Other Equity steps and Distributions."""
import json, os, sys
sys.path.insert(0, r"C:\dev\business_plann_app"); sys.path.insert(0, r"C:\dev\business_plann_app\python")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(r"C:\dev\business_plann_app\.env")
import mysql.connector
from client_statements_output_excel.data import draft_data_from_row, values_21
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True); cur.execute("SELECT * FROM intake_consult_drafts WHERE finmo_json IS NOT NULL AND model_input_json IS NOT NULL ORDER BY updated_at DESC"); rows = cur.fetchall()
n=0; steps=[]; q1=[]; dist=[]; oe_steps=[]
for r in rows:
    try:
        d = draft_data_from_row(dict(r))
        by = {x.get("label"): values_21(x.get("values")) for x in d.balance_sheet_rows}
    except Exception as e:
        continue
    oc = by.get("Owner's Capital"); oe = by.get("Other Equity"); ds = by.get("Distributions")
    if oc is None: continue
    n+=1
    did = r["draft_id"][:8]; name = (r.get("business_name") or "")[:28]
    st = [i for i in range(2,21) if abs(oc[i]-oc[i-1])>1e-9]
    if st: steps.append((did, name, st, [round(v) for v in oc]))
    if abs(oc[1]-oc[0])>1e-9: q1.append((did, name, round(oc[0]), round(oc[1])))
    if oe and any(abs(oe[i]-oe[i-1])>1e-9 for i in range(1,21)): oe_steps.append((did,name,[round(v) for v in oe]))
    if ds and any(abs(v)>1e-9 for v in ds): dist.append((did,name,[round(v) for v in ds]))
print("drafts with Owner's Capital row:", n)
print("OC steps (i>=2):", len(steps)); [print("  ", s) for s in steps[:12]]
print("Q1 != stub:", len(q1)); [print("  ", s) for s in q1[:12]]
print("Other Equity non-flat:", len(oe_steps)); [print("  ", s) for s in oe_steps[:5]]
print("Distributions nonzero:", len(dist)); [print("  ", s) for s in dist[:8]]
