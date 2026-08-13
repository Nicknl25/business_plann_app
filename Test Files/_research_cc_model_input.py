import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json'
out = json.load(open(p, encoding='utf-8'))
mi = out['model_input'] or {}
print('model_input keys:', list(mi.keys())[:40])
drv = mi.get('revenue_drivers') or (mi.get('drivers') or {})
def find_lines(obj, depth=0):
    if depth > 4: return None
    if isinstance(obj, dict):
        if 'lines_of_business' in obj: return obj['lines_of_business']
        for v in obj.values():
            r = find_lines(v, depth+1)
            if r is not None: return r
    return None
lines = find_lines(mi)
if lines:
    for line in lines:
        qs = line.get('quarters') or []
        print('LOB:', line.get('lob_name'))
        for q in qs:
            qq = q.get('q'); cap = q.get('capacity_units_per_period'); pr = q.get('unit_price'); ut = q.get('utilization_rate')
            if qq in (1,2,3,11,20):
                rev = (cap or 0)*(pr or 0)*(ut or 0)
                print(f'  q{qq}: cap={cap} price={pr} util={ut} rev={rev:,.2f}')
else:
    print('no lines_of_business found in model_input; searching finmo')
    fm = out.get('revenue_model')
    print('revenue_model:', json.dumps(fm)[:500] if fm else None)
