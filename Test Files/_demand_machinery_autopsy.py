"""DEMAND JUDGE research - autopsy of the dormant demand machinery.
Runs _compute_marketing_model_json OFFLINE against the real Sunny
canary draft (US, consumer, donut shop) with the silent except REMOVED
so the actual failure surfaces. Read-only (nothing persisted)."""
import json
import os
import sys
import traceback

sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

from api_handlers.intake_consult import (  # noqa: E402
    _compute_marketing_model_json,
)
from api_handlers import intake_consult as ic  # noqa: E402

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s",
    ("fad47464%",))
r = cur.fetchone()
ops = json.loads(r["operating_model_json"] or "{}")
mkt = json.loads(r["target_market_json"] or "{}")
ppl = json.loads(r["people_json"] or "{}")
y1 = json.loads(r["financials_year1_json"] or "{}")
bf = {"business_name": r.get("business_name"),
      "address": r.get("business_address"),
      "address_street": r.get("address_street"),
      "address_city": r.get("address_city"),
      "address_state": r.get("address_state"),
      "address_zip": r.get("address_zip"),
      "address_country": r.get("address_country"),
      "start_date": str(r.get("business_start_date") or "")}
print("address_country:", repr(r.get("address_country")),
      "zip:", repr(r.get("address_zip")))
print("stored marketing_model_json:", repr((r.get("marketing_model_json") or "")[:80]))

# The estimator dependency the handler injects - find its real import.
est = getattr(ic, "estimate_marketing_baseline_from_context", None)
print("estimator on module:", est)
if est is None:
    try:
        from client_intake_and_finmo.marketing_baseline import (
            estimate_marketing_baseline_from_context as est,
        )
        print("estimator imported from marketing_baseline")
    except Exception as exc:
        print("estimator import FAILED:", exc)
        est = lambda **kw: None  # noqa: E731

try:
    model = _compute_marketing_model_json(
        conn=conn, ops_json=ops, market_json=mkt, people_json=ppl,
        financials_year1_json=y1, business_facts=bf,
        existing_marketing_model_json={},
        estimate_marketing_baseline_from_context=est,
    )
    print("\nRESULT keys:", sorted(model.keys()))
    print(json.dumps({k: model.get(k) for k in (
        "ready", "missing_dependencies", "estimation_method",
        "estimation_status", "estimation_warning", "reachable_market",
        "capture_rate_year1", "expected_units_year1", "required_units_year1",
        "marketing_intensity", "baseline_marketing_percent",
        "demand_supports_required_units", "marketing_basis_summary",
        "market_basis_type")}, indent=1, default=str)[:2000])
    print("b2c_basis_counts:", json.dumps(model.get("b2c_basis_counts"))[:400])
except Exception:
    print("\nCOMPUTE RAISED:")
    traceback.print_exc()
cur.close()
conn.close()
