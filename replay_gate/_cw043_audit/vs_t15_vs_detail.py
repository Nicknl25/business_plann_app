"""Detail one draft on a tree: named series, supporting totals, payroll vs target."""
import os, sys, json, copy, collections, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT, DRAFT = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(ROOT, "python")); sys.path.insert(0, ROOT)
load_dotenv(r"C:\dev\business_plann_app\.env")
from client_intake_and_finmo.post_intake_headcount import schedule as S
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT draft_id,business_name,payroll_headcount,finmo_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (DRAFT+"%",))
r = cur.fetchall()[0]; cur.close(); c.close()
pay = json.loads(r['payroll_headcount']); fj = json.loads(r['finmo_json'])
tp = float(pay["target_payroll_percent_of_revenue"])
rev = {int(q['quarter_index']): float(q.get('revenue') or 0.0) for q in fj.get('quarter_rows') or []}
anchor = {"labor_intensity_class": pay.get("labor_intensity_class"),
          "per_quarter": [{"q": q, "payroll_budget": rev[q]*tp} for q in sorted(rev) if q>=1]}
def nm(x): return str(x.get("staffing_class") or "").strip().lower()=="key_person"
print(f"{r['draft_id'][:8]} {r['business_name']} target_pct={tp} horizon={pay.get('schedule_horizon_quarters')} rows={len(pay['rows'])} class={pay.get('labor_intensity_class')}")
def series(p, who):
    d = {int(x['quarter_index']): x.get('ending_fte') for x in p['rows'] if nm(x) and x.get('person_name')==who}
    return [d.get(q) for q in range(1,21)]
people = sorted({x.get('person_name') for x in pay['rows'] if nm(x)})
sup_titles = sorted({(x.get('position_title'), x.get('person_name'), x.get('oews_occ_title') or x.get('oews_matched_title')) for x in pay['rows'] if not nm(x)})
print(" named people:", people)
print(" supporting titles:", sup_titles)
for w in people: print("  BEFORE", w, series(pay, w))
def report(tag, work):
    for w in people: print(f"  {tag}", w, series(work, w))
    sup = collections.defaultdict(float); nmd = collections.defaultdict(float); tot = collections.defaultdict(float)
    for x in work['rows']:
        q = int(x['quarter_index']); v = float(x.get('total_quarterly_payroll') or 0)
        tot[q]+=v; (nmd if nm(x) else sup)[q]+=v
    supf = collections.defaultdict(float)
    for x in work['rows']:
        if not nm(x): supf[int(x['quarter_index'])] += float(x.get('ending_fte') or 0)
    print(f"  {tag} supporting ending_fte q1..q6:", [round(supf[q],3) for q in range(1,7)])
    print(f"  {tag} target   q1..q6:", [round(rev[q]*tp) for q in range(1,7)])
    print(f"  {tag} total    q1..q6:", [round(tot[q]) for q in range(1,7)])
    print(f"  {tag} named    q1..q6:", [round(nmd[q]) for q in range(1,7)])
    print(f"  {tag} support  q1..q6:", [round(sup[q]) for q in range(1,7)])
    print(f"  {tag} total-vs-target q1..q6:", [round(tot[q]-rev[q]*tp) for q in range(1,7)])
b = copy.deepcopy(pay); report("BASE  ", b)
for asd in (False, True):
    w = copy.deepcopy(pay)
    s = S.enforce_labor_scaling_on_payload(w, anchor, allow_scale_down=asd)
    print(f" --- allow_scale_down={asd} summary={ {k:v for k,v in (s or {}).items()} }")
    report("AFTER ", w)
