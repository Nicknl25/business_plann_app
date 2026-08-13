"""Search dry-run on Understory with the REAL executive-authored bounds
(from draft 4395f97c's restructure record) + honest labor physics."""
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
# Base = the ORIGINAL failed run's model input (draft 3464962b, the
# completed non-viable run whose state the search would start from).
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
# Real bounds from the v2 run record.
cur.execute(
    "SELECT repair_guidance_json FROM intake_consult_drafts WHERE draft_id=%s",
    ("4395f97c7c6741a5b8c6e1353351eb6e",),
)
g = json.loads(cur.fetchone()["repair_guidance_json"])
bounds = next(
    it["bounds"] for it in g["restructure"]["history"] if it.get("stage") == "bounds"
)
cur.close()
conn.close()

# Margin-vision test: inject per-line gross margins (the real re-run's
# constraint_author will author these itself; plausible operator values
# here — fresh commodity-ish, value-added higher).
for line in bounds["existing_lines"]:
    if "fresh" in str(line.get("lob") or "").lower():
        line["gross_margin_pct"] = 0.45
    else:
        line["gross_margin_pct"] = 0.60

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
print(f"SEARCH: found={result['found']} evals={result['evals']} in {elapsed:.1f}s")
for line in result["trace"]:
    print("  ", line)
score = result["score"]
print("\nfinal failed_binding:", score.get("failed_binding"))
for q in ("q1", "q5", "q11", "q20"):
    print(f"landed {q}:", (score.get("landed") or {}).get(q))
print("\ncandidate:", json.dumps(result["candidate"], indent=1, sort_keys=True))
