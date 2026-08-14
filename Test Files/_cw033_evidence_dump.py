# CW-033 evidence pull: the three A-113 capacity-correction turns, the
# A-115 cogs-rate-as-price turns, and the capex "Not recently, no" turn
# from the REAL Thornfield draft d9b17850, verbatim, with indices.
import json
import os
import re
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
conn.autocommit = True
cur = conn.cursor(dictionary=True)
cur.execute(
    "SELECT draft_id, business_name, messages_json, operating_model_json, "
    "financials_json FROM intake_consult_drafts WHERE draft_id LIKE %s",
    ("d9b17850%",),
)
row = cur.fetchone()
if not row:
    print("DRAFT NOT FOUND")
    sys.exit(1)
print("draft:", row["draft_id"], "|", row["business_name"])
msgs = json.loads(row["messages_json"] or "[]")
print("messages:", len(msgs))

NEEDLES = [
    r"capacity",
    r"not recently",
    r"unit price",
    r"retention",
    r"install",
]
for i, m in enumerate(msgs):
    role = m.get("role")
    text = str(m.get("content") or "")
    low = text.lower()
    if any(re.search(n, low) for n in NEEDLES):
        print("=" * 70)
        print(f"[{i}] {role}:")
        print(text[:2600])

ops = json.loads(row["operating_model_json"] or "{}")
print("=" * 70)
print("FINAL OPS ROWS:")
for lob in ops.get("lob_models") or []:
    for p in lob.get("products") or []:
        print(
            " ", p.get("product_name"),
            "| price", p.get("unit_price"),
            "| cap", p.get("units_per_period_capacity"),
            "| util", p.get("utilization_rate"),
            "| cogs", p.get("cogs_percent_of_line_revenue"),
        )
fin = json.loads(row["financials_json"] or "{}")
for k in ("current_capex", "current_revenue", "retention_pending",
          "retention_rate_after_price_change", "cogs_percent_of_revenue"):
    print(" fin:", k, "=", fin.get(k))
cur.close()
conn.close()
