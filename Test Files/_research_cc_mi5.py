import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json'
out = json.load(open(p, encoding='utf-8'))
mi = out['model_input']
rev = mi['sections']['revenue']
for i, r in enumerate(rev):
    vals = r.get('values')
    drv = r.get('driver')
    print(i, 'driver:', drv, 'value_kind:', r.get('value_kind'), 'capacity_shaping:', str(r.get('capacity_shaping'))[:120])
    if isinstance(vals, dict):
        qs = sorted(vals.items(), key=lambda kv: kv[0])
        print('   values sample:', {k: vals[k] for k in list(vals)[:6]})
    elif isinstance(vals, list):
        print('   values:', vals[:12])
# quarterly revenue check
print('\nfinmo present?', bool(out.get('fin') and out['fin'].get('_coherence')))
