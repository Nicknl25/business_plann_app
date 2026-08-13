import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
draft_id = sys.argv[1]
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT repair_guidance_json FROM intake_consult_drafts WHERE draft_id=%s",
    (draft_id,),
)
row = cur.fetchone() or {}
g = json.loads(row["repair_guidance_json"])
hist = ((g or {}).get("restructure") or {}).get("history") or []
for it in hist:
    stage = it.get("stage")
    print(f"--- {stage} ---")
    if stage == "bounds":
        b = it.get("bounds") or {}
        print("feasible_region_exists:", b.get("feasible_region_exists"))
        for ln in b.get("existing_lines") or []:
            print("  line:", ln.get("lob"), "/", ln.get("product"),
                  "pmax:", ln.get("price_multiplier_max"),
                  "vmax:", ln.get("volume_multiplier_max"),
                  "can_drop:", ln.get("can_drop"))
        for nl in b.get("new_line_candidates") or []:
            print("  new line:", nl.get("lob"), "/", nl.get("product"),
                  "price:", nl.get("unit_price"), "rev_max:", nl.get("q11_quarterly_revenue_max"),
                  "margin:", nl.get("gross_margin_pct"))
        print("  team:", b.get("team"))
        print("  facility:", b.get("facility"))
        print("  cost_floors:", b.get("cost_floors"))
        print("  overall:", (b.get("overall_rationale") or "")[:400])
    elif stage and stage.startswith("search"):
        print("found:", it.get("found"), "evals:", it.get("evals"))
        for t in it.get("trace") or []:
            print("   ", t)
        print("candidate:", json.dumps(it.get("candidate"), sort_keys=True))
        print("landed:", json.dumps(it.get("landed"), sort_keys=True))
    elif stage and stage.startswith("review"):
        r = it.get("review") or {}
        print("approved:", r.get("approved"),
              "no_realistic:", r.get("no_realistic_design_exists"))
        print("tightened:", r.get("tightened_lines"))
        print("rationale:", (r.get("rationale") or "")[:500])
        print("error:", it.get("error"))
    else:
        print(json.dumps(it, default=str)[:600])
cur.close()
conn.close()
