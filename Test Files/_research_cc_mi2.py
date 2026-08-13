import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json'
out = json.load(open(p, encoding='utf-8'))
mi = out['model_input'] or {}
s = json.dumps(mi)
print('len model_input json:', len(s))
# find any capacity/util/price mentions
import re
for key in ('capacity_units_per_period', 'utilization', 'unit_price', 'revenue'):
    idxs = [m.start() for m in re.finditer(key, s)][:5]
    print(key, 'occurrences:', len([m for m in re.finditer(key, s)]))
# sections?
secs = mi.get('sections')
if isinstance(secs, dict):
    print('sections keys:', list(secs.keys()))
si = mi.get('solver_input')
if isinstance(si, dict):
    print('solver_input keys:', list(si.keys())[:40])
