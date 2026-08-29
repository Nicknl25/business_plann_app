"""STORED payload vs the payload the CURRENT producer authors, for named people.

The workbook exporter renders intake_consult_drafts.payroll_headcount as stored -
it does NOT re-run the payroll producer. So a named person reading 1.28 in a
built workbook may be a STALE payload rather than live behaviour. This puts the
two side by side. (mini, 2026-08-28)

usage: python mini_stored_vs_rebuilt.py <prefix> [prefix...]
"""
import json, os, sys
import mysql.connector
from dotenv import load_dotenv

ROOT = r"C:\dev\business_plann_app"
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "python", "client_intake_and_finmo"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(os.path.join(ROOT, ".env"))
from client_intake_and_finmo.post_intake_headcount import schedule as S


def L(v):
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return {}


def named_fte(rows):
    out = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("staffing_class") or "").lower() != "key_person":
            continue
        who = str(r.get("person_name") or r.get("position_title") or "?")
        out.setdefault(who, set()).add(round(float(r.get("ending_fte") or 0.0), 4))
    return {k: sorted(v) for k, v in out.items()}


c = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
                            password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), autocommit=True)
cur = c.cursor(dictionary=True)
for prefix in sys.argv[1:]:
    cur.execute("SELECT draft_id, business_name, people_json, operating_model_json, model_input_json, "
                "payroll_headcount, updated_at FROM intake_consult_drafts WHERE draft_id LIKE %s", (prefix + "%",))
    d = cur.fetchone()
    if not d:
        print(prefix, "NO DRAFT"); continue
    ph = L(d["payroll_headcount"])
    stored = named_fte(ph.get("rows"))
    grid = [r for r in (ph.get("rows") or [])
            if str(r.get("staffing_class") or "").lower() != "key_person"]
    contract = {
        "payroll_headcount_grid": grid,
        "capacity_labor_model": ph.get("capacity_labor_model") or "labor_driven",
        "labor_intensity_class": ph.get("labor_intensity_class") or "medium",
        "wage_positioning_tier": ph.get("wage_positioning_tier") or "market",
        "wage_positioning_multiplier": ph.get("wage_positioning_multiplier") or 1.0,
        "capacity_units_per_supporting_fte": ph.get("capacity_units_per_supporting_fte") or 1.0,
        "target_payroll_percent_of_revenue": ph.get("target_payroll_percent_of_revenue") or 0.0,
    }
    try:
        payload = S._build_payroll_headcount_payload_from_contract(
            contract, draft_id=d["draft_id"], client_id="",
            model_input_json=L(d["model_input_json"]),
            business_facts={"business_name": d["business_name"]},
            ops_json=L(d["operating_model_json"]),
            people_json=L(d["people_json"]))
        rebuilt = named_fte(payload.get("rows"))
        err = None
    except Exception as e:
        rebuilt, err = {}, "%s: %s" % (type(e).__name__, str(e)[:90])
    print("\n=== %s  %s   (payload stored %s) ===" % (prefix, d["business_name"], d["updated_at"]))
    if err:
        print("   REBUILD ERROR:", err)
    for who in sorted(set(stored) | set(rebuilt)):
        s, r = stored.get(who), rebuilt.get(who)
        mark = "" if s == r else "   <<< STORED != REBUILT"
        print("   %-38.38s stored=%-26.26s rebuilt=%s%s" % (who, s, r, mark))
cur.close(); c.close()
