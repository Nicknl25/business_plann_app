import mysql.connector, json, sys
conn = mysql.connector.connect(host='localhost', user='root', password='Lovers251979!', database='biz_plan_revert')
cur = conn.cursor()
DID = '50658fff105e480c896f714fa519f22e'
cur.execute("""SELECT operating_model_json, financials_json, financials_year1_json, repair_guidance_json, model_input_json, business_name, revenue_model_json FROM intake_consult_drafts WHERE draft_id=%s""", (DID,))
row = cur.fetchone()
names = ['ops','fin','fin_y1','repair','model_input','name','revenue_model']
out = {}
for n, v in zip(names, row):
    if n == 'name':
        out[n] = v
        continue
    try:
        out[n] = json.loads(v) if v else None
    except Exception as e:
        out[n] = f'<unparseable: {e}>'
print('business:', out['name'])
with open(r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json', 'w') as f:
    json.dump(out, f, indent=1, default=str)
# quick summaries
fin = out['fin'] or {}
print('current_revenue:', fin.get('current_revenue'))
print('_coherence keys:', list((fin.get('_coherence') or {}).keys()))
ops = out['ops'] or {}
print('ops keys:', list(ops.keys())[:30])
for lob in ops.get('lob_models') or []:
    print('LOB:', lob.get('lob_name'))
    for p in lob.get('products') or []:
        print('  product:', json.dumps(p))
rep = out['repair'] or {}
coh = rep.get('coherence') or {}
print('coherence keys:', list(coh.keys()))
print('coherence status:', coh.get('status'))
