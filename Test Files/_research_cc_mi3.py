import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json'
out = json.load(open(p, encoding='utf-8'))
mi = out['model_input']
rev = mi['sections']['revenue']
print('revenue section keys:', list(rev.keys())[:30])
ra = mi['solver_input'].get('revenue_authored')
if ra:
    print('revenue_authored keys:', list(ra.keys()) if isinstance(ra, dict) else type(ra))
    s = json.dumps(ra)
    print(s[:1500])
