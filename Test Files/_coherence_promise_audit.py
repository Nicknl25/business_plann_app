"""THE STANDING TEST: after any coherence convergence, did restructure
fire? If yes, coherence's promise was wrong. One query over the fleet.
Read-only."""
import json
import os

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, business_name, updated_at, financials_json, repair_guidance_json, "
    "planning_run_json FROM intake_consult_drafts "
    "WHERE financials_json LIKE %s ORDER BY updated_at DESC LIMIT 200",
    ('%"_coherence"%',),
)


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


rows = cur.fetchall()
print(f"drafts with coherence state: {len(rows)}")
print(f"{'draft':14} {'business':34} {'coh status':11} {'restructured':12} {'promise'}")
broken = kept = 0
for r in rows:
    coh = (_j(r.get("financials_json")).get("_coherence")) or {}
    status = str(coh.get("status") or "-")
    restructured = bool((_j(r.get("repair_guidance_json")) or {}).get("restructure"))
    has_run = bool(str(_j(r.get("planning_run_json")).get("planning_run_id") or "").strip())
    verdict = "-"
    if status == "converged" and has_run:
        verdict = "BROKEN" if restructured else "kept"
        broken += restructured
        kept += not restructured
    print(f"{r['draft_id'][:12]:14} {str(r['business_name'])[:34]:34} {status:11} "
          f"{str(restructured):12} {verdict}")
print()
print(f"PROMISES KEPT: {kept}   PROMISES BROKEN (converged but restructure fired): {broken}")
cur.close()
conn.close()
