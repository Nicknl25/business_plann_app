"""Preview of the review-bound round-2 search: real authored bounds from
draft 6674464f (executive's own per-line margins), the reviewer's
tightened caps applied, revenue story REQUIRED."""
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
    "SELECT model_input_json, planning_runtime_json, operating_model_json, financials_json, repair_guidance_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    ("6674464f55a349b58e87eab8fc52698d",),
)
row = cur.fetchone()
mi = json.loads(row["model_input_json"])
runtime = json.loads(row["planning_runtime_json"])
ops = json.loads(row["operating_model_json"])
fin = json.loads(row["financials_json"])
g = json.loads(row["repair_guidance_json"])
cur.close()
conn.close()

hist = g["restructure"]["history"]
bounds = next(it["bounds"] for it in hist if it.get("stage") == "bounds")
review = next(it["review"] for it in hist if it.get("stage") == "review_1")

from client_intake_and_finmo.post_intake_restructure.solution_review import (
    apply_review_tightening,
)
from client_intake_and_finmo.post_intake_restructure.searcher import (
    candidate_to_directive,
    search_viable_configuration,
)

bounds2 = apply_review_tightening(bounds, review)
print("tightened caps:", [
    (l.get("product"), l.get("price_multiplier_max"), l.get("volume_multiplier_max"))
    for l in bounds2["existing_lines"]
])
print("line margins:", [
    (l.get("product"), l.get("gross_margin_pct")) for l in bounds2["existing_lines"]
])

planning_mode = str(runtime.get("planning_mode") or "").strip() or None
naics = "".join(ch for ch in str(ops.get("business_naics_6") or "") if ch.isdigit()) or None

t0 = time.perf_counter()
result = search_viable_configuration(
    base_model_input=mi, bounds=bounds2,
    business_naics_6=naics, ops_json=ops, financials_json=fin,
    planning_mode=planning_mode,
    require_revenue_move=True,
)
elapsed = time.perf_counter() - t0
print(f"\nSEARCH: found={result['found']} evals={result['evals']} in {elapsed:.1f}s")
for line in result["trace"]:
    print("  ", line)
score = result["score"]
print("\nfailed_binding:", score.get("failed_binding"))
for q in ("q5", "q11", "q20"):
    print(f"landed {q}:", (score.get("landed") or {}).get(q))
print("\nMINIMAL-CHANGE candidate:", json.dumps(result["candidate"], indent=1, sort_keys=True))
print("\nLEAN-END candidate:", json.dumps(result.get("candidate_first_viable"), indent=1, sort_keys=True))
if result["found"]:
    d = candidate_to_directive(
        result["candidate"], bounds2, result["base_levels"],
        base_model_input=mi,
        line_margins=result.get("line_margins") or None,
        payroll_burden_factor=float(result.get("payroll_burden_factor") or 1.0),
    )
    print("\ndirective team payroll (wage basis):", d["team"]["annual_payroll"])
    print("directive cogs target:", d["cost_structure"]["cogs_percent_of_revenue"])
    print("directive mix lines:", json.dumps(d["revenue_mix"]["lines"], sort_keys=True))
    print("directive new lines:", json.dumps(d["revenue_mix"]["new_lines"], sort_keys=True))
