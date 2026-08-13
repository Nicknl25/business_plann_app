"""ABLATION BATCH C — C1 (cash min() binding) + C6 (surplus split weights).
In-memory only; no python/ files modified. Uses Peachtree's real run state.
"""
import json, os, sys
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

DRAFT = "f62e846077ef40ca96f37edafb97a6fe"
conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!", database="biz_plan_revert")
cur = conn.cursor(dictionary=True)
cur.execute("SELECT model_input_json, finmo_json, financials_json FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,))
r = cur.fetchone()
mi = json.loads(r["model_input_json"]) ; finmo = json.loads(r["finmo_json"]) ; fin = json.loads(r["financials_json"])
conn.close()

from client_intake_and_finmo.post_intake_mapping import post_intake_cash_policy_for
from client_intake_and_finmo.post_intake_cash.common import (
    buffer_components, capital_structure_snapshot, live_quarter_rows, safe_float,
    canonical_cash_strategy_value,
)
from client_intake_and_finmo.post_intake_cash.gpt_cash_judgment import cash_judgment_from_model_input

cj = cash_judgment_from_model_input(mi)
judged_floor = safe_float(cj.get("buffer_months"))
judged_ceiling = safe_float(cj.get("ceiling_months"))
strategy = canonical_cash_strategy_value(fin.get("cash_strategy")) or "balanced"
rows = live_quarter_rows(finmo)
rows_by_q = {int(safe_float(x.get("quarter_index")) or 0): x for x in rows}
cap = capital_structure_snapshot(rows_by_q.get(1) or {}, preferred_debt_ratio=0.0, preferred_equity_ratio=1.0)
d2e = cap.get("debt_to_equity")

policy = post_intake_cash_policy_for(cash_strategy=strategy, debt_to_equity=d2e, required=False) or {}
balanced = post_intake_cash_policy_for(cash_strategy="balanced", debt_to_equity=d2e, required=False) or {}

pf = float(safe_float(policy.get("cash_floor_months")) or 1.0)
bf = float(safe_float(balanced.get("cash_floor_months")) or pf)
jf = float(judged_floor) if judged_floor else float("inf")

print("=== C1 INPUTS (Peachtree, real run) ===")
print(f"strategy={strategy}  D/E(q1)={d2e}  debt_position={policy.get('debt_position')}")
print(f"judged buffer_months={judged_floor}  judged ceiling={judged_ceiling}  debt_term_quarters={cj.get('debt_term_quarters')}")
print(f"policy row ({strategy}/{policy.get('debt_position')}): floor={pf} ceiling={policy.get('cash_ceiling_months')} dist_w={policy.get('distribution_weight')} debt_w={policy.get('debt_paydown_weight')}")
print(f"balanced row ({balanced.get('debt_position')}): floor={bf}")

variants = {
    "full_min(judged,policy,balanced)": min(jf, pf, bf),
    "no_balanced_partner(min judged,policy)": min(jf, pf),
    "no_policy_partner(min judged,balanced)": min(jf, bf),
    "judgment_alone": jf,
    "policy_alone": pf,
}
print("\n=== C1 FLOOR VARIANTS (months) ===")
for k, v in variants.items():
    print(f"  {k}: {v}")

print("\n=== C1 DOLLARS: per-quarter buffer_required under each floor; violations vs real ending_cash ===")
horizon = max(rows_by_q)
debt_any = any(abs(float(safe_float(rows_by_q[q].get("debt_opening_balance")) or 0.0)) > 0.5 or
               abs(float(safe_float(rows_by_q[q].get("debt_issuance")) or 0.0)) > 0.5 for q in rows_by_q)
print(f"any debt on run: {debt_any} (revolver paydown dollars = 0 regardless of floor when no draws exist)")
for label, months in [("governing 1.5", min(jf, pf, bf)), ("judgment-alone 2.0", jf), ("judged ceiling 4.0 (retention/deploy)", float(judged_ceiling or 0))]:
    viol = []
    sample = {}
    for q in sorted(rows_by_q):
        comp = buffer_components(rows_by_q[q], cash_floor_months=months, cash_ceiling_months=months,
                                 default_buffer_months=months, months_per_quarter=3.0)
        req = int(comp["cash_buffer_required"])
        ec = int(round(float(safe_float(rows_by_q[q].get("ending_cash")) or 0.0)))
        if q in (1, 5, 20):
            sample[q] = (req, ec, comp["monthly_opex"])
        if ec < req:
            viol.append(q)
    print(f"  floor={months} mo ({label}): violations={viol or 'NONE'}  q1(req={sample[1][0]:,}, cash={sample[1][1]:,}, mo_opex={sample[1][2]:,}) q20(req={sample[20][0]:,}, cash={sample[20][1]:,})")

print("\n=== C6: surplus split — weights vs judgment ===")
priority = str(cj.get("surplus_priority") or "").lower()
dw = float(policy.get("distribution_weight") or 0.0)
pw = float(policy.get("debt_paydown_weight") or 0.0)
print(f"selected policy row: {strategy}/{policy.get('debt_position')} -> distribution_weight={dw} debt_paydown_weight={pw}")
print(f"cash_judgment.surplus_priority = '{priority}' (deleverage_first would FORCE 0/1 override; distribute_ok keeps policy weights)")
dist_series = [float(safe_float(rows_by_q[q].get("distributions")) or 0.0) for q in sorted(rows_by_q)]
rep_series = [float(safe_float(rows_by_q[q].get("debt_repayment")) or 0.0) for q in sorted(rows_by_q)]
print(f"run outcome: total distributions=${sum(dist_series):,.0f}  total debt repayment=${sum(rep_series):,.0f}")
print("decider: judgment='distribute_ok' -> NO override; policy weights (1.00/0.00) applied; with zero debt, max_debt_add=0 so")
print("         even ablated weights (e.g. 0/1) would spill 100% of surplus to distributions via the spillover branch.")

# C6 ablation: recompute one quarter's attempted split under ablated weights
print("\n=== C6 ABLATION (arithmetic on Q8 surplus, the largest distribution quarter) ===")
q8_dist = dist_series[7]
for name, (adw, apw) in {"real (1.00/0.00)": (1.0, 0.0), "ablate->balanced-like (0.25/0.75)": (0.25, 0.75), "ablate->all-debt (0.00/1.00)": (0.0, 1.0)}.items():
    surplus = q8_dist  # the deployed surplus that quarter
    attempted_debt = min(0, round(surplus * apw))  # max_debt_add = 0 (no debt outstanding)
    attempted_dist = surplus - max(0, attempted_debt)
    print(f"  weights {name}: attempted debt paydown=min(max_debt_add=0, {surplus*apw:,.0f})=0 -> distributions get ${attempted_dist:,.0f} (unchanged)")
