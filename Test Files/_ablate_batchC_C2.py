"""ABLATION BATCH C — C2: burden x1.22 landed-payroll ablation + coherence
burden-factor conflict test. In-memory only. Peachtree real data."""
import json, os, sys
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

DRAFT = "f62e846077ef40ca96f37edafb97a6fe"
conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!", database="biz_plan_revert")
cur = conn.cursor(dictionary=True)
cur.execute("""SELECT model_input_json, financials_json, financials_year1_json,
    operating_model_json, payroll_headcount, people_json FROM intake_consult_drafts WHERE draft_id=%s""", (DRAFT,))
r = cur.fetchone()
conn.close()
mi = json.loads(r["model_input_json"]); fin = json.loads(r["financials_json"])
fy1 = json.loads(r["financials_year1_json"]) if r["financials_year1_json"] else {}
ops = json.loads(r["operating_model_json"]) if r["operating_model_json"] else {}
ph = json.loads(r["payroll_headcount"])

print("=== C2a: LANDED PAYROLL, burden ablation (static recompute of the shipped schedule) ===")
rows = ph.get("rows") or []
wage_cost_by_q = {}
for row in rows:
    q = int(row.get("quarter_index") or 0)
    wage_cost_by_q[q] = wage_cost_by_q.get(q, 0) + int(row.get("quarterly_wage_cost") or 0)
q1_wages = wage_cost_by_q.get(1, 0)
total_wages = sum(wage_cost_by_q.values())
for b in (0.0, 0.22, 0.35):
    print(f"  burden={b:.2f}: Q1 landed payroll={round(q1_wages*(1+b)):,}  20q total={round(total_wages*(1+b)):,}"
          f"  (delta vs 0.22: Q1 {round(q1_wages*(1+b))-round(q1_wages*1.22):+,}, 20q {round(total_wages*(1+b))-round(total_wages*1.22):+,})")
print(f"  shipped quarter_totals 20q sum = {sum(int(q.get('payroll') or 0) for q in ph.get('quarter_totals') or []):,} (should match burden=0.22 recompute)")
print(f"  stated payroll_total_year1 = {fin.get('payroll_total_year1'):,}  -> Q1 landed {round(q1_wages*1.22):,} (engine right-sized wages so LOADED cost hits the stated total)")

print("\n=== C2b: WHERE payroll_burden_factor FLOWS in intake_coherence ===")
print("  grep truth: controller.py:551 passes payroll_burden_factor=1.0 into favorable_corner_basis() ONLY (corner_check).")
print("  evaluator.evaluate_structural / basis_from_intake NEVER see a burden factor: the main five gate checks use")
print("  stated baseline_payroll_year1 (+adjustment) unloaded. Corner math scales bounds.team.min_annual_payroll by bf.")
print("  Contrast: restructure searcher.py:674 computes bf = engine annual_payroll / stated wages from REAL data.")

from client_intake_and_finmo.intake_coherence import controller as _ctl
from client_intake_and_finmo.intake_coherence.evaluator import (
    growth_multiple_from_judged, favorable_corner_basis, evaluate_structural,
    thresholds_from_margin_band, basis_from_intake, GROWTH_FENCE_Q11,
)

state = (fin.get("_coherence") or {})
band = state.get("margin_band_judgment")
judged_growth = state.get("judged_growth")
bounds = state.get("bounds")
print(f"\n  coherence state present: band={bool(band)} judged_growth={bool(judged_growth)} bounds={bool(bounds)} status={state.get('status')}")

growth_mult = None
try:
    growth_mult = growth_multiple_from_judged(judged_growth, ops_json=ops)
except Exception as e:
    print("  growth multiple unavailable:", type(e).__name__, str(e)[:120])

def run_eval(scale, growth):
    fin2 = dict(fin)
    base = float(fin2.get("baseline_payroll_year1") or 0.0)
    fin2["baseline_payroll_year1"] = base * scale
    return _ctl.evaluate_current(financials_json=fin2, ops_json=ops,
                                 financials_year1_json=fy1, margin_band=band, growth_to_q11=growth)

for label, growth in [("fence", None), (f"judged x{growth_mult:.4f}" if growth_mult else "judged (n/a)", growth_mult)]:
    if growth is None and label != "fence":
        continue
    for scale, sl in [(1.0, "bf=1.0 (live)"), (1.22, "bf=1.22 (ablated: loaded basis)")]:
        res = run_eval(scale, growth)
        if res is None:
            print(f"  eval[{label}][{sl}]: None"); continue
        print(f"  eval[{label}][{sl}]: passed={res['passed']} failed={res['failed']} gap_q=${res['gap_quarterly']:,.0f} "
              f"payroll_q=${res['q11']['payroll']:,.0f} ebitda_q=${res['q11']['ebitda']:,.0f} ebitda_margin={res['q11']['ebitda_margin']:.4f}")

print("\n=== C2c: CORNER math bf sensitivity (the ONLY coherence site the factor reaches) ===")
if bounds:
    thresholds = thresholds_from_margin_band(band)
    basis = basis_from_intake(financials_json=fin, ops_json=ops, financials_year1_json=fy1, growth_to_q11=GROWTH_FENCE_Q11)
    split = _ctl.ops_line_split(ops, fin)
    corner_split = []
    from client_intake_and_finmo.intake_coherence.controller import match_bounds_lines
    for line, bl in zip(split, match_bounds_lines(split, bounds)):
        corner_split.append({
            "q1_revenue_quarterly": line["q1_revenue_quarterly"],
            "price_multiplier_max": float((bl or {}).get("price_multiplier_max") or 1.0),
            "volume_multiplier_max": float((bl or {}).get("volume_multiplier_max") or 1.0),
        })
    for bf in (1.0, 1.22):
        corner = favorable_corner_basis(basis, bounds, existing_line_revenue_split=corner_split or None, payroll_burden_factor=bf)
        res = evaluate_structural(corner, thresholds)
        print(f"  corner[bf={bf}]: passed={res['passed']} failed={res['failed']} payroll_floor_q=${corner.payroll_quarterly:,.0f} gap_q=${res['gap_quarterly'] or 0:,.0f}")
    print(f"  bounds.team.min_annual_payroll = {((bounds.get('team') or {}).get('min_annual_payroll'))}")
else:
    print("  no bounds in coherence state (Peachtree passed without walking) -> corner path never executed on this run;")
    print("  bf therefore touched NOTHING on this run. Synthetic corner check with placeholder team floor:")
    thresholds = thresholds_from_margin_band(band)
    basis = basis_from_intake(financials_json=fin, ops_json=ops, financials_year1_json=fy1, growth_to_q11=GROWTH_FENCE_Q11)
    if basis is not None:
        synth_bounds = {"team": {"min_annual_payroll": float(fin.get("baseline_payroll_year1") or 0.0) * 0.8}}
        for bf in (1.0, 1.22):
            corner = favorable_corner_basis(basis, synth_bounds, payroll_burden_factor=bf)
            res = evaluate_structural(corner, thresholds)
            print(f"    synth corner[bf={bf}]: passed={res['passed']} payroll_floor_q=${corner.payroll_quarterly:,.0f} failed={res['failed']}")
