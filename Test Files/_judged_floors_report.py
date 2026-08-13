"""Judged-floors validation report: per draft — verdict, the executive's
authored floors (with character + rationale), the two structural-check
memo rows (actual vs floor), and floor_source provenance."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")

BUSINESSES = [
    ("Sunny_V3 canary", "Sunny Glaze Donuts", 280800),
    ("Glaze", "Sunny Glaze Donuts", 4500),
    ("Blueprint control", "Blueprint Ledger Advisory LLC", None),
    ("Meridian", "Meridian Motorcars, LLC", None),
    ("Understory", "Understory Mushroom Co.", None),
]

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance

seen = set()
for label, name, revenue_filter in BUSINESSES:
    q = (
        "SELECT draft_id, model_input_json, realism_memo_json, repair_guidance_json, "
        "planning_run_json, financials_json, updated_at FROM intake_consult_drafts "
        "WHERE business_name LIKE %s ORDER BY updated_at DESC LIMIT 6"
    )
    cur.execute(q, (name.split(" LLC")[0] + "%",))
    rows = cur.fetchall()
    row = None
    for r in rows:
        if r["draft_id"] in seen:
            continue
        fin = _j(r.get("financials_json"))
        if revenue_filter is not None and float(fin.get("current_revenue") or 0) != float(revenue_filter):
            continue
        row = r
        break
    if not row:
        print(f"=== {label}: NO DRAFT FOUND ===\n")
        continue
    seen.add(row["draft_id"])
    mi = _j(row.get("model_input_json"))
    memo = _j(row.get("realism_memo_json"))
    pr = _j(row.get("planning_run_json"))
    rg = _j(row.get("repair_guidance_json"))
    judgment = ((mi.get("solver_input") or {}).get("margin_band_judgment") or {})
    gm_floor = judgment.get("gross_margin_floor_q11")
    burden_max = judgment.get("fixed_cost_burden_max_q11")
    v = verify_run_acceptance(
        conn, draft_id=row["draft_id"],
        planning_run_id=str(pr.get("planning_run_id") or "").strip() or None,
    )
    print(f"=== {label} (draft {row['draft_id'][:12]}, {row['updated_at']}) ===")
    print(f"  VERDICT passed: {v.get('passed')}  failed: {v.get('failed_checks')}")
    print(f"  restructure_present: {bool(rg.get('restructure'))}")
    print(f"  margin_character: {judgment.get('margin_character')}")
    print(f"  judged bands q11: {judgment.get('q11')}  q20: {judgment.get('q20')}")
    print(f"  GM FLOOR: {'JUDGED ' + str(gm_floor) if gm_floor is not None else 'FALLBACK 0.20'}"
          f"   BURDEN MAX: {'JUDGED ' + str(burden_max) if burden_max is not None else 'FALLBACK 0.65'}")
    for r2 in memo.get("results") or []:
        if not isinstance(r2, dict):
            continue
        mk = str(r2.get("metric_key") or "")
        if mk in ("gross_margin_supports_ebitda_recovery", "fixed_cost_burden_reduced_or_scaled_by_q11"):
            print(f"  {mk}: status={r2.get('status')} shifted_value={r2.get('actual_value')}")
    rationale = str(judgment.get("rationale") or "")
    if rationale:
        print(f"  WHY: {rationale[:350]}")
    print()
cur.close()
conn.close()
