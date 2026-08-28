"""Pick fixture candidates: drafts where the REVERTED tree moves a named person and
HEAD does not. usage: select.py <tree_root> <out.json> <ASD 0|1>"""
import os, sys, json, copy, collections, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT, OUT, ASD = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
sys.path.insert(0, os.path.join(ROOT, "python")); sys.path.insert(0, ROOT)
load_dotenv(r"C:\dev\business_plann_app\.env")
from client_intake_and_finmo.post_intake_headcount import schedule as S
assert os.path.abspath(S.__file__).lower().startswith(os.path.abspath(ROOT).lower()), S.__file__
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT draft_id,business_name,payroll_headcount,finmo_json FROM intake_consult_drafts "
            "WHERE payroll_headcount IS NOT NULL AND CHAR_LENGTH(payroll_headcount)>100 "
            "AND finmo_json IS NOT NULL ORDER BY updated_at")
rows = cur.fetchall(); cur.close(); c.close()
def nm(x): return str(x.get("staffing_class") or "").strip().lower() == "key_person"
out = {}
for r in rows:
    try:
        pay = json.loads(r['payroll_headcount']); fj = json.loads(r['finmo_json'])
    except Exception: continue
    if not (pay.get("rows") and pay.get("quarter_totals")): continue
    tp = pay.get("target_payroll_percent_of_revenue")
    if not isinstance(tp, (int, float)) or tp <= 0: continue
    rev = {int(q['quarter_index']): float(q.get('revenue') or 0.0) for q in fj.get('quarter_rows') or []}
    if not rev: continue
    anchor = {"labor_intensity_class": pay.get("labor_intensity_class"),
              "per_quarter": [{"q": q, "payroll_budget": rev[q]*float(tp)} for q in sorted(rev) if q>=1]}
    before = {(x.get("person_name"), x.get("position_title"), int(x.get("quarter_index") or 0)): float(x.get("ending_fte") or 0)
              for x in pay["rows"] if nm(x)}
    sup_before = collections.defaultdict(float)
    for x in pay["rows"]:
        if not nm(x): sup_before[int(x.get("quarter_index") or 0)] += float(x.get("ending_fte") or 0)
    work = copy.deepcopy(pay)
    try:
        summ = S.enforce_labor_scaling_on_payload(work, anchor, allow_scale_down=ASD)
    except Exception as e:
        continue
    after = {(x.get("person_name"), x.get("position_title"), int(x.get("quarter_index") or 0)): float(x.get("ending_fte") or 0)
             for x in work["rows"] if nm(x)}
    sup_after = collections.defaultdict(float)
    for x in work["rows"]:
        if not nm(x): sup_after[int(x.get("quarter_index") or 0)] += float(x.get("ending_fte") or 0)
    moved = {k: (before[k], after[k]) for k in before if abs(before[k]-after.get(k, before[k])) > 1e-9}
    fulls = sorted({b for k,b in before.items() if abs(b-1.0) < 1e-9})
    ft_moved = {k: v for k,v in moved.items() if abs(v[0]-1.0) < 1e-9}
    pt_moved = {k: v for k,v in moved.items() if abs(v[0]-1.0) >= 1e-9}
    out[r['draft_id'][:8]] = {
        "name": (r['business_name'] or '')[:32],
        "scaled": bool(summ), "rows": len(pay["rows"]),
        "named_people": sorted({k[0] for k in before}),
        "sup_titles": len({(x.get("position_title"), x.get("person_name")) for x in pay["rows"] if not nm(x)}),
        "ft_moved_cells": len(ft_moved), "pt_moved_cells": len(pt_moved),
        "ft_moved_ex": [[k[0], k[2], round(v[0],3), round(v[1],3)] for k,v in list(ft_moved.items())[:3]],
        "pt_moved_ex": [[k[0], k[2], round(v[0],3), round(v[1],3)] for k,v in list(pt_moved.items())[:3]],
        "sup_q1": [round(sup_before.get(1,0),3), round(sup_after.get(1,0),3)],
        "sup_moved_q": sum(1 for q in sup_before if abs(sup_before[q]-sup_after.get(q,0))>1e-9),
        "max_f": (summ or {}).get("max_scale_factor"), "min_f": (summ or {}).get("min_scale_factor"),
    }
json.dump(out, open(OUT, "w"), indent=0)
print(f"[{ROOT}] ASD={ASD} drafts={len(out)}")
print("  ft moved:", sum(1 for v in out.values() if v['ft_moved_cells']),
      " pt moved:", sum(1 for v in out.values() if v['pt_moved_cells']))
