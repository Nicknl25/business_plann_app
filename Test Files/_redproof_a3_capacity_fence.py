"""RED-PROOF A3 (#101, CW-022 Fetch & Fluff): a plan can PASS the coherence
verdict on volume ABOVE the client's stated capacity.

PRODUCTION CALL CHAIN (named first, per the E2E law):
  intake_consult completion attempt / every turn
    -> intake_coherence.section.gate_and_turn        (gate entry, verdict)
    -> intake_coherence.section.refresh_eval_stamps  (per-turn restamp, same tiers)
    -> controller.evaluate_current
    -> evaluator.basis_from_intake  (growth multiple lives HERE)
    -> evaluator.evaluate_structural
  and the stamp lands in financials_json['_coherence']['eval'].

REAL SHAPE: draft 50658fff (Fetch & Fluff) - the FIRST-CAPTURE facts exactly
as they stood at the turn-96 PASS ("$6,354/q at 26.4%", reproduced to the
cent by _research_ft_first_capture_eval.py), the draft's own stored ops
model (30 grooms/wk, 52 periods, util 0.70), price $45, and its stored
margin-band judgment. Physical ceiling = 30 x 45 x 52 = $70,200/yr; the
fence evaluated Q11 at $24,097.60/q = $96,390/yr = 137% of capacity.

PRE-FIX (red): fence PASS, eval stamp passed=True, no capacity term.
POST-FIX (green): the growth multiple is capped at the stated-capacity wall
(ceiling x the engine's own 1%/q price path / anchor = 1.5825), the fence
FAILS, and the stamp shows requested/ceiling/used.
Controls: a non-unit model (no products) is untouched; a low-utilization
draft whose wall is above the fence is byte-identical.
"""
import copy, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import mysql.connector

from client_intake_and_finmo.intake_coherence.controller import evaluate_current
from client_intake_and_finmo.intake_coherence.evaluator import GROWTH_FENCE_Q11
from client_intake_and_finmo.intake_coherence import section as sec

DRAFT = "50658fff105e480c896f714fa519f22e"
conn = mysql.connector.connect(
  host=os.environ["MYSQL_HOST"], user=os.environ["MYSQL_USER"],
  password=os.environ["MYSQL_PASSWORD"], database=os.environ["MYSQL_DB"])
cur = conn.cursor(dictionary=True)
cur.execute("SELECT financials_json, operating_model_json FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,))
row = cur.fetchone()
fin_now = json.loads(row["financials_json"])
ops_now = json.loads(row["operating_model_json"])
state = fin_now.get("_coherence") or {}
band = state.get("margin_band_judgment")
assert band, "F&F draft has no margin band stamp"

fin_first = {
  "current_revenue": 49000.0, "cogs_percent_of_revenue": 0.12,
  "baseline_payroll_year1": 24000.0,
  "payroll_basis_people_roles": fin_now.get("payroll_basis_people_roles"),
  "payroll_adjustment": 0.0, "payroll_total_year1": 24000.0, "current_payroll": 24000.0,
  "owner_compensation": 2000.0, "other_operating_expense": 1450.0,
  "other_opex_absolute": 17400.0, "marketing_total_year1": 600.0,
  "monthly_rent_expense": 0.0, "total_debt_outstanding": 58000.0,
  "current_capex": 0.0, "current_num_employees": 1,
}
ops_first = copy.deepcopy(ops_now)
for lob in ops_first.get("lob_models") or []:
  for p in lob.get("products") or []:
    p["unit_price"] = 45.0
    # msg 7 "About 30 dogs a week" / msg 113 "My capacity is 30 dogs a week and I
    # run 21" - the stored 40/wk is her later (msg 121-126) correction.
    p["units_per_period_capacity"] = 30.0
    p["units_per_week_capacity"] = 30.0
prod = ops_first["lob_models"][0]["products"][0]
ceiling = 45.0 * float(prod["units_per_period_capacity"]) * float(prod.get("operating_periods_per_year") or 12)
print(f"stated ops: cap={prod['units_per_period_capacity']}/period x {prod.get('operating_periods_per_year')} periods x $45 -> physical ceiling ${ceiling:,.0f}/yr; anchor $49,000")

fails = []
def check(name, cond, detail=""):
  print(("  PASS " if cond else "  RED  ") + name + (f"  [{detail}]" if detail else ""))
  if not cond:
    fails.append(name)

# ---- T1: the fence tier on the real turn-96 shape (evaluate_current) ----
r = evaluate_current(financials_json=fin_first, ops_json=ops_first, financials_year1_json=None,
                     margin_band=band, growth_to_q11=None)
q11_rev_annual = r["q11"]["revenue"] * 4
g = r.get("growth") or {}
print(f"T1 fence: passed={r['passed']} q11 rev ${r['q11']['revenue']:,.2f}/q (${q11_rev_annual:,.0f}/yr) growth={g}")
check("T1a fence Q11 revenue does not exceed the stated-capacity ceiling on the price path",
      q11_rev_annual <= ceiling * 1.1046221254112045 + 0.01, f"{q11_rev_annual:,.0f} vs {ceiling*1.1046221254112045:,.0f}")
check("T1b fence verdict FAILS on F&F first-capture facts (was PASS at 137% of capacity)", r["passed"] is False)
check("T1c growth stamp shows requested/ceiling/used and capped flag",
      g.get("capped_by_stated_capacity") is True and abs(g.get("requested", 0) - GROWTH_FENCE_Q11) < 1e-6
      and g.get("used") is not None and g["used"] < GROWTH_FENCE_Q11)

# ---- T2: the production per-turn stamp (refresh_eval_stamps) writes the artifact ----
fin_stamped = dict(fin_first)
fin_stamped["_coherence"] = {"margin_band_judgment": band, "judged_growth": state.get("judged_growth"), "status": "pending"}
out = sec.refresh_eval_stamps(fin_stamped, ops_json=ops_first, financials_year1_json={})
ev = (out.get("_coherence") or {}).get("eval") or {}
print(f"T2 refresh_eval_stamps: eval.passed={ev.get('passed')} failed={ev.get('failed')} growth={ev.get('growth')}")
check("T2a stamped eval is NOT a pass", ev.get("passed") is False)
check("T2b stamped eval carries the growth wall (artifact)", isinstance(ev.get("growth"), dict) and ev["growth"].get("capacity_ceiling_multiple"))

# ---- T3: judged tier also capped (wall applies to every basis) ----
from client_intake_and_finmo.intake_coherence.evaluator import growth_multiple_from_judged, capacity_growth_ceiling
jm = growth_multiple_from_judged(state.get("judged_growth"), ops_json=ops_first)
wall = capacity_growth_ceiling(ops_first, 49000.0)
rj = evaluate_current(financials_json=fin_first, ops_json=ops_first, financials_year1_json=None, margin_band=band, growth_to_q11=max(jm or 1.0, 5.0))
check("T3 an over-capacity judged multiple is capped at the wall", abs((rj.get("growth") or {}).get("used", 0) - wall) < 1e-6, f"wall={wall:.4f}")

# ---- C1: non-unit model (no products) - no wall, fence untouched ----
rc = evaluate_current(financials_json=fin_first, ops_json={"lob_models": []}, financials_year1_json=None, margin_band=band, growth_to_q11=None)
check("C1 non-unit model keeps the fence exactly (no wall)", abs((rc.get("growth") or {}).get("used", 0) - GROWTH_FENCE_Q11) < 1e-6)
check("C1b non-unit model: ceiling multiple is None, verdict is the pre-fix fence verdict (PASS)",
      (rc.get("growth") or {}).get("capacity_ceiling_multiple") is None and rc["passed"] is True)

# ---- C2: low-utilization shape - wall above the fence => byte-identical to the fence ----
ops_low = copy.deepcopy(ops_first)
for lob in ops_low.get("lob_models") or []:
  for p in lob.get("products") or []:
    p["units_per_period_capacity"] = float(p["units_per_period_capacity"]) * 3.0  # capacity 90/wk, same anchor
rl = evaluate_current(financials_json=fin_first, ops_json=ops_low, financials_year1_json=None, margin_band=band, growth_to_q11=None)
check("C2 wall above the fence: growth used == fence, verdict unchanged from pre-fix (PASS)",
      abs((rl.get("growth") or {}).get("used", 0) - GROWTH_FENCE_Q11) < 1e-6 and rl["passed"] is True
      and (rl.get("growth") or {}).get("capped_by_stated_capacity") is False)

print()
print("ALL GREEN" if not fails else f"RED: {fails}")
sys.exit(1 if fails else 0)
