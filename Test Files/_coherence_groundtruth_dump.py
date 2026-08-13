"""Ground truth for the coherence v2 closed form: for each backtest
business, dump stated intake facts vs the engine's landed Q1/Q11 FINMO
rows vs the model_input Q1 basis (searcher._base_levels) vs the margin
band — so the v2 basis definition is fitted against reality, not guessed.
Read-only."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")
from client_intake_and_finmo.post_intake_restructure.searcher import _base_levels

BUSINESSES = [
    ("Sunny_V3", "Sunny Glaze Donuts", 280800),
    ("Glaze", "Sunny Glaze Donuts", 4500),
    ("Blueprint", "Blueprint%", None),
    ("Meridian", "Meridian Motorcars", None),
    ("Understory", "Understory Mushroom", None),
    ("Harvest Lane", "Harvest Lane", None),
    ("Ironthread", "Ironthread", None),
]

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


def _f(d, key, default=0.0):
    try:
        v = d.get(key)
        return default if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return default


seen = set()
for label, name, revenue_filter in BUSINESSES:
    cur.execute(
        "SELECT draft_id, business_name, model_input_json, financials_json, finmo_json, "
        "planning_run_json, repair_guidance_json, operating_model_json, updated_at "
        "FROM intake_consult_drafts WHERE business_name LIKE %s ORDER BY updated_at DESC LIMIT 8",
        (name if name.endswith("%") else name + "%",),
    )
    row = None
    for r in cur.fetchall():
        if r["draft_id"] in seen:
            continue
        fin = _j(r.get("financials_json"))
        if revenue_filter is not None and _f(fin, "current_revenue") != float(revenue_filter):
            continue
        if not str(_j(r.get("planning_run_json")).get("planning_run_id") or "").strip():
            continue
        row = r
        break
    if not row:
        print(f"=== {label}: NO DRAFT ===\n")
        continue
    seen.add(row["draft_id"])
    fin = _j(row.get("financials_json"))
    mi = _j(row.get("model_input_json"))
    fm = _j(row.get("finmo_json"))
    ops = _j(row.get("operating_model_json"))
    mb = (mi.get("solver_input") or {}).get("margin_band_judgment") or {}

    rows = {}
    for qr in fm.get("quarter_rows") or []:
        if isinstance(qr, dict):
            try:
                rows[int(float(qr.get("quarter_index")))] = qr
            except (TypeError, ValueError):
                continue

    print(f"=== {label} (draft {row['draft_id'][:12]}) stage={ops.get('business_stage')} ===")
    print(f"  STATED: rev {_f(fin,'current_revenue'):,.0f}  cogs {_f(fin,'current_cogs'):,.0f} "
          f"(pct {_f(fin,'cogs_percent_of_revenue')})  payroll {_f(fin,'current_payroll') or _f(fin,'payroll_total_year1'):,.0f}  "
          f"rent/mo {_f(fin,'monthly_rent_expense'):,.0f}  gna_abs {_f(fin,'other_opex_absolute'):,.0f} "
          f"(other_opex {_f(fin,'other_operating_expense'):,.0f})  mkt {_f(fin,'marketing_total_year1'):,.0f}")
    bl = _base_levels(mi)
    print(f"  ENGINE BASIS (_base_levels): {json.dumps(bl)}")
    ph = mi.get("payroll_headcount") or {}
    qt = ph.get("quarter_totals") or []
    if qt:
        def pq(i):
            try:
                return float((qt[i - 1] or {}).get("payroll") or 0.0)
            except (TypeError, ValueError, IndexError):
                return 0.0
        print(f"  payroll quarter_totals: Q1 {pq(1):,.0f}  Q5 {pq(5):,.0f}  Q11 {pq(11):,.0f}  (n={len(qt)})")
    if rows:
        keys = sorted(rows)
        sample = rows[keys[0]]
        for qi in (1, 5, 11, 20):
            q = rows.get(qi)
            if not q:
                continue
            def g(k):
                try:
                    return float(q.get(k) or 0.0)
                except (TypeError, ValueError):
                    return 0.0
            mkt = g("marketing") or g("sales_marketing")
            print(f"  FINMO Q{qi}: rev {g('revenue'):,.0f}  cogs {g('cogs'):,.0f}  payroll {g('payroll'):,.0f}  "
                  f"rent {g('lease_rent'):,.0f}  gna {g('other_operating_expense'):,.0f}  mkt {mkt:,.0f}  "
                  f"ebitda {g('ebitda'):,.0f} ({(g('ebitda')/g('revenue')*100) if g('revenue') else 0:.1f}%)  ni {g('net_income'):,.0f}")
        print(f"  finmo row keys: {sorted(sample.keys())}")
    else:
        print("  NO FINMO ROWS in draft")
    print(f"  margin band: q11 {mb.get('q11')}  gm_floor {mb.get('gross_margin_floor_q11')}  "
          f"burden_max {mb.get('fixed_cost_burden_max_q11')}  ni_floor {mb.get('ni_margin_floor_q11')}")
    print()

cur.close()
conn.close()
