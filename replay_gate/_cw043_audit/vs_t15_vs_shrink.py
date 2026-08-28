import os, sys, json, copy, collections, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT, ASD = sys.argv[1], sys.argv[2]=="1"
sys.path.insert(0, os.path.join(ROOT, "python")); sys.path.insert(0, ROOT)
load_dotenv(r"C:\dev\business_plann_app\.env")
from client_intake_and_finmo.post_intake_headcount import schedule as S
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT draft_id,business_name,payroll_headcount,finmo_json FROM intake_consult_drafts WHERE payroll_headcount IS NOT NULL AND CHAR_LENGTH(payroll_headcount)>100 AND finmo_json IS NOT NULL ORDER BY updated_at")
rows = cur.fetchall(); cur.close(); c.close()
def nm(x): return str(x.get("staffing_class") or "").strip().lower()=="key_person"
shrunk_ft = []; grew_ft = []; worst_lo = (9.9, None); worst_hi = (0.0, None)
for r in rows:
    try: pay = json.loads(r['payroll_headcount']); fj = json.loads(r['finmo_json'])
    except Exception: continue
    if not (pay.get("rows") and pay.get("quarter_totals")): continue
    tp = pay.get("target_payroll_percent_of_revenue")
    if not isinstance(tp,(int,float)) or tp<=0: continue
    rev = {int(q['quarter_index']): float(q.get('revenue') or 0.0) for q in fj.get('quarter_rows') or []}
    if not rev: continue
    anchor = {"labor_intensity_class": pay.get("labor_intensity_class"),
              "per_quarter":[{"q":q,"payroll_budget":rev[q]*float(tp)} for q in sorted(rev) if q>=1]}
    before = {(x.get('person_name'),int(x['quarter_index'])): float(x.get('ending_fte') or 0) for x in pay['rows'] if nm(x)}
    w = copy.deepcopy(pay)
    try: S.enforce_labor_scaling_on_payload(w, anchor, allow_scale_down=ASD)
    except Exception: continue
    after = {(x.get('person_name'),int(x['quarter_index'])): float(x.get('ending_fte') or 0) for x in w['rows'] if nm(x)}
    d = r['draft_id'][:8]
    lo = [(k,before[k],after[k]) for k in before if abs(before[k]-1.0)<1e-9 and after.get(k,1.0) < 0.999]
    hi = [(k,before[k],after[k]) for k in before if abs(before[k]-1.0)<1e-9 and after.get(k,1.0) > 1.001]
    if lo:
        shrunk_ft.append((d, r['business_name'], min(x[2] for x in lo)))
        m = min(x[2] for x in lo)
        if m < worst_lo[0]: worst_lo = (m, (d, r['business_name'], [x for x in lo if x[2]==m][:1]))
    if hi:
        grew_ft.append((d, r['business_name'], max(x[2] for x in hi)))
        m = max(x[2] for x in hi)
        if m > worst_hi[0]: worst_hi = (m, (d, r['business_name'], [x for x in hi if x[2]==m][:1]))
print(f"ASD={ASD}: drafts with a named FULL-TIMER SHRUNK below 1.0: {len(shrunk_ft)}; GROWN above 1.0: {len(grew_ft)}")
print("  worst shrink:", worst_lo)
print("  worst growth:", worst_hi)
print("  shrink examples:", shrunk_ft[:8])
