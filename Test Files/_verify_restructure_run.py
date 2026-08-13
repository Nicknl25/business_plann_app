"""Verify a draft's acceptance verdict + restructure-stage state.

Usage: _verify_restructure_run.py <draft_id>
Prints: passed/failed_checks, whether repair_guidance_json holds a
restructure directive, headcount/growth trace sources, and key FINMO
landing points (Q1/Q11/Q20 revenue, NI margin).
"""
import os
import sys
import json
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

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
    "SELECT business_name, repair_guidance_json, planning_run_json, finmo_json, model_input_json "
    "FROM intake_consult_drafts WHERE draft_id=%s LIMIT 1",
    (draft_id,),
)
row = cur.fetchone() or {}


def _j(v):
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


pr = _j(row.get("planning_run_json"))
rg = _j(row.get("repair_guidance_json"))
fm = _j(row.get("finmo_json"))
mi = _j(row.get("model_input_json"))

print("business:", row.get("business_name"))
prid = pr.get("planning_run_id")
from client_intake_and_finmo.post_intake_acceptance.gate import verify_run_acceptance

v = verify_run_acceptance(conn, draft_id=draft_id, planning_run_id=prid or None)
print("VERDICT passed:", v.get("passed"))
print("failed_checks:", v.get("failed_checks"))

rs = (rg or {}).get("restructure") or {}
print("restructure_present:", bool(rs))
if rs:
    print("restructure final_passed:", rs.get("final_passed"))
    hist = rs.get("history") or []
    print("restructure iterations:", len(hist))
    for it in hist:
        d = it.get("design") or {}
        print(
            "  iter", it.get("iteration"),
            "feasible:", it.get("feasible"),
            "verdict_after:", (it.get("verdict_after") or {}).get("passed"),
            "error:", it.get("error"),
        )
        if d:
            team = d.get("team") or {}
            pricing = d.get("pricing") or {}
            fac = d.get("facility") or {}
            gr = d.get("growth") or {}
            print("    team payroll:", team.get("annual_payroll"), "|", (team.get("structure") or "")[:100])
            print("    pricing x11/x20:", pricing.get("price_multiplier_q11"), pricing.get("price_multiplier_q20"))
            print("    rent target/q:", fac.get("quarterly_rent_target"))
            print("    growth y1/mature:", gr.get("year1_annual_growth"), gr.get("mature_annual_growth"))
            print("    overall:", (d.get("overall_rationale") or "")[:220])

si = (mi.get("solver_input") or {}) if isinstance(mi, dict) else {}
print("solver_input.restructure_directive:", bool(si.get("restructure_directive")))
hc = si.get("headcount_coherence") or {}
print("headcount_coherence:", {k: hc.get(k) for k in ("applies", "coherent_annual_payroll", "stated_annual_payroll", "notes")} if hc else None)
jg = si.get("judged_growth") or {}
print("judged_growth:", jg)

rows = {int(float(r.get("quarter_index") or 0)): r for r in (fm.get("quarter_rows") or []) if isinstance(r, dict)}
for q in (1, 5, 11, 20):
    r = rows.get(q) or {}
    rev = float(r.get("revenue") or 0.0)
    ni = float(r.get("net_income") or 0.0)
    pay = float(r.get("payroll") or 0.0)
    rent = float(r.get("lease_rent") or 0.0)
    print(
        f"Q{q}: rev={rev:,.0f} ni_margin={(ni / rev * 100.0) if rev else 0.0:.1f}% "
        f"payroll={pay:,.0f} rent={rent:,.0f}"
    )
cur.close()
conn.close()
