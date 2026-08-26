import os,sys,json,mysql.connector,collections
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from dotenv import load_dotenv; load_dotenv(r'C:\dev\business_plann_app\.env')
c=mysql.connector.connect(host=os.getenv('MYSQL_HOST'),user=os.getenv('MYSQL_USER'),password=os.getenv('MYSQL_PASSWORD'),database=os.getenv('MYSQL_DB'),autocommit=True)
cur=c.cursor(dictionary=True)
cur.execute("SELECT draft_id,business_name,updated_at,payroll_headcount,CHAR_LENGTH(model_input_json) mil,CHAR_LENGTH(finmo_json) fl FROM intake_consult_drafts WHERE payroll_headcount IS NOT NULL AND CHAR_LENGTH(payroll_headcount)>100 AND updated_at >= '2026-07-13' ORDER BY updated_at")
out=[]
for r in cur.fetchall():
    try: rows=[x for x in json.loads(r['payroll_headcount']).get('rows') or [] if isinstance(x,dict)]
    except Exception: continue
    if not rows: continue
    byq=collections.defaultdict(list)
    for x in rows: byq[int(x.get('quarter_index') or 0)].append(x)
    qs=sorted(byq)
    nroles=max(len(v) for v in byq.values())
    # duplicate titles within a quarter (same class+title, different/absent person)
    dup_title=any(len(set((y.get('staffing_class'),y.get('position_title')) for y in v))<len(v) for v in byq.values())
    dup_full=any(len(set((y.get('staffing_class'),y.get('position_title'),y.get('person_name')) for y in v))<len(v) for v in byq.values())
    frac_q=sum(1 for q in qs if any((float(y.get('hires') or 0)%1)!=0 for y in byq[q]))
    nonint=sum(1 for x in rows if (float(x.get('hires') or 0)%1)!=0)
    # roles missing a prior-quarter row (by full key w/ ordinal)
    prior=set(); fb=0
    for q in qs:
        seen=collections.Counter(); keys=set()
        for y in byq[q]:
            bk=(str(y.get('staffing_class') or '').strip(),str(y.get('position_title') or '').strip(),str(y.get('person_name') or '').strip())
            keys.add(bk+(seen[bk],)); seen[bk]+=1
        if q>1: fb+=sum(1 for k in keys if k not in prior)
        prior=keys
    out.append(dict(id=r['draft_id'][:8],name=(r['business_name'] or '')[:28],upd=str(r['updated_at'])[:10],rows=len(rows),nq=len(qs),nroles=nroles,dup_title=dup_title,dup_full=dup_full,frac_q=frac_q,nonint_hire_rows=nonint,fallback=fb,mil=r['mil'],fl=r['fl']))
print("drafts:",len(out))
print("nroles hist:",collections.Counter(o['nroles'] for o in out))
print("dup_title:",sum(o['dup_title'] for o in out),"dup_full:",sum(o['dup_full'] for o in out),"fallback>0:",sum(o['fallback']>0 for o in out))
print("frac_q==nq:",sum(o['frac_q']==o['nq'] for o in out))
print("\n-- 9-12 roles:")
for o in out:
    if 9<=o['nroles']<=12: print(o)
print("\n-- dup_full:")
for o in out:
    if o['dup_full']: print(o)
print("\n-- dup_title only (top 15):")
for o in [o for o in out if o['dup_title'] and not o['dup_full']][:15]: print(o)
print("\n-- fractional hires every quarter (top 15):")
for o in [o for o in out if o['frac_q']==o['nq']][:15]: print(o)
print("\n-- fallback>0:")
for o in out:
    if o['fallback']: print(o)
json.dump(out,open(os.path.join(os.path.dirname(__file__),'pop.json'),'w'))
