"""RESEARCH (Fetch & Fluff 50658fff): three-way eval of the FIRST-CAPTURE facts.

Reconstructs the financials_json exactly as it stood at the first PASS
(turn 96, "$6,354/q at 26.4%") and runs evaluate_current at:
  - the fence (1.07^10 = 1.9672)   -> what the gate actually used
  - the judged multiple (engine's own proposer with the stored judged rates)
  - flat (growth 1.0)              -> today's scale
Hypothesis split: flat/judged FAIL while fence PASSES on the same facts => (b)
honest facts + fence optimism; even flat PASSING would have meant (a) garbage-in.
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

import mysql.connector

conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!", database="biz_plan_revert")
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT financials_json, operating_model_json, financials_year1_json, people_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    ("50658fff105e480c896f714fa519f22e",),
)
row = cur.fetchone()
fin_now = json.loads(row["financials_json"])
ops_now = json.loads(row["operating_model_json"])
fy1_now = json.loads(row["financials_year1_json"] or "{}")
state = fin_now.get("_coherence") or {}
band = state.get("margin_band_judgment")
judged_growth = state.get("judged_growth")

from client_intake_and_finmo.intake_coherence.controller import evaluate_current
from client_intake_and_finmo.intake_coherence.evaluator import (
    GROWTH_FENCE_Q11,
    growth_multiple_from_judged,
)

# ---- FIRST-CAPTURE financials (turn 53-96 of messages_json, verbatim) ----
fin_first = {
    "current_revenue": 49000.0,          # "$49,000 last year"
    "cogs_percent_of_revenue": 0.12,     # "12%, around $5,900" -> captured $5,880 (12%)
    "baseline_payroll_year1": 24000.0,   # people: Nadia corrected $52,900 -> $24,000
    "payroll_basis_people_roles": fin_now.get("payroll_basis_people_roles"),
    "payroll_adjustment": 0.0,
    "payroll_total_year1": 24000.0,
    "current_payroll": 24000.0,
    "owner_compensation": 2000.0,        # $2,000/month (non-additive: owner in roles)
    "other_operating_expense": 1450.0,   # $1,450/month bills
    "other_opex_absolute": 17400.0,
    "marketing_total_year1": 600.0,
    "monthly_rent_expense": 0.0,
    "total_debt_outstanding": 58000.0,   # van loan
    "current_capex": 0.0,
    "current_num_employees": 1,
}

# First-capture ops: price 45, cap 30/wk, util 0.70, 52 periods.
# Multiple is anchor-scale-invariant; util ramp starts from stated util,
# which is unchanged (0.70) between first capture and now.
ops_first = json.loads(json.dumps(ops_now))
for lob in ops_first.get("lob_models") or []:
    for p in lob.get("products") or []:
        p["unit_price"] = 45.0

mult_first = growth_multiple_from_judged(judged_growth, ops_json=ops_first)
mult_now = growth_multiple_from_judged(judged_growth, ops_json=ops_now)
print(f"judged multiple (first-capture ops price=45): {mult_first}")
print(f"judged multiple (current ops price=112):      {mult_now}")
print(f"fence multiple:                               {GROWTH_FENCE_Q11:.6f}")
print(f"stored judged rates: {judged_growth}")
print()

def show(label, growth):
    r = evaluate_current(
        financials_json=fin_first,
        ops_json=ops_first,
        financials_year1_json=None,
        margin_band=band,
        growth_to_q11=growth,
    )
    q = r["q11"]
    print(f"--- {label} (growth_to_q11={growth if growth else GROWTH_FENCE_Q11:.4f}) ---")
    print(f"  PASSED={r['passed']}  failed={r['failed']}  gap=${r['gap_quarterly']:,.2f}/q")
    print(
        f"  q11: rev={q['revenue']:,.2f} cogs={q['cogs']:,.2f} payroll={q['payroll']:,.2f} "
        f"rent={q['rent']:,.2f} gna={q['gna']:,.2f} mkt={q['marketing']:,.2f}"
    )
    print(
        f"  ebitda={q['ebitda']:,.2f} ({q['ebitda_margin']*100:.2f}%)  "
        f"ni_margin={q['ni_margin']*100:.2f}%  band_floor$={q['band_low_floor_dollars']:,.2f}"
    )
    for name, c in r["checks"].items():
        print(f"    {name:18s} {'PASS' if c['passed'] else 'FAIL'}  value={c['value']:.4f} thr={c['threshold']:.4f}")
    print()
    return r

show("FENCE  (what the gate used at turn 96)", None)
if mult_first:
    show("JUDGED (the walk's own tier)", mult_first)
show("FLAT   (today's scale)", 1.0)

# Sanity: reproduce the stored early_eval / turn-96 numbers exactly?
r_fence = evaluate_current(financials_json=fin_first, ops_json=ops_first,
                           financials_year1_json=None, margin_band=band, growth_to_q11=None)
print("turn-96 quoted: $6,354 at 26.4% | recomputed:",
      f"${r_fence['q11']['ebitda']:,.0f} at {r_fence['q11']['ebitda_margin']*100:.1f}%")
stored_early = (state.get("early_eval") or {}).get("q11") or {}
print("stored early_eval ebitda:", stored_early.get("ebitda"))

# Also: FINAL facts (current draft) at all three growth points, for contrast.
print()
print("=== FINAL facts (current draft, rev $122,304) ===")
for label, g in (("fence", None), ("judged", mult_now), ("flat", 1.0)):
    r = evaluate_current(financials_json=fin_now, ops_json=ops_now,
                         financials_year1_json=fy1_now, margin_band=band, growth_to_q11=g)
    q = r["q11"]
    print(f"  {label:6s}: passed={r['passed']} failed={r['failed']} "
          f"ebitda={q['ebitda']:,.0f} ({q['ebitda_margin']*100:.1f}%) gap=${r['gap_quarterly']:,.0f}/q")
