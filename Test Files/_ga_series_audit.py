"""G&A rate-series audit: the Model Inputs G&A ratio row per draft,
plus the stated other-opex intake fields — across businesses and eras."""
import json
import os
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)

DRAFTS = [
    ("Meridian G&A-FIXED", "0f8e1e1c5d8d"),
    ("Meridian floors-era", "b6078ffac55a"),
    ("Meridian PASSING baseline 07-16", "e6537a2f7eb5"),
    ("Meridian PASSING baseline 07-15", "f3d67d289292"),
    ("Sunny latest", "f8bc1b50592f"),
    ("Harvest latest", "31c55af9e793"),
    ("Understory latest", "830e1409fd10"),
    ("Glaze latest", "b08703cf6e30"),
]


def _j(v):
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


for label, prefix in DRAFTS:
    cur.execute(
        "SELECT draft_id, model_input_json, financials_json FROM intake_consult_drafts "
        "WHERE draft_id LIKE %s LIMIT 1",
        (prefix + "%",),
    )
    row = cur.fetchone()
    if not row:
        print(f"== {label}: not found")
        continue
    mi = _j(row.get("model_input_json"))
    fin = _j(row.get("financials_json"))
    ga_vals = None
    for r in ((mi.get("sections") or {}).get("expenses") or []):
        if isinstance(r, dict) and str(r.get("label") or "").strip() == "General & Administrative":
            ga_vals = list(r.get("values") or [])
            break
    opex_fields = {
        k: fin.get(k) for k in fin.keys()
        if "opex" in k.lower() or "other" in k.lower() or "g_and_a" in k.lower() or "ga_" in k.lower()
    }
    rev = fin.get("current_revenue")
    print(f"== {label} ({row['draft_id'][:12]})")
    print(f"   stated: revenue={rev} opex_fields={opex_fields}")
    if ga_vals:
        pct = [round(float(v) * 100, 2) for v in ga_vals[:12]]
        print(f"   G&A ratio row (stub,Q1..Q11) %: {pct}")
    else:
        print("   G&A row: NOT FOUND")
cur.close()
conn.close()
