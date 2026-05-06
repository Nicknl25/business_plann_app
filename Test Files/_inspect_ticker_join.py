"""Confirm the ticker -> NAICS join path for alpha_data."""
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

print("=== ticker_metadata ===")
cur.execute("DESCRIBE ticker_metadata")
for r in cur.fetchall():
    print(f"  {r['Field']:30} {r['Type']}")
cur.execute("SELECT * FROM ticker_metadata LIMIT 2")
for s in cur.fetchall():
    print("  --- sample ---")
    for k, v in s.items():
        print(f"    {k}: {str(v)[:80]}")

print("\n=== alpha_match_naics_industry ===")
cur.execute("DESCRIBE alpha_match_naics_industry")
for r in cur.fetchall():
    print(f"  {r['Field']:30} {r['Type']}")
cur.execute("SELECT * FROM alpha_match_naics_industry LIMIT 2")
for s in cur.fetchall():
    print("  --- sample ---")
    for k, v in s.items():
        print(f"    {k}: {str(v)[:80]}")

print("\n=== industry_growth_table NAICS coverage ===")
cur.execute(
    "SELECT MIN(YEAR(fiscalDateEnding)) AS min_y, MAX(YEAR(fiscalDateEnding)) AS max_y, "
    "       COUNT(DISTINCT naics_code) AS n_naics, COUNT(*) AS row_count "
    "FROM industry_growth_table"
)
print(f"  {cur.fetchone()}")

# Test if alpha_data has deferredRevenue values
print("\n=== alpha_data: deferredRevenue presence ===")
cur.execute(
    "SELECT COUNT(*) AS total, "
    "       SUM(CASE WHEN deferredRevenue IS NOT NULL AND deferredRevenue NOT IN ('','None','null','0') THEN 1 ELSE 0 END) AS with_dr "
    "FROM alpha_data"
)
print(f"  {cur.fetchone()}")

print("\n=== alpha_data: dividendPayout presence ===")
cur.execute(
    "SELECT COUNT(*) AS total, "
    "       SUM(CASE WHEN dividendPayout IS NOT NULL AND dividendPayout NOT IN ('','None','null','0') THEN 1 ELSE 0 END) AS with_div "
    "FROM alpha_data"
)
print(f"  {cur.fetchone()}")

conn.close()
