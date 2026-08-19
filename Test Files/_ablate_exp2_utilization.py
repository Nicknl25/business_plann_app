"""EXP-2: mature utilization 0.85 - what job does each copy do.

(a) PROPOSER copy (deterministic_revenue_proposer): ablate 0.85 -> 1.0
    and 0.85 -> 0.50 on real Peachtree revenue reference. If revenue is
    identical, the constant only shapes the util/capacity decomposition
    (presentation physics), not the forecast level.
(b) CONTRACT copy (_MATURE_UTILIZATION_CAP): rebuild the real stage-ramp
    contract with 0.85 vs 1.0 vs 0.60 and diff the utilization curve,
    watermark, and whether the contract stays validator-acceptable.
"""
import copy
import json
import sys

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv()
import mysql.connector

conn = mysql.connector.connect(
    host="localhost", user="root", password="Lovers251979!",
    database="biz_plan_revert", autocommit=True)
cur = conn.cursor()
cur.execute(
    "SELECT operating_model_json, financials_json, financials_year1_json, "
    "people_json, model_input_json, finmo_json FROM intake_consult_drafts "
    "WHERE draft_id = 'f62e846077ef40ca96f37edafb97a6fe'")
ops, fin, fy1, ppl, mi, finmo = [json.loads(x) if x else {} for x in cur.fetchone()]

# ---- (a) proposer
import client_intake_and_finmo.post_intake_headcount.deterministic_revenue_proposer as P

ref = None
si = mi.get("solver_input") or {}
for key in ("current_revenue_reference", "revenue_reference"):
    if isinstance(si.get(key), list):
        ref = si[key]
        break
if ref is None:
    # build the reference the runner builds: from ops lob models
    ref = []
    for lob in (ops.get("lob_models") or []):
        for pr in (lob.get("products") or []):
            ref.append({
                "lob_name": lob.get("lob_name"), "product_name": pr.get("product_name"),
                "unit_price": pr.get("unit_price"),
                "capacity_units_per_period": pr.get("units_per_period_capacity"),
                "utilization_rate": pr.get("utilization_rate") or 0.8,
            })

for mu in (0.85, 1.0, 0.50):
    out = P.propose_revenue_drivers_deterministic(
        current_revenue_reference=copy.deepcopy(ref),
        anchor_q1_revenue_total=float(fin.get("current_revenue") or 0) / 4.0,
        mature_utilization=mu)
    lines = (out.get("drivers") or {}).get("lines_of_business") or []
    def total_rev(qi):
        t = 0.0
        for ln in lines:
            qs = ln.get("quarters") or []
            if qi < len(qs):
                q = qs[qi]
                t += float(q.get("capacity_units_per_period") or 0) * float(q.get("unit_price") or 0) * float(q.get("utilization_rate") or 0)
        return t
    u_q11 = None
    if lines:
        qs = lines[0].get("quarters") or []
        if len(qs) > 10:
            u_q11 = qs[10].get("utilization_rate")
    print(f"(a) proposer mature_util={mu}: rev_q1={total_rev(0):,.0f} rev_q11={total_rev(10):,.0f} rev_q20={total_rev(19):,.0f} line1_util_q11={u_q11}")

# ---- (b) contract cap
import client_intake_and_finmo.post_intake_contracts.runner as R

for cap in (0.85, 1.0, 0.60):
    orig = R._MATURE_UTILIZATION_CAP
    R._MATURE_UTILIZATION_CAP = cap
    try:
        built = R.build_python_stage_ramp_contract(
            business_facts={}, ops_json=ops, financials_json=fin,
            financials_year1_json=fy1, people_json=ppl, planning_mode="standard",
            planning_mode_reason="", model_input_json=mi, finmo_json=finmo,
            r_and_d_applicability={"r_and_d_enabled": False})
        g = built["quarter_ramp_grid"]
        v = R._validate_stage_ramp_contract_payload(
            payload=built, expected_stage_family=built.get("stage_family") or "operational")
        ok = "valid"
    except RuntimeError as e:
        ok = f"REJECTED: {str(e)[:110]}"
        g = built["quarter_ramp_grid"] if built else []
    finally:
        R._MATURE_UTILIZATION_CAP = orig
    utils = [g[i]["max_util"] for i in (0, 5, 10, 19)] if g else []
    print(f"(b) contract cap={cap}: watermark={built.get('utilization_high_watermark')} max_util q1/q6/q11/q20={utils} -> {ok}")
