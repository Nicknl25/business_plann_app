"""Inspect the walk-E2E draft's coherence state: bounds the executive
authored, corner arithmetic, eval, and whether ops_line_split parsed
the live ops shape. Read-only."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
sys.path.insert(0, "C:/dev/business_plann_app/python")
from client_intake_and_finmo.intake_coherence.controller import ops_line_split

DRAFT = "cb40cca7334149b7b390356ee490c7d5"

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT operating_model_json, financials_json FROM intake_consult_drafts WHERE draft_id=%s",
    (DRAFT,),
)
r = cur.fetchone()


def _j(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or {})
    except Exception:
        return {}


ops = _j(r.get("operating_model_json"))
fin = _j(r.get("financials_json"))
coh = fin.get("_coherence") or {}

print("=== coherence state ===")
print("status:", coh.get("status"))
print("eval:", json.dumps(coh.get("eval"), indent=1)[:900])
print("corner:", json.dumps(coh.get("corner"), indent=1)[:600])
print("bounds_error:", coh.get("bounds_error"))
b = coh.get("bounds") or {}
print("bounds.feasible:", b.get("feasible_region_exists"))
print("bounds.existing_lines:", json.dumps(b.get("existing_lines"))[:500])
print("bounds.new_lines:", json.dumps(b.get("new_line_candidates"))[:400])
print("bounds.team:", json.dumps(b.get("team")))
print("bounds.facility:", json.dumps(b.get("facility")))
print("bounds.cost_floors:", json.dumps(b.get("cost_floors")))

print()
print("=== ops shape / split ===")
lobs = ops.get("lob_models") or []
print("lob_models count:", len(lobs))
for l in lobs[:3]:
    if isinstance(l, dict):
        prods = l.get("products") or []
        print(" lob:", l.get("lob") or l.get("name"), "| products:", len(prods))
        for p in prods[:3]:
            if isinstance(p, dict):
                print("   product keys:", sorted(p.keys()))
                print("   product:", json.dumps({k: p.get(k) for k in ("product", "name", "unit_price", "units_per_period_capacity", "units_per_week_capacity", "utilization_rate", "operating_periods_per_year")}))
split = ops_line_split(ops, fin)
print("ops_line_split ->", json.dumps(split, indent=1)[:600])
print()
print("fin stated: rev", fin.get("current_revenue"), "cogs_pct", fin.get("cogs_percent_of_revenue"),
      "payroll", fin.get("current_payroll"), "rent/mo", fin.get("monthly_rent_expense"),
      "other_opex/mo", fin.get("other_operating_expense"), "mkt", fin.get("marketing_total_year1"),
      "owner_comp", fin.get("owner_compensation"))
cur.close()
conn.close()
