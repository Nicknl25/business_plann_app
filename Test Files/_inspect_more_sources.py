"""Inspect industry_growth_table, industry_growth_index, alpha_data,
and check what else can fill remaining coverage gaps."""
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

# alpha_data columns
print("=== alpha_data ===")
cur.execute("DESCRIBE alpha_data")
for r in cur.fetchall():
    print(f"  {r['Field']:32} {r['Type']}")
cur.execute("SELECT * FROM alpha_data LIMIT 1")
s = cur.fetchone()
if s:
    print("  --- sample ---")
    for k, v in s.items():
        sval = str(v)[:90]
        print(f"    {k}: {sval}")

# industry_growth_table - already saw schema; check year/quarter coverage
print("\n=== industry_growth_table NAICS coverage ===")
cur.execute("""
    SELECT MIN(YEAR(fiscalDateEnding)) AS min_y, MAX(YEAR(fiscalDateEnding)) AS max_y,
           COUNT(DISTINCT naics_code) AS n_naics, COUNT(*) AS rows
    FROM industry_growth_table
""")
print(cur.fetchone())

# What's in industry_growth_table for revenue growth ranges?
cur.execute("""
    SELECT naics_code, AVG(industry_revenue_growth_q) AS avg_growth,
           STDDEV(industry_revenue_growth_q) AS std_growth,
           COUNT(*) AS n
    FROM industry_growth_table
    WHERE industry_revenue_growth_q IS NOT NULL
      AND YEAR(fiscalDateEnding) >= 2020
    GROUP BY naics_code
    HAVING n >= 4
    LIMIT 5
""")
print("\nSample QoQ revenue growth from industry_growth_table:")
for r in cur.fetchall():
    print(f"  naics={r['naics_code']} avg_qoq={float(r['avg_growth'] or 0):.4f} std={float(r['std_growth'] or 0):.4f} n={r['n']}")

# Check industry_growth_index - already saw it has trust flags
print("\n=== industry_growth_index sample ===")
cur.execute("SELECT * FROM industry_growth_index LIMIT 5")
for r in cur.fetchall():
    print(f"  {r}")

# fred_macro_quarterly columns
print("\n=== fred_macro_quarterly columns ===")
cur.execute("DESCRIBE fred_macro_quarterly")
for r in cur.fetchall():
    print(f"  {r['Field']:32} {r['Type']}")

# Check if alpha_data has employee counts
print("\n=== alpha_data: any employee/headcount columns? ===")
cur.execute("SHOW COLUMNS FROM alpha_data LIKE '%emp%'")
for r in cur.fetchall():
    print(f"  {r}")
cur.execute("SHOW COLUMNS FROM alpha_data LIKE '%full%time%'")
for r in cur.fetchall():
    print(f"  {r}")

# What are the distinct firm_age_buckets in BDS?
print("\n=== BDS firm_age_buckets ===")
cur.execute("SELECT DISTINCT firm_age_bucket, COUNT(*) AS n FROM bds_firm_age GROUP BY firm_age_bucket ORDER BY firm_age_bucket")
for r in cur.fetchall():
    print(f"  {r['firm_age_bucket']:30} n={r['n']}")

conn.close()
