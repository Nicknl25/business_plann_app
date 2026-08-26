"""mini's population re-run, written independently: evaluate the emitted chain in doubles per draft; count misses for
the ROUNDed chain, for a BARE FTE chain, and for a BARE wage/benefits chain; count fallback rows under the full key and
under the title-only key. usage: [draft_prefix to detail...]"""
import os, sys, json, collections, mysql.connector
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv(r'C:\dev\business_plann_app\.env')
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
cur.execute("SELECT draft_id, payroll_headcount FROM intake_consult_drafts WHERE payroll_headcount IS NOT NULL AND CHAR_LENGTH(payroll_headcount)>100 AND updated_at >= '2026-07-13' ORDER BY updated_at")
detail = set(sys.argv[1:])
N = miss = bare_fte_miss = bare_wage_miss = fb_full = fb_title = 0
per = {}
for r in cur.fetchall():
    try: rows = [x for x in json.loads(r['payroll_headcount']).get('rows') or [] if isinstance(x, dict)]
    except Exception: continue
    if not rows: continue
    N += 1
    byq = collections.defaultdict(list)
    for x in rows: byq[int(x.get('quarter_index') or 0)].append(x)
    state = {}; tstate = {}; bad = []; bfte = bwage = 0; fbf = fbt = 0
    for q in sorted(byq):
        cnt = collections.Counter(); nstate = {}; tkeys = set()
        for x in byq[q]:
            bk = (str(x.get('staffing_class') or '').strip(), str(x.get('position_title') or '').strip(), str(x.get('person_name') or '').strip())
            k = bk + (cnt[bk],); cnt[bk] += 1
            tk = (bk[0], x.get('position_title') or x.get('person_name') or '')
            if q > 1 and tk not in tstate: fbt += 1
            tkeys.add(tk)
            s, h, w, b = (float(x.get(f) or 0) for f in ('starting_fte', 'hires', 'annual_wage', 'payroll_taxes_benefits_percent'))
            p = state.get(k)
            if p is None:
                if q > 1: fbf += 1
                cs, cw, cb = s, w, b
            else:
                cs = round(p[0], 6)
                if p[0] != s: bfte += 1
                dw = w - p[1]; cw = p[1] if abs(dw) <= 1e-9 else round(p[1] + dw, 6)
                db = b - p[2]; cb = p[2] if abs(db) <= 1e-9 else round(p[2] + db, 6)
                if abs(dw) > 1e-9 and p[1] + dw != w: bwage += 1
                if abs(db) > 1e-9 and p[2] + db != b: bwage += 1
                if cs != s: bad.append(('fte', q, s, cs))
                if cw != w: bad.append(('wage', q, w, cw))
                if cb != b: bad.append(('ben', q, b, cb))
            nstate[k] = (cs + h, cw, cb)
        state = nstate; tstate = {t: 1 for t in tkeys}
    if bad: miss += 1
    if bfte: bare_fte_miss += 1
    if bwage: bare_wage_miss += 1
    fb_full += fbf; fb_title += fbt
    per[r['draft_id'][:8]] = dict(bad=bad[:3], bare_fte_rows=bfte, bare_wage_rows=bwage, fb_full=fbf, fb_title=fbt)
print(f"drafts={N} rounded-chain misses={miss} | drafts a BARE FTE chain would miss={bare_fte_miss} | drafts a BARE wage/benefits chain would miss={bare_wage_miss} | fallback rows full-key={fb_full} title-only-key={fb_title}")
for d in detail: print(" ", d, per.get(d))
