"""Dump the restructure history stages + the runner's directive trace
for the rent-degraded run (landing-fidelity #2 diagnosis). Read-only."""
import json
import os

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
DRAFT = "85a94aca42e447e1af12ed7a64499cb4"

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT repair_guidance_json, planning_run_json, planning_runtime_json "
    "FROM intake_consult_drafts WHERE draft_id=%s",
    (DRAFT,))
r = cur.fetchone()


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


rest = _j(r.get("repair_guidance_json")).get("restructure") or {}
print("final_passed:", rest.get("final_passed"))
for h in rest.get("history") or []:
    if not isinstance(h, dict):
        continue
    line = {"stage": h.get("stage")}
    for k in ("found", "approved", "feasible_region_exists", "verdict_after", "evals",
              "no_realistic_design_exists", "revenue_story_required", "error"):
        if k in h:
            line[k] = h[k]
    cand = h.get("candidate") or (h.get("landing") or {})
    if isinstance(cand, dict) and cand.get("quarterly_rent") is not None:
        line["candidate_rent"] = cand.get("quarterly_rent")
        line["candidate_payroll"] = cand.get("annual_payroll")
    print(json.dumps(line, default=str)[:600])

for col in ("planning_run_json", "planning_runtime_json"):
    s = json.dumps(_j(r.get(col)))
    for token in ("restructure_directive_trace", "rent_target", '"facility"'):
        idx = s.find(token)
        if idx >= 0:
            print(f"\n{col} '{token}':", s[idx:idx + 350])
cur.close()
conn.close()

