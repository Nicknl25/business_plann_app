import json, os, sys
import mysql.connector

DRAFT = "f62e846077ef40ca96f37edafb97a6fe"
RUN = "22e3db068db1401f84ffb0cb322e20f3"

conn = mysql.connector.connect(host="localhost", user="root", password="Lovers251979!", database="biz_plan_revert")
cur = conn.cursor(dictionary=True)

cur.execute("SHOW COLUMNS FROM intake_consult_drafts")
cols = [r["Field"] for r in cur.fetchall()]
print("DRAFT COLUMNS:", [c for c in cols if "json" in c or "payroll" in c or "finmo" in c or "people" in c or "financial" in c])

cur.execute("SELECT * FROM intake_consult_drafts WHERE draft_id=%s", (DRAFT,))
r = cur.fetchone()
if not r:
    print("NO DRAFT"); sys.exit(1)
print("business_name:", r.get("business_name"))

def j(col):
    v = r.get(col)
    if not v: return {}
    try: return json.loads(v)
    except Exception: return {}

fin = j("financials_json")
mi = j("model_input_json")
people = j("people_json")
ph = j("payroll_headcount")
finmo = j("finmo_json") if "finmo_json" in cols else {}

print("\n--- financials_json keys of interest ---")
for k in sorted(fin.keys()):
    v = fin[k]
    if isinstance(v, (int, float, str)):
        s = str(v)
        if any(t in k.lower() for t in ["cash", "debt", "fund", "loan", "payroll", "wage", "revenue", "strategy"]):
            print(f"  fin.{k} = {s[:90]}")

si = mi.get("solver_input") or {}
cj = si.get("cash_judgment") or {}
print("\n--- cash_judgment ---")
print(json.dumps(cj, indent=1)[:3000])

print("\n--- people_json roles ---")
print(json.dumps(people, indent=1)[:2500])

print("\n--- payroll_headcount top-level ---")
print("keys:", list(ph.keys()))
for k in ("capacity_labor_model","labor_intensity_class","wage_positioning_tier","wage_positioning_multiplier","capacity_units_per_supporting_fte","target_payroll_percent_of_revenue","contract_version"):
    print(f"  ph.{k} = {ph.get(k)}")
rows = ph.get("rows") or []
print("row count:", len(rows))
seen = {}
for row in rows:
    key = (row.get("position_title") or row.get("oews_occ_title"), row.get("staffing_class"), row.get("wage_source"))
    if key not in seen:
        seen[key] = row
for key, row in seen.items():
    print("ROW SAMPLE:", json.dumps({k: row.get(k) for k in ("quarter_index","position_title","staffing_class","annual_wage","payroll_taxes_benefits_percent","wage_positioning_multiplier","wage_source","oews_occ_title","starting_fte","ending_fte","quarterly_wage_cost","quarterly_taxes_benefits","total_quarterly_payroll")}))
qt = ph.get("quarter_totals") or []
print("quarter_totals:", [(q.get("quarter_index"), q.get("payroll"), q.get("ending_fte")) for q in qt])

print("\n--- finmo quarter rows (cash/debt) ---")
qr = (finmo.get("quarter_rows") if isinstance(finmo, dict) else None) or []
if not qr and isinstance(finmo, dict):
    print("finmo keys:", list(finmo.keys())[:40])
for row in qr:
    if not isinstance(row, dict): continue
    print({k: row.get(k) for k in ("quarter_index","ending_cash","debt_opening_balance","debt_issuance","debt_repayment","debt_ending_balance","distributions","payroll","total_revenue") if k in row})

print("\n--- model_input drivers: Payroll row values ---")
sections = mi.get("sections") or {}
for row in (sections.get("expenses") or []):
    if isinstance(row, dict) and str(row.get("label","")).strip() == "Payroll":
        print("Payroll driver values:", row.get("values"))

print("\n--- model_input exact levers: debt/distribution series ---")
for name in ("debt_issuance","debt_repayment","distributions","owners_capital"):
    for section, rows2 in sections.items():
        if not isinstance(rows2, list): continue
        for row in rows2:
            if isinstance(row, dict) and name.replace("_"," ") in str(row.get("label","")).lower():
                print(section, row.get("label"), (row.get("values") or [])[:21])

# planning run tables
cur.execute("SHOW TABLES")
tables = [list(t.values())[0] for t in cur.fetchall()]
cand = [t for t in tables if "run" in t or "debt" in t or "cash" in t]
print("\nRUN/DEBT/CASH TABLES:", cand)
conn.close()
