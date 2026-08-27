"""mini claim (a) on data: the engine's ITERATIVE clip vs the workbook's CLOSED FORM,
both evaluated on the SAME persisted Debt Schedule snapshot (no stale finmo_json).

engine walk (finmo_model.py:541-551), verbatim:
    S = closing[q]; std = 0
    for i in q+1 .. min(q+4, 20):
        r = max(0, requested_repayment[i]); a = min(r, max(0, S))
        std += a; S = max(0, S - a)
closed form (finmo_sheet.py:_short_term_debt_formula):
    MIN(closing[q], SUM(actual_repayment[q+1 .. min(q+4,20)]))

Also reports the two sub-cases the task names: PARTIAL clip (window only partly
taken) and RE-BORROW inside the window (issuance > 0 after the anchor quarter).
"""
import os, sys, json, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(r"C:\dev\business_plann_app\.env")
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'),
                            password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT draft_id, business_name, debt_schedule FROM intake_consult_drafts "
            "WHERE debt_schedule IS NOT NULL AND CHAR_LENGTH(debt_schedule)>100 "
            "AND updated_at >= '2026-05-01' ORDER BY updated_at")
drafts = cur.fetchall(); cur.close(); c.close()
Q = 20; TOL = 1e-6
n = cells = mism = 0
partial = reborrow = full_clip = 0
mism_rows = []; partial_ex = []; reborrow_ex = []
for r in drafts:
    try: rows = json.loads(r['debt_schedule']).get('rows') or []
    except Exception: continue
    if not rows: continue
    n += 1
    req = {}; act = {}; clo = {}; new = {}
    for x in rows:
        qi = int(x.get('quarter_index') or 0)
        req[qi] = float(x.get('requested_debt_repayment') or 0.0)
        act[qi] = float(x.get('actual_debt_repayment') or 0.0)
        clo[qi] = float(x.get('closing_debt') or 0.0)
        new[qi] = float(x.get('actual_debt_issuance') or x.get('new_borrowing') or 0.0)
    for q in range(1, Q + 1):
        if q not in clo: continue
        lo, hi = q + 1, min(q + 4, Q)
        if lo > hi: continue
        cells += 1
        S = clo[q]; walk = 0.0; took = []
        for i in range(lo, hi + 1):
            rr = max(0.0, req.get(i, 0.0)); a = min(rr, max(0.0, S))
            walk += a; took.append(a < rr - TOL); S = max(0.0, S - a)
        closed = min(clo[q], sum(act.get(i, 0.0) for i in range(lo, hi + 1)))
        if any(took) and walk > TOL: full_clip += 1
        if any(took) and walk > TOL and walk < sum(max(0.0, req.get(i,0.0)) for i in range(lo,hi+1)) - TOL:
            partial += 1
            if len(partial_ex) < 6: partial_ex.append((r['draft_id'][:8], (r['business_name'] or '')[:26], q, clo[q], [req.get(i,0.0) for i in range(lo,hi+1)], walk, closed))
        if any(new.get(i, 0.0) > 0.0 for i in range(lo, hi + 1)):
            reborrow += 1
            if len(reborrow_ex) < 6: reborrow_ex.append((r['draft_id'][:8], (r['business_name'] or '')[:26], q, clo[q], [new.get(i,0.0) for i in range(lo,hi+1)], [act.get(i,0.0) for i in range(lo,hi+1)], walk, closed))
        if abs(walk - closed) > 0.005:
            mism += 1
            if len(mism_rows) < 25:
                mism_rows.append((r['draft_id'][:8], (r['business_name'] or '')[:26], q, clo[q],
                                  [req.get(i,0.0) for i in range(lo,hi+1)], [act.get(i,0.0) for i in range(lo,hi+1)], walk, closed))
print(f"drafts={n}  STD cells evaluated={cells}")
print(f"CLOSED FORM != ENGINE WALK: {mism} cells   <-- claim (a)")
for m in mism_rows: print("   MISMATCH", m)
print(f"cells where the walk CLIPPED at all: {full_clip}")
print(f"cells where the clip was PARTIAL (window only partly taken): {partial}")
for e in partial_ex: print("   partial:", e)
print(f"cells with a RE-BORROW inside the window (issuance>0 after the anchor): {reborrow}")
for e in reborrow_ex[:4]: print("   reborrow:", e)
