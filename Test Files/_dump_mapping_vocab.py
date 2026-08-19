"""Extract the distinct value_kind / target_value_kind / input_semantics
values currently seeded in post_intak_mapping_lookup. Authoritative
producer vocabulary for the Contract 1 Literal completion (P3.41 iter 2).
"""
import os
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

for col in ("value_kind", "target_value_kind", "input_semantics"):
    cur.execute(
        f"SELECT DISTINCT {col} AS v FROM post_intak_mapping_lookup "
        f"WHERE mapping_status = 'active' ORDER BY {col}"
    )
    rows = cur.fetchall()
    print(f"\n=== {col} (active rows) ===")
    for r in rows:
        print(f"  {r['v']!r}")

# Bonus: a small sample of value_kind by lever_id pattern (revenue/expenses/balance_sheet/schedules)
print("\n=== sample value_kind by section ===")
cur.execute(
    """
    SELECT
      SUBSTRING_INDEX(lever_id, '::', 1) AS section,
      value_kind,
      COUNT(*) AS n
    FROM post_intak_mapping_lookup
    WHERE mapping_status = 'active'
    GROUP BY section, value_kind
    ORDER BY section, value_kind
    """
)
for r in cur.fetchall():
    print(f"  {r['section']:<20} {r['value_kind']:<24} n={r['n']}")

# input_semantics by section too
print("\n=== sample input_semantics by section ===")
cur.execute(
    """
    SELECT
      SUBSTRING_INDEX(lever_id, '::', 1) AS section,
      input_semantics,
      COUNT(*) AS n
    FROM post_intak_mapping_lookup
    WHERE mapping_status = 'active'
    GROUP BY section, input_semantics
    ORDER BY section, input_semantics
    """
)
for r in cur.fetchall():
    print(f"  {r['section']:<20} {r['input_semantics']:<32} n={r['n']}")

conn.close()
