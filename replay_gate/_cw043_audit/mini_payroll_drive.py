"""mini claims (d)+(e): drive enforce_labor_scaling_on_payload from ONE tree on every
stored payroll payload, with an anchor rebuilt independently as
   payroll_budget[q] = revenue[q] (finmo_json.quarter_rows) x target_payroll_percent_of_revenue
Reports, per draft: whether any NAMED (key_person) row's ending_fte moved, the factor
range, whether named full-timers land at 1.0 and stated part-timers keep their fraction,
whether supporting absorbed the delta, and total payroll vs target.

usage: <tree_root> <out.json> [detail_draft_prefix ...]
"""
import os, sys, json, copy, collections, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT, OUT = sys.argv[1], sys.argv[2]
DETAIL = set(sys.argv[3:])
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
def named(r): return str(r.get("staffing_class") or "").strip().lower() == "key_person"
out = {}
n = 0
for r in rows:
    try:
        pay = json.loads(r['payroll_headcount']); fj = json.loads(r['finmo_json'])
    except Exception: continue
    if not (pay.get("rows") and pay.get("quarter_totals")): continue
    tp = pay.get("target_payroll_percent_of_revenue")
    if not isinstance(tp, (int, float)) or tp <= 0: continue
    rev = {int(q['quarter_index']): float(q.get('revenue') or 0.0) for q in fj.get('quarter_rows') or []}
    if not rev: continue
    anchor = {"per_quarter": [{"q": q, "payroll_budget": rev[q] * float(tp)} for q in sorted(rev) if q >= 1],
              "labor_intensity_class": "high"}
    before = copy.deepcopy(pay)
    work = copy.deepcopy(pay)
    try:
        summary = S.enforce_labor_scaling_on_payload(work, anchor, allow_scale_down=(os.environ.get("ASD")=="1"))
    except Exception as e:
        out[r['draft_id'][:8]] = {"error": repr(e)[:90]}; continue
    n += 1
    b_named = {}; a_named = {}
    for x in before["rows"]:
        if named(x): b_named[(x.get("person_name"), x.get("position_title"), int(x.get("quarter_index") or 0))] = float(x.get("ending_fte") or 0)
    for x in work["rows"]:
        if named(x): a_named[(x.get("person_name"), x.get("position_title"), int(x.get("quarter_index") or 0))] = float(x.get("ending_fte") or 0)
    moved = [(k, b_named[k], a_named.get(k)) for k in b_named if a_named.get(k) is not None and abs(b_named[k] - a_named[k]) > 1e-9]
    # named payroll vs target, per quarter, on the RESULT
    tgt = {q: rev[q] * float(tp) for q in rev if q >= 1}
    res_tot = {int(q['quarter_index']): float(q.get('payroll') or 0) for q in work.get("quarter_totals") or []}
    nmd = collections.defaultdict(float); sup = collections.defaultdict(float)
    for x in work["rows"]:
        q = int(x.get("quarter_index") or 0)
        (nmd if named(x) else sup)[q] += float(x.get("total_quarterly_payroll") or 0)
    over = [q for q in sorted(tgt) if q in res_tot and res_tot[q] > tgt[q] + 1.0]
    over_named_only = [q for q in over if nmd.get(q, 0.0) > tgt[q] + 1.0]
    facs = [f for f in (summary or {}).get("factor_by_quarter", {}).values()] if isinstance(summary, dict) else []
    rec = {"name": (r['business_name'] or '')[:34], "named_rows_moved": len(moved),
           "scaled": bool(summary), "over_target_quarters": len(over),
           "over_but_named_alone_exceeds": len(over_named_only),
           "over_unexplained": sorted(set(over) - set(over_named_only))[:4],
           "named_fte_after": sorted({round(v, 4) for v in a_named.values()})[:8],
           "moved_examples": [(k[0], k[2], round(a, 4), round(b, 4)) for k, a, b in moved[:4]]}
    if r['draft_id'][:8] in DETAIL:
        rec["detail_named"] = sorted({(k[0], round(b_named[k],4), round(a_named[k],4)) for k in b_named if k[2] == 1})
        rec["detail_q1"] = {"target": round(tgt.get(1,0)), "total_after": round(res_tot.get(1,0)),
                            "named_after": round(nmd.get(1,0)), "supporting_after": round(sup.get(1,0)),
                            "total_before": round(next((float(q.get('payroll') or 0) for q in before['quarter_totals'] if int(q['quarter_index'])==1), 0))}
    out[r['draft_id'][:8]] = rec
json.dump(out, open(OUT, "w"), indent=0)
mv = [d for d, v in out.items() if v.get("named_rows_moved")]
ov = [d for d, v in out.items() if v.get("over_target_quarters")]
un = [d for d, v in out.items() if v.get("over_unexplained")]
print(f"[{ROOT}] drafts driven={n}")
print(f"  drafts where a NAMED row's FTE MOVED: {len(mv)}")
print(f"  drafts OVER target in >=1 quarter: {len(ov)}")
print(f"  ... of those, quarters where named payroll ALONE exceeds target: explained")
print(f"  drafts with an UNEXPLAINED over-target quarter (named alone does NOT exceed): {len(un)} {un[:8]}")
fteset = collections.Counter()
for v in out.values():
    for f in v.get("named_fte_after") or []: fteset[f] += 1
print(f"  distinct NAMED ending_fte values after the run (top): {fteset.most_common(10)}")
for d in sorted(DETAIL):
    if d in out: print("  DETAIL", d, json.dumps(out[d])[:600])
