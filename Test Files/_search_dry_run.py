"""Dry run of the restructure search on Understory's real failed draft,
with SYNTHETIC bounds (mechanics proof — GPT bounds come next)."""
import json
import os
import sys
import time

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
    "SELECT model_input_json, planning_runtime_json, operating_model_json, financials_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    ("3464962b16864c1a942d48c746dc48bb",),
)
row = cur.fetchone()
mi = json.loads(row["model_input_json"])
runtime = json.loads(row["planning_runtime_json"])
ops = json.loads(row["operating_model_json"])
fin = json.loads(row["financials_json"])
cur.close()
conn.close()

# The mushroom farm's revenue lines, from the model_input itself.
lines = sorted({
    (str(r.get("lob")), str(r.get("product")))
    for r in ((mi.get("sections") or {}).get("revenue") or [])
    if isinstance(r, dict) and r.get("driver") == "Unit Price"
})
print("revenue lines:", lines)

# SYNTHETIC bounds (dry-run only): modest specialty-price headroom,
# real value-added expansion room, team floor at owner+1, smaller space.
bounds = {
    "feasible_region_exists": True,
    "existing_lines": [
        {
            "lob": lob, "product": prod,
            "price_multiplier_max": 1.35,
            "volume_multiplier_max": 1.75,
            "can_drop": False,
            "rationale": "synthetic",
        }
        for lob, prod in lines
    ],
    "new_line_candidates": [
        {
            "lob": "Value-Added", "product": "Dried Mushroom Products",
            "unit_price": 14.0, "q11_quarterly_revenue_max": 40000.0,
            "gross_margin_pct": 0.55, "rationale": "synthetic",
        }
    ],
    "team": {
        "min_annual_payroll": 98000.0, "max_annual_payroll": 130000.0,
        "structure_at_min": "owner-grower + 1 FT grower + PT market help",
        "rationale": "synthetic",
    },
    "facility": {
        "min_quarterly_rent": 7500.0, "max_quarterly_rent": 19500.0,
        "rationale": "synthetic",
    },
    "cost_floors": {
        "cogs_percent_of_revenue_min": 0.28,
        "marketing_percent_of_revenue_min": 0.02,
        "g_and_a_percent_of_revenue_min": 0.04,
        "rationale": "synthetic",
    },
    "growth": {
        "year1_annual_growth_max": 0.25, "mature_annual_growth_max": 0.06,
        "rationale": "synthetic",
    },
    "reality_constraints": {
        "real_market": "synthetic", "real_physics": "synthetic",
        "still_this_business": "synthetic", "lender_defensible": "synthetic",
    },
}

from client_intake_and_finmo.post_intake_restructure.searcher import (
    candidate_to_directive,
    search_viable_configuration,
)

planning_mode = str(runtime.get("planning_mode") or "").strip() or None
naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None

t0 = time.perf_counter()
result = search_viable_configuration(
    base_model_input=mi, bounds=bounds,
    business_naics_6=naics, ops_json=ops, financials_json=fin,
    planning_mode=planning_mode,
)
elapsed = time.perf_counter() - t0
print(f"\nSEARCH: found={result['found']} evals={result['evals']} in {elapsed:.1f}s")
for line in result["trace"]:
    print("  ", line)
score = result["score"]
print("\nfinal failed_binding:", score.get("failed_binding"))
print("landed q11:", (score.get("landed") or {}).get("q11"))
print("landed q20:", (score.get("landed") or {}).get("q20"))
print("\ncandidate:", json.dumps(result["candidate"], indent=1, sort_keys=True))
if result["found"]:
    directive = candidate_to_directive(
        result["candidate"], bounds, result["base_levels"],
        overall_rationale="dry-run",
    )
    print("\ndirective:", json.dumps(directive, indent=1, sort_keys=True)[:2000])
