"""(h) population check my way: evaluate the EXACT emitted chain (stub literal; =prev; =ROUND(prev +/- |delta|,6))
in Python over every stored draft, float-equality vs the engine series; and enumerate steppers for sampling."""
import json, os, sys, math
sys.path.insert(0, r"C:\dev\business_plann_app"); sys.path.insert(0, r"C:\dev\business_plann_app\python")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(r"C:\dev\business_plann_app\.env")
import mysql.connector
from client_statements_output_excel.data import draft_data_from_row, values_21
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True); cur.execute("SELECT draft_id, business_name, updated_at, model_input_json, finmo_json FROM intake_consult_drafts WHERE finmo_json IS NOT NULL AND model_input_json IS NOT NULL ORDER BY updated_at DESC"); rows = cur.fetchall()
def excel_round6(x):
    # Excel ROUND = half away from zero on the decimal representation; emulate via Decimal
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(repr(x)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP))
n=0; total_step=0; misses=[]; erepr=[]; offgrid=[]; cats={"oc_pos":[], "oc_neg":[], "oe_step":[], "oe_neg":[], "q1_only":[], "flat":[]}
sinceJul13=[]
for r in rows:
    try:
        d = draft_data_from_row(dict(r)); by = {x.get("label"): values_21(x.get("values")) for x in d.balance_sheet_rows}
    except Exception as e:
        continue
    if by.get("Owner's Capital") is None: continue
    n+=1; did=r["draft_id"][:8]; name=(r.get("business_name") or "")[:30]; stepped=False
    for lab in ("Owner's Capital","Other Equity"):
        eng=[float(v or 0.0) for v in (by.get(lab) or [0.0]*21)]
        for v in eng:
            if excel_round6(v)!=v: offgrid.append((did,lab,v))
        chain=[eng[0]]
        for i in range(1,21):
            delta = eng[i]-eng[i-1]
            if abs(delta)<=1e-9: chain.append(chain[-1])
            else:
                stepped=True
                if 'e' in repr(abs(delta)): erepr.append((did,lab,i,repr(abs(delta))))
                chain.append(excel_round6(chain[-1] + abs(delta)*(1 if delta>0 else -1)))
        mm=[(i,chain[i],eng[i]) for i in range(21) if chain[i]!=eng[i]]
        if mm: misses.append((did,lab,mm[:2]))
        st=[i for i in range(1,21) if abs(eng[i]-eng[i-1])>1e-9]
        neg=[i for i in st if eng[i]<eng[i-1]]
        if lab=="Owner's Capital":
            if st and st!=[1]:
                (cats["oc_neg"] if neg else cats["oc_pos"]).append((did,name,str(r["updated_at"])[:10],st,neg))
            elif st==[1]: cats["q1_only"].append((did,name))
            else: cats["flat"].append((did,name))
        else:
            if st: (cats["oe_neg"] if neg else cats["oe_step"]).append((did,name,str(r["updated_at"])[:10],st,[round(v) for v in eng]))
    if stepped: total_step+=1
    if str(r["updated_at"])[:10] >= "2026-07-13" and stepped: sinceJul13.append(did)
print("drafts with OC row:", n, "| stepping (any step Q1..Q20, OC or OE):", total_step, "| chain misses:", len(misses), "| e-notation deltas:", len(erepr), "| off-6dp-grid engine values:", len(offgrid))
for m in misses[:10]: print("  MISS", m)
for e in erepr[:10]: print("  EREPR", e)
for o in offgrid[:10]: print("  OFFGRID", o)
print("stepping since 07-13:", len(sinceJul13))
for k,v in cats.items(): print(f"{k}: {len(v)}")
print("--- OC negative steppers (all):"); [print("  ",x) for x in cats["oc_neg"]]
print("--- OE steppers (all):"); [print("  ",x) for x in cats["oe_step"]+cats["oe_neg"]]
print("--- OC positive steppers, most recent 40:"); [print("  ",x) for x in cats["oc_pos"][:40]]
