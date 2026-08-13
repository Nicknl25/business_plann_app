import json, sys, io, copy
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'c:\dev\business_plann_app\python')
p = r'C:\Users\IGNATI~1\AppData\Local\Temp\claude\c--dev-business-plann-app\71cfaead-171d-4788-845c-04ee287322dc\scratchpad\draft.json'
out = json.load(open(p, encoding='utf-8'))
fin_final = out['fin']; ops_final = out['ops']
coh = fin_final['_coherence']
bounds = coh['bounds']; band = coh['margin_band_judgment']; jg = coh['judged_growth']
from client_intake_and_finmo.intake_coherence import controller as ctl
from client_intake_and_finmo.intake_coherence.evaluator import (
    basis_from_intake, thresholds_from_margin_band, evaluate_structural, growth_multiple_from_judged)
th = thresholds_from_margin_band(band)

def mk_ops(price):
    ops = copy.deepcopy(ops_final); ops['unit_price'] = price
    for lob in ops['lob_models']:
        for pr in lob['products']: pr['unit_price'] = price
    return ops

def mk_fin(ann):
    f = dict(fin_final); f = {k: v for k, v in f.items() if k != '_coherence'}
    f['current_revenue'] = ann
    f['payroll_adjustment'] = 0.0
    return f

# 1. anchor 8339 (actual msg-116 state): gap + new-lines closes
ops112 = mk_ops(112.0)
m = growth_multiple_from_judged(jg, ops_json=ops112)
fin = mk_fin(8339.0)
b = basis_from_intake(financials_json=fin, ops_json=ops112, growth_to_q11=m)
r = evaluate_structural(b, th)
print('anchor 8339: gap =', r['gap_quarterly'], '(panel: 11,319) gna_pct=%.4f' % b.gna_pct)
rnd = ctl.plan_rounds(basis=b, thresholds=th, bounds=bounds, ops_json=ops112,
                      financials_json=fin, rounds_done=['cost_structure','pricing'])
print('round:', rnd['key'], [ (o['id'][:30], o['closes_display']) for o in rnd['options']])

# 2. honest anchors: would the structure have passed?
for price, ann in ((45.0, 49140.0), (60.0, 65520.0), (80.0, 87360.0)):
    o = mk_ops(price); f = mk_fin(ann)
    mm = growth_multiple_from_judged(jg, ops_json=o)
    bb = basis_from_intake(financials_json=f, ops_json=o, growth_to_q11=mm)
    rr = evaluate_structural(bb, th)
    print(f'price ${price:.0f} anchor {ann:,.0f}: passed={rr["passed"]} gap={rr["gap_quarterly"]} ebitda_margin={rr["q11"]["ebitda_margin"]:.3f}')

# 3. physical ceilings table
for price in (45, 60, 80, 108, 112):
    print(f'price ${price}: util-adjusted ceiling ${30*52*0.7*price:,.0f}/yr, max-util ceiling ${30*52*price:,.0f}/yr')
print('stored current_revenue:', fin_final['current_revenue'])
print('implied utilization at $80:', 122304/(30*52*80))
print('implied utilization at $45:', 122304/(30*52*45))
print('delivered Q7+ capacity 406.0/q =', 406.001688/13, 'grooms/week vs stated 30')
