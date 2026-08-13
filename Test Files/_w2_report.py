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
from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance

BASELINE_BANDS = {
    "Sunny": ({"low": 0.08, "high": 0.16}, {"low": 0.1, "high": 0.18}),
    "Understory": ({"low": 0.03, "high": 0.12}, {"low": 0.08, "high": 0.18}),
    "Blueprint": (None, None),
    "Glaze": ({"low": 0.08, "high": 0.18}, {"low": 0.12, "high": 0.22}),
}
DRAFTS = [
    ("Sunny", "ee7cd6b20cc142429e576214b5cf199c"),
    ("Understory", "ea30f6dc23784a35a73ac7f4352c2721"),
    ("Blueprint", "49181987acf24de4adf0f5e8b79e5bff"),
    ("Glaze", "195d85e4345f4d9ab3e466d75bd58404"),
]
for label, d in DRAFTS:
    cur.execute(
        "SELECT model_input_json, repair_guidance_json, finmo_json FROM intake_consult_drafts WHERE draft_id=%s",
        (d,),
    )
    row = cur.fetchone()
    mi = json.loads(row["model_input_json"])
    rg = json.loads(row["repair_guidance_json"]) if row.get("repair_guidance_json") else {}
    fm = json.loads(row["finmo_json"])
    j = ((mi.get("solver_input") or {}).get("margin_band_judgment") or {})
    v = verify_run_acceptance(conn, draft_id=d)
    ni_detail = {}
    for c in v.get("checks") or []:
        if c.get("name") == "net_income_trajectory_viable":
            ni_detail = c.get("detail") or {}
    rows = {int(float(r.get("quarter_index"))): r for r in fm.get("quarter_rows") or [] if isinstance(r, dict)}
    r11 = rows.get(11) or {}
    rev = float(r11.get("revenue") or 1)
    print(f"== {label} ({d[:12]}) passed={v.get('passed')}")
    print(f"   band q11={j.get('q11')} q20={j.get('q20')}")
    print(f"   floors: gm={j.get('gross_margin_floor_q11')} burden={j.get('fixed_cost_burden_max_q11')} NI={j.get('ni_margin_floor_q11')}")
    print(f"   char: {j.get('margin_character')}")
    print(f"   NI check: passed_via={'ramping' if ni_detail.get('ramping_viable') else ('flat_healthy' if ni_detail.get('flat_healthy_viable') else 'FAILED')} "
          f"q11_ni={ni_detail.get('q11_ni_margin')} floor={ni_detail.get('min_required_q11_margin_flat')} src={ni_detail.get('flat_floor_source')}")
    print(f"   restructure: {bool(rg.get('restructure'))}"
          + (f" final_passed={(rg.get('restructure') or {}).get('final_passed')}" if rg.get("restructure") else ""))
    bl = BASELINE_BANDS.get(label)
    if bl and bl[0]:
        drift = (abs(float((j.get('q11') or {}).get('low') or 0) - bl[0]['low']) > 0.005
                 or abs(float((j.get('q11') or {}).get('high') or 0) - bl[0]['high']) > 0.005)
        print(f"   band drift vs baseline: {'DRIFTED from ' + str(bl[0]) if drift else 'stable'}")
cur.close()
conn.close()
