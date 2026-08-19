"""Offline replay of the Fetch & Fluff coherence walk (draft 50658fff...).
Reconstructs the msg-114 state (pricing round) and msg-116 state (new-lines
round) and computes the closes numbers the controller produced. RESEARCH ONLY."""
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
    basis_from_intake, thresholds_from_margin_band, evaluate_structural,
    growth_multiple_from_judged, GROWTH_FENCE_Q11)

def mk_ops(price):
    ops = copy.deepcopy(ops_final)
    ops['unit_price'] = price
    for lob in ops['lob_models']:
        for pr in lob['products']:
            pr['unit_price'] = price
    return ops

def mk_fin(ann_rev):
    return {
        'current_revenue': ann_rev,
        'cogs_percent_of_revenue': 0.12,
        'current_cogs': 5900.0,
        'baseline_payroll_year1': 24000.0,
        'payroll_adjustment': 0.0,
        'owner_compensation': 3300,
        'payroll_basis_people_roles': fin_final['payroll_basis_people_roles'],
        'other_opex_absolute': 17400.0,
        'other_operating_expense': 1450,
        'marketing_total_year1': 600.0,
        'monthly_rent_expense': 0.0,
        'total_debt_outstanding': 58000.0,
        'current_capex': 0.0,
        '_coherence': {'client_floors': {}},
    }

ops80 = mk_ops(80.0)
m = growth_multiple_from_judged(jg, ops_json=ops80)
print('judged growth multiple Q1->Q11 =', m)
th = thresholds_from_margin_band(band)

def gap_of(fin, ops, growth):
    b = basis_from_intake(financials_json=fin, ops_json=ops, growth_to_q11=growth)
    r = evaluate_structural(b, th)
    return b, r

# ---- calibrate the msg-114 anchor: find ann_rev giving gap 12,357 ----
for cand in (4466.0, 4468.48, 3351.36*4/3):
    fin = mk_fin(cand)
    b, r = gap_of(fin, ops80, m)
    print(f'anchor {cand:.2f}: gap={r["gap_quarterly"]}, failed={r["failed"]}')

# use the custom-price-scaled value
ANN0 = 3351.36 * 4/3
fin0 = mk_fin(ANN0)
b0, r0 = gap_of(fin0, ops80, m)
print('\n=== msg-114 state: anchor', round(ANN0,2), 'gap', r0['gap_quarterly'], 'binding', r0['failed'])
print('basis: q1_rev/q %.2f cogs_pct %.4f gna_pct %.4f mkt_pct %.4f payroll/q %.2f' % (
    b0.q1_revenue_quarterly, b0.cogs_pct, b0.gna_pct, b0.marketing_pct, b0.payroll_quarterly))

rnd = ctl.plan_rounds(basis=b0, thresholds=th, bounds=bounds, ops_json=ops80,
                      financials_json=fin0, rounds_done=['cost_structure'])
print('\nround key:', rnd['key'] if rnd else None)
if rnd and rnd['key'] == 'pricing':
    for o in rnd['options']:
        print(' option', o['id'], 'label', o['label'], 'prices',
              [(pp['from'], pp['to']) for pp in o['prices']],
              'closes =', o['closes_display'],
              'patch current_revenue =', o['patch']['current_revenue'])
    print(' facts:', rnd['facts'])

    # dissect WHY closes = 0 for pricing_mid
    from client_intake_and_finmo.intake_coherence.controller import _price_move_basis, _gap
    split = ctl.ops_line_split(ops80, fin0)
    print('\nsplit:', split)
    mults = {f"{split[0]['lob']}\u241f{split[0]['product']}": 1.4}
    moved = _price_move_basis(b0, split, mults)
    rm = evaluate_structural(moved, th)
    print('projected moved basis: q1_rev %.2f cogs_pct %.4f gna_pct %.4f(HELD) mkt_pct %.4f(HELD)' % (
        moved.q1_revenue_quarterly, moved.cogs_pct, moved.gna_pct, moved.marketing_pct))
    print('projected gap after move:', rm['gap_quarterly'], 'failed:', rm['failed'])
    print('=> closes = gap_now - projected = %.2f - %.2f = %.2f -> max(0,.)=%.2f' % (
        r0['gap_quarterly'], rm['gap_quarterly'],
        r0['gap_quarterly'] - rm['gap_quarterly'], max(0.0, r0['gap_quarterly']-rm['gap_quarterly'])))

    # what ACTUALLY happened on accept: patch applied, re-eval from fields
    accept_rev = rnd['options'][0]['patch']['current_revenue']
    fin1 = mk_fin(accept_rev)
    ops112 = mk_ops(112.0)
    b1, r1 = gap_of(fin1, ops112, m)
    print('\n=== after accepting $112: anchor', accept_rev)
    print('realized basis: gna_pct %.4f (was %.4f in projection) mkt_pct %.4f cogs_pct %.4f' % (
        b1.gna_pct, moved.gna_pct, b1.marketing_pct, b1.cogs_pct))
    print('realized gap:', r1['gap_quarterly'], ' (panel showed 11,319; realized closure = %.2f, projected closes was $0)'
          % (r0['gap_quarterly'] - r1['gap_quarterly']))

    # ---- msg-116: new-lines round on the post-accept state ----
    rnd2 = ctl.plan_rounds(basis=b1, thresholds=th, bounds=bounds, ops_json=ops112,
                           financials_json=fin1, rounds_done=['cost_structure', 'pricing'])
    print('\n=== msg-116 round:', rnd2['key'] if rnd2 else None)
    if rnd2:
        for o in rnd2['options']:
            print(' option', o['id'], 'gm', o.get('gross_margin_pct'), 'cap/q', o.get('q11_quarterly_revenue_max'),
                  'closes =', o.get('closes_display'))
        # dissect one
        gna, mkt = b1.gna_pct, b1.marketing_pct
        for nl in bounds['new_line_candidates']:
            cap, gm = nl['q11_quarterly_revenue_max'], nl['gross_margin_pct']
            ed = cap*gm - cap*(gna+mkt)
            fd = th.band_low*cap
            print('  %-45s ebitda_delta=%.2f (gm %.2f - gna %.4f - mkt %.4f) floor_delta=%.2f closes=%.2f' % (
                nl['product'][:45], ed, gm, gna, mkt, fd, max(0.0, ed-fd)))
