"""Verify the rent-degraded Sunny_V3 run (#2+#3 live exercise):
did restructure fire, is the directive within its own bounds, did the
rent target LAND on the Lease row (the new consumer), and is the final
plan viable? Read-only."""
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
    "SELECT financials_json, model_input_json, finmo_json, repair_guidance_json, planning_run_json "
    "FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,))
r = cur.fetchone()


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


fin = _j(r.get("financials_json"))
mi = _j(r.get("model_input_json"))
fm = _j(r.get("finmo_json"))
rg = _j(r.get("repair_guidance_json"))
pr = _j(r.get("planning_run_json"))
rest = rg.get("restructure") or {}
directive = rest.get("active_directive") or {}
bounds = None
for h in rest.get("history") or []:
    if isinstance(h, dict) and h.get("stage") == "bounds" and isinstance(h.get("bounds"), dict):
        bounds = h["bounds"]
        break

print("stated rent/mo:", fin.get("monthly_rent_expense"), "=> stated quarterly:", float(fin.get("monthly_rent_expense") or 0) * 3)
print("restructure fired:", bool(rest), "| final_passed:", rest.get("final_passed"), "| run:", pr.get("status"))
if directive:
    team = directive.get("team") or {}
    fac = directive.get("facility") or {}
    tb = (bounds or {}).get("team") or {}
    fb = (bounds or {}).get("facility") or {}
    print("directive team:", team.get("annual_payroll"), "| bounds team [", tb.get("min_annual_payroll"), ",", tb.get("max_annual_payroll"), "]")
    print("directive rent target:", fac.get("quarterly_rent_target"), "| bounds rent [", fb.get("min_quarterly_rent"), ",", fb.get("max_quarterly_rent"), "]")
    print("invariant_clamps:", directive.get("invariant_clamps"))
    t = team.get("annual_payroll")
    ok_team = t is None or (float(t) >= float(tb.get("min_annual_payroll") or 0) - 0.01)
    rt = fac.get("quarterly_rent_target")
    ok_rent_bounds = rt is None or (
        float(rt) >= float(fb.get("min_quarterly_rent") or 0) - 0.01
        and (not fb.get("max_quarterly_rent") or float(rt) <= float(fb.get("max_quarterly_rent")) + 0.01))
    print("INVARIANTS: team>=floor", ok_team, "| rent in bounds", ok_rent_bounds)

    lease_vals = next((row.get("values") for row in ((mi.get("sections") or {}).get("expenses") or [])
                       if isinstance(row, dict) and row.get("label") == "Lease"), [])
    rows = {int(float(q.get("quarter_index"))): q for q in (fm.get("quarter_rows") or []) if isinstance(q, dict)}
    print("Lease row: Q1", lease_vals[1] if len(lease_vals) > 1 else None,
          "Q6", lease_vals[6] if len(lease_vals) > 6 else None,
          "Q11", lease_vals[11] if len(lease_vals) > 11 else None,
          "Q20", lease_vals[20] if len(lease_vals) > 20 else None)
    q11r = rows.get(11) or {}
    print("FINMO lease_rent: Q1", (rows.get(1) or {}).get("lease_rent"),
          "Q11", q11r.get("lease_rent"),
          "| Q11 ebitda_margin:", round(float(q11r.get("ebitda") or 0) / float(q11r.get("revenue") or 1), 4))
    if rt is not None and len(lease_vals) > 11:
        landed_ok = abs(float(lease_vals[11]) - float(rt)) <= 0.01
        print("RENT LANDED (Lease Q11 == directive target):", landed_ok)
else:
    print("no active directive persisted (run may have passed without restructure or found nothing)")
cur.close()
conn.close()


