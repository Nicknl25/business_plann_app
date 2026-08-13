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
DRAFTS = [
    ("Sunny", "3b2144c780da4789bc9b6ddcb26bd7af"),
    ("Understory", "6f9de220dac24dde9149771b9a52f87e"),
    ("Harvest", "9408bd78c98f4d03bd6ef15216849b0f"),
    ("Glaze", "22f9567f4ecf47f9a239fe36cde7ff86"),
]
for label, d in DRAFTS:
    cur.execute(
        "SELECT model_input_json, finmo_json, repair_guidance_json, financials_json "
        "FROM intake_consult_drafts WHERE draft_id=%s", (d,))
    row = cur.fetchone()
    mi = json.loads(row["model_input_json"])
    fm = json.loads(row["finmo_json"])
    rg = json.loads(row["repair_guidance_json"]) if row.get("repair_guidance_json") else {}
    fin = json.loads(row["financials_json"])
    j = ((mi.get("solver_input") or {}).get("margin_band_judgment") or {})
    ga = None
    for r in ((mi.get("sections") or {}).get("expenses") or []):
        if isinstance(r, dict) and str(r.get("label")) == "General & Administrative":
            ga = [round(float(v) * 100, 2) for v in (r.get("values") or [])[:8]]
    rows = {int(float(r.get("quarter_index"))): r for r in fm.get("quarter_rows") or [] if isinstance(r, dict)}
    def m(q, f):
        r = rows.get(q) or {}
        rev = float(r.get("revenue") or 1)
        return round(float(r.get(f) or 0) / rev * 100, 1)
    print(f"== {label} ({d[:12]})")
    print(f"   opex pair: monthly={fin.get('other_operating_expense')} absolute={fin.get('other_opex_absolute')}")
    print(f"   G&A row % (stub,Q1..Q7): {ga}")
    print(f"   band: {j.get('q11')} / {j.get('q20')}  char: {j.get('margin_character')}")
    print(f"   floors: gm={j.get('gross_margin_floor_q11')} burden={j.get('fixed_cost_burden_max_q11')}")
    print(f"   restructure: {bool(rg.get('restructure'))}"
          + (f" final_passed={((rg.get('restructure') or {}).get('final_passed'))}" if rg.get("restructure") else ""))
    print(f"   Q11: EBITDA {m(11,'ebitda')}% NI {m(11,'net_income')}%   Q20: EBITDA {m(20,'ebitda')}% NI {m(20,'net_income')}%")
cur.close()
conn.close()
