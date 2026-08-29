import json, sys, traceback
from pathlib import Path
REPO = Path(r"C:\dev\business_plann_app")
sys.path.insert(0, str(REPO / "python")); sys.path.insert(0, str(REPO / "python" / "client_intake_and_finmo"))
try:
    from dotenv import load_dotenv; load_dotenv(REPO / ".env")
except Exception: pass
from client_intake_and_finmo.post_intake_headcount import schedule as S
from intake_submission import get_mysql_connection

def L(v):
    if v is None: return {}
    if isinstance(v,(dict,list)): return v
    try: return json.loads(v)
    except Exception: return {}

conn = get_mysql_connection(); cur = conn.cursor(dictionary=True)
cur.execute("SELECT draft_id, client_id, business_name, people_json, operating_model_json, model_input_json, payroll_headcount FROM intake_consult_drafts WHERE payroll_headcount IS NOT NULL AND people_json IS NOT NULL")
drafts = cur.fetchall(); conn.close()
print("drafts with stored payroll:", len(drafts), flush=True)

VS_USED = {"52cf5792","7042ce1a","cc8b7081","1b9b4e45","ecd0e148","46ae584a"}
frac, errs, ok = [], [], 0
for _i, d in enumerate(drafts):
    if _i % 25 == 0: print("  ..%d" % _i, flush=True)
    did = str(d["draft_id"]); short = did[:8]
    try:
        ph = L(d["payroll_headcount"])
        contract = ph.get("source_contract") or ph.get("contract") or None
        # rebuild the CONTRACT shape the producer consumes from the stored grid
        grid = ph.get("payroll_headcount_grid")
        if grid is None:
            grid = [r for r in (ph.get("rows") or []) if str(r.get("staffing_class") or "").lower() != "key_person"]
        contract = {
            "payroll_headcount_grid": grid,
            "capacity_labor_model": ph.get("capacity_labor_model") or "labor_driven",
            "labor_intensity_class": ph.get("labor_intensity_class") or "medium",
            "wage_positioning_tier": ph.get("wage_positioning_tier") or "market",
            "wage_positioning_multiplier": ph.get("wage_positioning_multiplier") or 1.0,
            "capacity_units_per_supporting_fte": ph.get("capacity_units_per_supporting_fte") or 1.0,
            "target_payroll_percent_of_revenue": ph.get("target_payroll_percent_of_revenue") or 0.0,
        }
        payload = S._build_payroll_headcount_payload_from_contract(
            contract, draft_id=did, client_id=d.get("client_id"),
            model_input_json=L(d["model_input_json"]),
            business_facts={"business_name": d.get("business_name")},
            ops_json=L(d["operating_model_json"]),
            people_json=L(d["people_json"]),
        )
        ok += 1
        for r in (payload.get("rows") or []):
            if str(r.get("staffing_class") or "").lower() != "key_person": continue
            fte = float(r.get("ending_fte") or 0.0)
            if abs(fte - 1.0) > 1e-9:
                frac.append((short, d.get("business_name"), int(r.get("quarter_index") or 0),
                             r.get("person_name") or r.get("position_title"), round(fte,4),
                             str(r.get("wage_source") or ""), int(r.get("annual_wage") or 0)))
    except Exception as e:
        errs.append((short, type(e).__name__, str(e)[:110]))

print("rebuilt OK:", ok, " errors:", len(errs))
print("\n=== NAMED-PERSON ROWS WITH FTE != 1.0 (post-fix, real producer path) ===")
seen=set(); 
for f in frac:
    k=(f[0], f[3], f[4])
    if k in seen: continue
    seen.add(k)
    print("  ", f[0], "|", (f[1] or "")[:24], "| Q%-2d"%f[2], "|", str(f[3])[:30], "| fte=", f[4], "| wage=", f[6], "|", f[5][:48])
print("\ndistinct (draft,person,fte) fractional:", len(seen))
print("distinct drafts with a fractional named person:", len({f[0] for f in frac}))
print("of those, drafts VS did NOT use:", sorted({f[0] for f in frac} - VS_USED))
print("\nERRORS (first 12):")
for e in errs[:12]: print("  ", e)
