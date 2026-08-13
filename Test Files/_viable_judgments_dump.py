"""Executive judgments (with rationales) for a viable run's draft."""
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
    "SELECT business_name, model_input_json FROM intake_consult_drafts WHERE draft_id LIKE %s",
    (draft_id + "%",),
)
row = cur.fetchone() or {}
mi = json.loads(row.get("model_input_json") or "{}")
si = (mi.get("solver_input") or {})
print("=== ", row.get("business_name"))
for key in ("headcount_coherence", "margin_band_judgment", "judged_growth", "wc_judgment"):
    v = si.get(key)
    if not isinstance(v, dict):
        continue
    print(f"\n[{key}]")
    if key == "wc_judgment":
        for dk, dv in (v.get("drivers") or {}).items():
            if isinstance(dv, dict):
                print(f"  {dk}: q1={dv.get('q1')} q11={dv.get('q11')} q20={dv.get('q20')} applicable={dv.get('applicable')}")
                print(f"    WHY: {str(dv.get('rationale') or '')[:400]}")
    else:
        for k2, v2 in v.items():
            if k2 in ("rationale", "coherent_structure"):
                print(f"  {k2}: {str(v2)[:400]}")
            elif isinstance(v2, dict):
                print(f"  {k2}: {json.dumps({a: b for a, b in v2.items() if a != 'rationale'}, default=str)[:200]}")
                if v2.get("rationale"):
                    print(f"    WHY: {str(v2.get('rationale'))[:400]}")
            else:
                print(f"  {k2}: {str(v2)[:200]}")
cur.close()
conn.close()
