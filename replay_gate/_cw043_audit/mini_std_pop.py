"""mini's INDEPENDENT re-derivation of the STD-clip population.

For every stored draft since 07-13 carrying a debt schedule, evaluate BOTH
workbook formulas in Python off the engine's own persisted Debt Schedule rows
(actual_debt_repayment / closing_debt, which is exactly what the Debt sheet
corkscrew reproduces on an untouched schedule):

  OLD cell = SUM(actual repayment, q+1 .. min(q+4, 20))
  NEW cell = MIN(closing_debt[q], OLD)

and compare each against the ENGINE's own Layer 1 short_term_debt for that
quarter (finmo_json.quarter_rows[q].short_term_debt) - that is the equivalence
test (claim a) at population scale, and the error census (claim b).

Visibility: the Checks balance tie-out is written for q_col in
[FIRST_LIVE_COL, LAST_LIVE_COL] only (checks_sheet.py:665) = Q1 and Q20.
"""
import os, sys, json, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(r"C:\dev\business_plann_app\.env")
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'),
                            password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'),
                            autocommit=True)
cur = c.cursor(dictionary=True)
SINCE = sys.argv[1] if len(sys.argv) > 1 else '2026-07-13'
cur.execute(
    "SELECT draft_id, business_name, updated_at, debt_schedule, finmo_json "
    "FROM intake_consult_drafts WHERE debt_schedule IS NOT NULL "
    "AND CHAR_LENGTH(debt_schedule)>100 AND updated_at >= %s ORDER BY updated_at", (SINCE,))
drafts = cur.fetchall(); cur.close(); c.close()

TOL = 0.5
Q = 20
n = n_eng = 0
hits = []            # drafts where OLD != NEW at some quarter
eng_mismatch_new = []  # NEW != engine STD
eng_mismatch_old = []  # OLD != engine STD
for r in drafts:
    try:
        ds = json.loads(r['debt_schedule'])
        rows = ds.get('rows') or []
    except Exception:
        continue
    if not rows:
        continue
    n += 1
    actual = {}; closing = {}
    for x in rows:
        qi = int(x.get('quarter_index') or 0)
        actual[qi] = float(x.get('actual_debt_repayment') or 0.0)
        closing[qi] = float(x.get('closing_debt') or 0.0)
    eng = {}
    try:
        fj = json.loads(r['finmo_json'] or 'null')
        for qr in (fj or {}).get('quarter_rows') or []:
            eng[int(qr.get('quarter_index'))] = float(qr.get('short_term_debt') or 0.0)
    except Exception:
        eng = {}
    if eng: n_eng += 1
    worst = None; bad_q = []; new_miss = []; old_miss = []
    for q in range(1, Q + 1):
        if q not in closing:
            continue
        lo, hi = q + 1, min(q + 4, Q)
        old = sum(actual.get(i, 0.0) for i in range(lo, hi + 1)) if lo <= hi else 0.0
        new = min(closing[q], old) if lo <= hi else 0.0
        err = old - new
        if err > TOL:
            bad_q.append((q, err, old, new))
            if worst is None or err > worst[1]:
                worst = (q, err, old, new)
        if q in eng:
            if abs(new - eng[q]) > TOL: new_miss.append((q, new, eng[q]))
            if abs(old - eng[q]) > TOL: old_miss.append((q, old, eng[q]))
    if bad_q:
        vis = [q for q, *_ in bad_q if q in (1, 20)]
        hits.append(dict(draft=r['draft_id'][:8], name=(r['business_name'] or '')[:34],
                         updated=str(r['updated_at'])[:10], nq=len(bad_q), worst=worst,
                         quarters=[q for q, *_ in bad_q], visible=bool(vis)))
    if new_miss: eng_mismatch_new.append((r['draft_id'][:8], (r['business_name'] or '')[:28], new_miss[:4], len(new_miss)))
    if old_miss: eng_mismatch_old.append((r['draft_id'][:8], (r['business_name'] or '')[:28], old_miss[:4], len(old_miss)))

print(f"drafts scanned (debt schedule, updated >= {SINCE}): {n}   with engine finmo_json: {n_eng}")
print(f"drafts where OLD(sum) != NEW(min): {len(hits)}")
errs = sorted(h['worst'][1] for h in hits)
if errs:
    print(f"  error range ${errs[0]:,.0f} .. ${errs[-1]:,.0f}   median ${errs[len(errs)//2]:,.0f}")
for h in sorted(hits, key=lambda x: -x['worst'][1]):
    q, err, old, new = h['worst']
    print(f"  {h['draft']} {h['name']:<34} {h['updated']}  quarters={h['quarters']}  "
          f"worst Q{q} old={old:,.0f} new={new:,.0f} err=${err:,.0f}  "
          f"VISIBLE(Q1/Q20 tie-out)={h['visible']}")
print()
print(f"NEW formula != engine Layer 1 STD: {len(eng_mismatch_new)} drafts")
for d in eng_mismatch_new[:15]: print("   ", d)
print(f"OLD formula != engine Layer 1 STD: {len(eng_mismatch_old)} drafts")
for d in eng_mismatch_old[:15]: print("   ", d)
