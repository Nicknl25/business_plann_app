"""Does the landed FINMO match the model_input G&A ratio row?"""
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
for label, prefix in (
    ("Sunny latest (PASSED)", "f8bc1b50592f"),
    ("Meridian latest (FAILED)", "37b6a30f7b3b"),
):
    cur.execute(
        "SELECT draft_id, model_input_json, finmo_json FROM intake_consult_drafts "
        "WHERE draft_id LIKE %s LIMIT 1",
        (prefix + "%",),
    )
    row = cur.fetchone()
    mi = json.loads(row["model_input_json"])
    fm = json.loads(row["finmo_json"])
    ga_vals = None
    for r in ((mi.get("sections") or {}).get("expenses") or []):
        if isinstance(r, dict) and str(r.get("label") or "") == "General & Administrative":
            ga_vals = list(r.get("values") or [])
    rows = {int(float(r.get("quarter_index"))): r for r in fm.get("quarter_rows") or [] if isinstance(r, dict)}
    print(f"== {label}")
    for q in (1, 2, 3, 5, 11):
        r = rows.get(q) or {}
        rev = float(r.get("revenue") or 1)
        ga = float(r.get("general_and_administrative") or 0)
        row_pct = round(float(ga_vals[q]) * 100, 2) if ga_vals and q < len(ga_vals) else None
        print(f"   Q{q}: FINMO G&A ${ga:,.0f} = {ga / rev * 100:.2f}% of rev | model_input row = {row_pct}%")
cur.close()
conn.close()
