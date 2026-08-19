import json
p = r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json'
out = json.load(open(p))
fin = out['fin']
coh = fin.get('_coherence') or {}
for k in ['status','gap_initial','gap_open','rounds_done','converged_suffix','digest_hash']:
    print(k, '=', json.dumps(coh.get(k)))
print('--- bounds ---')
print(json.dumps(coh.get('bounds'), indent=1))
print('--- corner ---')
print(json.dumps(coh.get('corner'), indent=1))
print('--- margin_band_judgment ---')
print(json.dumps(coh.get('margin_band_judgment'), indent=1)[:2000])
print('--- judged_growth ---')
print(json.dumps(coh.get('judged_growth'), indent=1))
print('--- eval ---')
print(json.dumps(coh.get('eval'), indent=1)[:3000])
print('--- early_eval ---')
print(json.dumps(coh.get('early_eval'), indent=1)[:1500])
print('--- fin fields ---')
for k in sorted(fin.keys()):
    if k != '_coherence':
        v = fin[k]
        print(k, '=', json.dumps(v)[:200])
