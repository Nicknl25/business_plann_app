"""WS1(b) intake-half smoke: lines helper, RECALC per-line derive +
stated-dollars lockstep, carry-forward guard, bridge end-to-end (ops ->
model_input_json -> finmo) with the Sigma == blend invariant, and the
single-line no-op guarantees at every seam."""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "C:/dev/business_plann_app/python")

from api_handlers.intake_consult import (
    _cogs_revenue_lines,
    _carry_forward_per_line_cogs,
    _sync_financials_consult_persistence_state,
)

OPS = {
    "business_type": "Bike shop",
    "business_naics_6": "459110",
    "lob_models": [
        {"lob_name": "Bike retail", "products": [{
            "product_name": "Bike sale", "unit_name": "bike", "unit_cadence": "weekly",
            "units_per_week_capacity": 10, "utilization_rate": 0.72, "unit_price": 1250.0,
            "cogs_percent_of_line_revenue": 0.62,
        }]},
        {"lob_name": "Service", "products": [{
            "product_name": "Repair", "unit_name": "repair", "unit_cadence": "weekly",
            "units_per_week_capacity": 50, "utilization_rate": 0.85, "unit_price": 95.0,
            "cogs_percent_of_line_revenue": 0.18,
        }]},
    ],
}
# annual revenues: bikes 10*0.72*1250*52 = 468,000 ; repairs 50*0.85*95*52 = 209,950
Y1 = {
    "company_revenue_total_year1": 677950.0,
    "lobs": [
        {"lob_name": "Bike retail", "products": [{"product_name": "Bike sale", "revenue_total_year1": 468000.0}]},
        {"lob_name": "Service", "products": [{"product_name": "Repair", "revenue_total_year1": 209950.0}]},
    ],
}

lines = _cogs_revenue_lines(ops_json=OPS, financials_year1_json=Y1)
print("T1 lines:", [(l["line_name"], l["revenue_share"]) for l in lines],
      "-> 2 lines w/ shares:", len(lines) == 2 and all(l["revenue_share"] for l in lines))

single_ops = {"lob_models": [OPS["lob_models"][0]]}
print("T2 single-line helper returns []:", _cogs_revenue_lines(ops_json=single_ops, financials_year1_json=Y1) == [])

# --- RECALC per-line derive ---
import copy
ops_rc = copy.deepcopy(OPS)
fin = {"_financials_revenue_intro_done": True, "cogs_percent_of_revenue": 0.99,
       "current_cogs": 1.0, "cogs_total_year1": 1.0, "cogs_basis": "ratio"}
fin2, y2 = _sync_financials_consult_persistence_state(
    financials_json=fin, financials_year1_json=copy.deepcopy(Y1), ops_json=ops_rc)
exp_total = 468000.0 * 0.62 + 209950.0 * 0.18  # 290,160 + 37,791 = 327,951
rev2 = float(y2.get("company_revenue_total_year1") or 0.0)
got_total = float(fin2.get("cogs_total_year1") or 0.0)
got_pct = float(fin2.get("cogs_percent_of_revenue") or 0.0)
exp_pct_vs_rev = abs(got_pct - got_total / rev2) < 1e-9 if rev2 else False
print(f"T3 RECALC derive: total {got_total:.0f} (patched 1.0 overridden) ->",
      abs(got_total - exp_total) < max(1.0, 0.02 * exp_total),
      f"| pct {got_pct:.4f} coherent w/ rev {rev2:.0f} ->", exp_pct_vs_rev)

# --- stated-dollars lockstep: client says COGS is 163,975 total (half) ---
ops_lk = copy.deepcopy(OPS)
fin_lk = {"_financials_revenue_intro_done": True, "cogs_basis": "dollars",
          "cogs_total_year1": exp_total / 2.0, "current_cogs": exp_total / 2.0}
fin3, y3 = _sync_financials_consult_persistence_state(
    financials_json=fin_lk, financials_year1_json=copy.deepcopy(Y1), ops_json=ops_lk)
pcts3 = [p["cogs_percent_of_line_revenue"] for lm in ops_lk["lob_models"] for p in lm["products"]]
print("T4 dollars lockstep: line pcts", pcts3, "-> halved:",
      abs(pcts3[0] - 0.31) < 0.01 and abs(pcts3[1] - 0.09) < 0.01,
      "| basis back to ratio:", fin3.get("cogs_basis") == "ratio",
      f"| total {float(fin3.get('cogs_total_year1') or 0):.0f} ~ {exp_total/2:.0f}")

# --- single-line RECALC unchanged (no per-line keys anywhere) ---
fin_s = {"_financials_revenue_intro_done": True, "cogs_percent_of_revenue": 0.55, "cogs_basis": "ratio"}
y1_s = {"company_revenue_total_year1": 468000.0,
        "lobs": [{"lob_name": "Bike retail", "products": [{"product_name": "Bike sale", "revenue_total_year1": 468000.0}]}]}
fin_s2, _ = _sync_financials_consult_persistence_state(
    financials_json=fin_s, financials_year1_json=y1_s, ops_json=copy.deepcopy(single_ops))
print("T5 single-line ladder untouched: pct stays 0.55 ->",
      abs(float(fin_s2.get("cogs_percent_of_revenue") or 0) - 0.55) < 1e-9)

# --- carry-forward guard ---
incoming = copy.deepcopy(OPS["lob_models"])
for lm in incoming:
    for p in lm["products"]:
        p["cogs_percent_of_line_revenue"] = None  # consultant restatement w/o statement
merged = _carry_forward_per_line_cogs(existing=OPS["lob_models"], incoming=incoming)
kept = [p["cogs_percent_of_line_revenue"] for lm in merged for p in lm["products"]]
print("T6 carry-forward: restated nulls inherit ->", kept == [0.62, 0.18])

# --- bridge end-to-end: ops w/ per-line -> model_input_json -> finmo ---
from client_intake_and_finmo.finmo_bridge import build_python_model_input_json, build_python_finmo_json
mi = build_python_model_input_json(
    business_facts={"business_name": "Thistle Smoke", "start_date": "2020-01-01"},
    ops_json=copy.deepcopy(OPS),
    people_json={},
    financials_json={"current_revenue": 677950.0, "cogs_percent_of_revenue": 0.4838},
    financials_year1_json=copy.deepcopy(Y1),
    marketing_model_json={},
    forecast_starting_ppe=0.0,
    maintenance_rate=0.05,
)
rev_rows = mi["sections"]["revenue"]
cogs_rows = [r for r in rev_rows if r.get("driver") == "COGS %"]
blend_row = next(r for r in mi["sections"]["expenses"] if r.get("label") == "Cost of Goods Sold")
print("T7 bridge emits", len(cogs_rows), "COGS % rows (expect 2); values[1]:",
      [r["values"][1] for r in cogs_rows], "| blend[1]:", blend_row["values"][1])
finmo = build_python_finmo_json(model_input_json=mi)
rows = finmo.get("quarters") or finmo.get("quarter_rows") or []
if rows:
    q1 = rows[0] if not rows[0].get("quarter_index") in (0,) else (rows[1] if len(rows) > 1 else rows[0])
    q_rev = float(q1.get("revenue") or 0.0)
    q_cogs = float(q1.get("cogs") or q1.get("cost_of_goods_sold") or 0.0)
    # Sigma invariant: line revenues x line pcts == reported cogs
    caps = {r["revenue_slot_key"]: r for r in rev_rows if r["driver"] == "Capacity"}
    prices = {r["revenue_slot_key"]: r for r in rev_rows if r["driver"] == "Unit Price"}
    utils = {r["revenue_slot_key"]: r for r in rev_rows if r["driver"] == "Utilization"}
    idx = 1
    sigma = sum(
        caps[r["revenue_slot_key"]]["values"][idx] * prices[r["revenue_slot_key"]]["values"][idx]
        * utils[r["revenue_slot_key"]]["values"][idx] * r["values"][idx]
        for r in cogs_rows
    )
    print(f"T8 SIGMA invariant: finmo q1 cogs {q_cogs:.0f} vs Sigma(lines) {sigma:.0f} ->",
          abs(q_cogs - sigma) < max(1.0, 0.01 * max(q_cogs, 1.0)), f"| q1 rev {q_rev:.0f}")
else:
    print("T8 SKIP: finmo rows empty - keys:", list(finmo.keys())[:12])

# --- single-line bridge: NO COGS % rows ---
mi_s = build_python_model_input_json(
    business_facts={"business_name": "Single Smoke", "start_date": "2020-01-01"},
    ops_json=copy.deepcopy(single_ops),
    people_json={},
    financials_json={"current_revenue": 468000.0, "cogs_percent_of_revenue": 0.55},
    financials_year1_json=copy.deepcopy(y1_s),
    marketing_model_json={},
    forecast_starting_ppe=0.0,
    maintenance_rate=0.05,
)
print("T9 single-line bridge: COGS % rows:",
      len([r for r in mi_s["sections"]["revenue"] if r.get("driver") == "COGS %"]), "(expect 0)")
