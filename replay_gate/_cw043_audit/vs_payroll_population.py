"""Population bit-identity for the payroll chain: evaluate, in IEEE doubles, exactly the formulas the builder
emits (Starting = round(prior Ending, 6); wage/benefits = prev or round(prev +/- delta, 6); Ending = start+hires)
for every draft with payroll rows, and compare to the engine's authored values with float equality.
Also reports what a BARE chain (no ROUND) would miss - the class the committed test pins."""
import os,sys,json,mysql.connector,collections
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from dotenv import load_dotenv; load_dotenv(r'C:\dev\business_plann_app\.env')
c=mysql.connector.connect(host=os.getenv('MYSQL_HOST'),user=os.getenv('MYSQL_USER'),password=os.getenv('MYSQL_PASSWORD'),database=os.getenv('MYSQL_DB'),autocommit=True)
cur=c.cursor(dictionary=True)
cur.execute("SELECT draft_id,business_name,updated_at,payroll_headcount FROM intake_consult_drafts WHERE payroll_headcount IS NOT NULL AND CHAR_LENGTH(payroll_headcount)>100 AND updated_at >= '2026-07-13' ORDER BY updated_at")
n=0; miss=0; bare_miss=0; fallback_rows=0; misses=[]; ids=[]
for r in cur.fetchall():
    try: rows=[x for x in json.loads(r['payroll_headcount']).get('rows') or [] if isinstance(x,dict)]
    except Exception: continue
    if not rows: continue
    n+=1; ids.append(r['draft_id'][:8])
    prior={}; bad=[]; bare_bad=0; seen={}; cq=None
    for x in rows:
        q=int(x.get('quarter_index') or 0)
        if q!=cq: cq,seen=q,{}
        bk=(str(x.get('staffing_class') or ''),str(x.get('position_title') or ''),str(x.get('person_name') or ''))
        o=seen.get(bk,0); seen[bk]=o+1; key=bk+(o,)
        s=float(x.get('starting_fte') or 0); h=float(x.get('hires') or 0); w=float(x.get('annual_wage') or 0); b=float(x.get('payroll_taxes_benefits_percent') or 0)
        p=prior.get(key)
        if p and p['q']==q-1:
            start=round(p['end'],6); bare=p['end']
            if start!=s: bad.append(('start',q,s,start))
            if bare!=s: bare_bad+=1
            dw=w-p['w']; ww=p['w'] if abs(dw)<=1e-9 else round(p['w']+dw,6) if dw>0 else round(p['w']-abs(dw),6)
            db=b-p['b']; bb=p['b'] if abs(db)<=1e-9 else round(p['b']+db,6) if db>0 else round(p['b']-abs(db),6)
            if ww!=w: bad.append(('wage',q,w,ww))
            if bb!=b: bad.append(('ben',q,b,bb))
        else:
            if q>1: fallback_rows+=1
            start=s; ww=w; bb=b
        end=start+h
        prior[key]={'q':q,'end':end,'w':ww,'b':bb}
    if bad: miss+=1; misses.append((r['draft_id'][:8],bad[:3]))
    if bare_bad: bare_miss+=1
print(f"drafts with payroll rows: {n} | chain != engine (bit): {miss} | drafts a BARE (no ROUND) chain would miss: {bare_miss} | fallback rows: {fallback_rows}")
for m in misses[:8]: print("  MISS",m)
open(r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\1b5df2b9-512c-4fc5-bfdd-b10c0712b978\scratchpad\payroll_ids.txt','w').write(' '.join(ids))
cur.close(); c.close()
