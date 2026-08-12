"""THE THISTLEDOWN FIXTURE (#138 red-proof): the client's unanswered
question - "shouldn't bikes and repairs carry different costs?" - is now
answered BY CONSTRUCTION: the fitted judge proposes per-line COGS in one
breath and the proposal copy names each line with its own percent.

GREEN (new code): cogs_per_line present, two entries, retail line above
the service line, message names both. RED (stash/old code): the baseline
carries no cogs_per_line and the copy proposes one blended percent."""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "C:/dev/business_plann_app/python")
from dotenv import load_dotenv

load_dotenv("C:/dev/business_plann_app/.env")
import mysql.connector

from api_handlers.intake_consult import (
    _compute_cogs_baseline,
    _build_cogs_baseline_message,
)
from client_intake_and_finmo.financials_year1 import assemble_financials_year1

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"),
    autocommit=True,
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT operating_model_json, people_json, target_market_json, "
    "financials_year1_json FROM intake_consult_drafts WHERE draft_id LIKE 'be84629a%'")
row = cur.fetchone()
ops = json.loads(row["operating_model_json"] or "{}")
people = json.loads(row["people_json"] or "{}")
market = json.loads(row["target_market_json"] or "{}")
y1 = json.loads(row["financials_year1_json"] or "{}")
if not y1.get("company_revenue_total_year1"):
    y1 = assemble_financials_year1({"operating_model": ops}, y1)

shared = {"operating_model": ops, "people_capability": people, "target_market": market}
baseline = _compute_cogs_baseline(
    conn=conn, ops_json=ops, shared_context=shared, financials_year1_json=y1,
)
if not isinstance(baseline, dict):
    print("VERDICT: baseline is None (judge unavailable)")
    sys.exit(1)

per_line = baseline.get("cogs_per_line")
print("blend:", round(float(baseline.get("baseline_cogs_percent") or 0), 4),
      "band:", baseline.get("cogs_fit_band"))
if isinstance(per_line, list):
    for item in per_line:
        print("LINE:", item.get("line_name"), "->", item.get("cogs_percent"),
              "band:", item.get("band"), "shared:", item.get("shares_cost_structure_with"))
msg = _build_cogs_baseline_message(baseline)
print()
print("PROPOSAL COPY:")
print(msg)
print()
retail = next((i for i in (per_line or []) if "bike sale" in str(i.get("line_name", "")).lower()
               or "sale" in str(i.get("product_name", "")).lower()), None)
service = next((i for i in (per_line or []) if "repair" in str(i.get("line_name", "")).lower()
                or "repair" in str(i.get("product_name", "")).lower()), None)
print("VERDICT:")
print("  per-line present (2 entries):", isinstance(per_line, list) and len(per_line) == 2)
print("  retail line found:", retail is not None, "| service line found:", service is not None)
if retail and service:
    print("  retail pct > service pct (goods carry materials):",
          float(retail["cogs_percent"]) > float(service["cogs_percent"]))
print("  copy names both lines:", ("epair" in msg) and ("ike" in msg))
print("  copy invites collapse:", "treat them as one" in msg.lower() or "as one" in msg.lower())
