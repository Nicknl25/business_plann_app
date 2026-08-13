import json, os, sys
from dotenv import load_dotenv
import mysql.connector
load_dotenv()
conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306))
cur = conn.cursor(dictionary=True)

def _j(v):
    try: return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception: return {}

for draft_id, label in [("98a147fd8d0d", "Ironthread"), ("ea30f6dc2378", "Understory")]:
    cur.execute("SELECT draft_id, model_input_json, finmo_json, repair_guidance_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (draft_id + "%",))
    r = cur.fetchone()
    if not r:
        print(label, "not found"); continue
    fm = _j(r.get("finmo_json"))
    rows = fm.get("quarter_rows") or []
    print(f"=== {label} ({r['draft_id'][:12]}) landed FINMO ===")
    for qi in (1, 6, 11):
        if qi < len(rows) and isinstance(rows[qi], dict):
            q = rows[qi]
            def g(k):
                try: return float(q.get(k) or 0.0)
                except Exception: return 0.0
            print(f"  Q{qi}: rev {g('revenue'):,.0f}  payroll {g('payroll'):,.0f}  rent {g('lease_rent'):,.0f}  "
                  f"other_opex {g('other_operating_expense'):,.0f}  ebitda {g('ebitda'):,.0f}  ni {g('net_income'):,.0f}")
    rg = _j(r.get("repair_guidance_json"))
    rest = rg.get("restructure") or {}
    if rest:
        base = rest.get("baseline") or rest.get("baseline_metrics") or {}
        print(f"  restructure baseline keys: {list(base)[:8] if isinstance(base, dict) else type(base)}")
        if isinstance(base, dict):
            for k in ("q11_revenue", "q11_net_income_margin", "q11_ebitda_margin", "quarterly_revenue"):
                if k in base: print(f"    {k}: {base[k]}")
    print()
cur.close(); conn.close()
