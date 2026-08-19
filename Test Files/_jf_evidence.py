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
for label, d in (
    ("Blueprint", "1d515b3c743749aeb8eda83eb0f907ab"),
    ("Meridian", "b6078ffac55a4e41b612691608aa32ce"),
):
    cur.execute(
        "SELECT repair_guidance_json, finmo_json, model_input_json FROM intake_consult_drafts WHERE draft_id=%s",
        (d,),
    )
    row = cur.fetchone()
    g = json.loads(row["repair_guidance_json"]) if row.get("repair_guidance_json") else {}
    rst = g.get("restructure") or {}
    hist = rst.get("history") or []
    for it in hist:
        if it.get("stage") == "bounds":
            gap = it.get("gap_report_in") or {}
            print(f"{label} FIRST-PASS failed_checks:", gap.get("failed_checks"))
        if isinstance(it.get("verdict_after"), dict):
            print(f"{label} verdict_after re-run:", it["verdict_after"].get("passed"),
                  it["verdict_after"].get("failed_checks"))
    print(f"{label} final_passed:", rst.get("final_passed"))
    fm = json.loads(row["finmo_json"])
    rows = {int(float(r.get("quarter_index"))): r for r in fm.get("quarter_rows") or [] if isinstance(r, dict)}
    for q in (11, 20):
        r = rows.get(q) or {}
        rev = float(r.get("revenue") or 1)
        print(f"  {label} Q{q}: ebitda_margin={float(r.get('ebitda') or 0) / rev:.4f} "
              f"gm={(rev - float(r.get('cost_of_goods_sold') or 0)) / rev:.4f}")
    mi = json.loads(row["model_input_json"])
    j = ((mi.get("solver_input") or {}).get("margin_band_judgment") or {})
    print(f"  {label} judged bands: q11={j.get('q11')} q20={j.get('q20')} "
          f"gm_floor={j.get('gross_margin_floor_q11')} burden_max={j.get('fixed_cost_burden_max_q11')}")
    print()
cur.close()
conn.close()
