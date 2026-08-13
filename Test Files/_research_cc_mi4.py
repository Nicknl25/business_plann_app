import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json'
out = json.load(open(p, encoding='utf-8'))
mi = out['model_input']
rev = mi['sections']['revenue']
print('n rows:', len(rev))
r0 = rev[0]
print('row keys:', list(r0.keys()))
for r in rev[:3]:
    print({k: r.get(k) for k in list(r0.keys())[:12]})
ra = mi['solver_input'].get('revenue_authored')
print('\nrevenue_authored:', json.dumps(ra)[:2000] if ra else None)
