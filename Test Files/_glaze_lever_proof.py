"""Receipts for the Glaze solve: (1) the exact lever list + bounds the
joint solve was given (coffee/catering as real adjustable cells), and
(2) the fast-evaluator result of the FULL-CORNER candidate — all three
lines at their caps at once — proving the dead-end with the lines IN."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT model_input_json, repair_guidance_json, operating_model_json, financials_json, "
    "planning_runtime_json, finmo_json FROM intake_consult_drafts WHERE draft_id=%s",
    ("cc8b7081adec47b4b79f33a6231beb26",),
)
row = cur.fetchone()
mi = json.loads(row["model_input_json"])
g = json.loads(row["repair_guidance_json"])
ops = json.loads(row["operating_model_json"])
fin = json.loads(row["financials_json"])
runtime = json.loads(row["planning_runtime_json"])
fm = json.loads(row["finmo_json"])
cur.close()
conn.close()

bounds = next(it["bounds"] for it in g["restructure"]["history"] if it.get("stage") == "bounds")

# Q3 receipt: what lines does the PERSISTED FINMO/model_input contain?
lines_in_model = sorted({
    (str(r.get("lob")), str(r.get("product")))
    for r in ((mi.get("sections") or {}).get("revenue") or [])
    if isinstance(r, dict) and r.get("driver") == "Unit Price"
})
print("PERSISTED model_input revenue lines (the un-restructured business):")
for lb in lines_in_model:
    print("  ", lb)

# Q1/Q2 receipt: rebuild the solve's prepared model + lever plan
# (deterministic — same code path the run used).
from client_intake_and_finmo.post_intake_restructure.joint_solver import (
    _base_levels, _lever_plan, _prepare_restructure_model,
)
from client_intake_and_finmo.post_intake_restructure.searcher import (
    apply_candidate, line_margins_from_bounds,
)
from client_intake_and_finmo.post_intake_restructure.fast_evaluator import (
    build_fast_finmo, score_viability,
)

prepared = _prepare_restructure_model(mi, bounds)
base_lv = _base_levels(mi)
stated_wages = float(fin.get("payroll_total_year1") or 0.0)
bf = (base_lv.get("annual_payroll") or 0.0) / stated_wages if stated_wages else 1.0
plan = _lever_plan(prepared, bounds, base_lv, bf)
print("\nTHE SOLVE'S ADJUSTABLE CELLS (lever id -> Q11 bounds):")
for lever_id in sorted(plan["bounds"].keys()):
    b11 = plan["bounds"][lever_id].get(11)
    tag = ""
    if lever_id in plan["new_line_of_lever"]:
        tag = "  <-- NEW LINE (free variable, 0..market cap)"
    print(f"  {lever_id}: {b11}{tag}")

# Q4 receipt: full-corner candidate — every line at its cap at once.
line_margins = line_margins_from_bounds(bounds)
donut_key = None
for lob, prod in lines_in_model:
    donut_key = f"{lob.strip().casefold()}/{prod.strip().casefold()}"
full_corner = {
    "lines": {donut_key: {"price_m11": 1.75, "price_m20": 1.75,
                          "volume_m11": 4.0, "volume_m20": 4.0}},
    "new_lines": [
        {"lob": "Beverages", "product": "coffee & drinks", "unit_price": 3.0,
         "gross_margin_pct": 0.75, "q11_quarterly_revenue": 15000.0},
        {"lob": "Pre-orders & Catering", "product": "bulk donut orders", "unit_price": 1.5,
         "gross_margin_pct": 0.6, "q11_quarterly_revenue": 12000.0},
    ],
    "annual_payroll": 115000.0 * max(1.0, min(2.0, bf)),
    "quarterly_rent": 4500.0,
    "marketing_pct": 0.04,
    "g_and_a_pct": 0.12,
}
mi_corner = apply_candidate(mi, full_corner, line_margins=line_margins or None)
score = score_viability(
    model_input_json=mi_corner, finmo_json=build_fast_finmo(mi_corner),
    business_naics_6="".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None,
    ops_json=ops, financials_json=fin,
    planning_mode=str(runtime.get("planning_mode") or "").strip() or None,
)
print("\nFULL-CORNER EVALUATION (donuts 4.0x vol + 1.75x price, coffee $15k/q, catering $12k/q,")
print("payroll at floor, rent at floor):")
print("  viable_pnl:", score.get("viable_pnl"))
print("  failed_binding:", score.get("failed_binding"))
for q in ("q5", "q11", "q20"):
    print(f"  landed {q}:", (score.get("landed") or {}).get(q))
