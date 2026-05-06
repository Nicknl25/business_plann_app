import os
import sys
import json
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
draft_id = sys.argv[1]
conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    port=int(os.getenv("MYSQL_PORT") or 3306),
)
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT business_name, financials_json, financials_year1_json, operating_model_json, model_input_json "
    "FROM intake_consult_drafts WHERE draft_id=%s LIMIT 1",
    (draft_id,),
)
row = cur.fetchone()
print(f"Business: {row['business_name']}")
fin = json.loads(row["financials_json"]) if row["financials_json"] else {}
y1 = json.loads(row["financials_year1_json"]) if row["financials_year1_json"] else {}
op = json.loads(row["operating_model_json"]) if row["operating_model_json"] else {}
print("\n--- financials_json keys ---")
print(list(fin.keys())[:50])
print("\n--- key financials ---")
for k in (
    "annual_revenue", "year1_revenue", "current_quarter_revenue",
    "starting_revenue", "monthly_revenue", "current_revenue",
    "owner_compensation", "key_person_wages", "taxes_percent",
    "growth_assumption", "stage_classification", "planning_mode",
):
    if k in fin:
        print(f"  {k}: {fin[k]}")
print("\n--- year1 ---")
print(json.dumps(y1, indent=2)[:2000] if y1 else "(empty)")
print("\n--- op_model_json keys ---")
print(list(op.keys())[:50])
for k in ("capacity", "unit_price", "utilization", "revenue_drivers"):
    if k in op:
        print(f"  {k}: {op[k]}")
mi = json.loads(row["model_input_json"]) if row["model_input_json"] else None
print("\n--- model_input present? ---")
print(bool(mi))
conn.close()
