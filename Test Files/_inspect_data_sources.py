"""Probe what raw data is already in the DB for Phase 1 derivation."""
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

# Confirm SOI volume
cur.execute("SELECT COUNT(*) AS n FROM SOI_corporate_tax_returns")
print(f"SOI rows: {cur.fetchone()['n']}")
cur.execute(
    "SELECT naics_2_digit IS NULL AS l2_null, COUNT(*) AS n FROM SOI_corporate_tax_returns GROUP BY l2_null"
)
print("SOI NAICS-2 null breakdown:", cur.fetchall())
cur.execute(
    "SELECT "
    "  SUM(CASE WHEN naics_6_digit IS NOT NULL AND naics_6_digit<>'' THEN 1 ELSE 0 END) AS l6, "
    "  SUM(CASE WHEN naics_5_digit IS NOT NULL AND naics_5_digit<>'' THEN 1 ELSE 0 END) AS l5, "
    "  SUM(CASE WHEN naics_4_digit IS NOT NULL AND naics_4_digit<>'' THEN 1 ELSE 0 END) AS l4, "
    "  SUM(CASE WHEN naics_3_digit IS NOT NULL AND naics_3_digit<>'' THEN 1 ELSE 0 END) AS l3, "
    "  SUM(CASE WHEN naics_2_digit IS NOT NULL AND naics_2_digit<>'' THEN 1 ELSE 0 END) AS l2 "
    "FROM SOI_corporate_tax_returns"
)
print(f"SOI coverage by level: {cur.fetchone()}")

# Confirm OEWS schema/volume
cur.execute("SHOW TABLES LIKE 'oews%'")
print(f"OEWS-like tables: {cur.fetchall()}")

# Find any oews table
cur.execute("SHOW TABLES")
all_tables = [list(r.values())[0] for r in cur.fetchall()]
print(f"\nAll tables ({len(all_tables)}):")
for t in all_tables:
    if "oews" in t.lower() or "wage" in t.lower() or "qcew" in t.lower() or "naics" in t.lower() or "census" in t.lower() or "industry" in t.lower() or "soi" in t.lower():
        cur.execute(f"SELECT COUNT(*) AS n FROM `{t}`")
        n = cur.fetchone()["n"]
        print(f"  {t}: {n} rows")

# Show schema of OEWS-like
for t in all_tables:
    if "oews" in t.lower():
        print(f"\n--- {t} schema ---")
        cur.execute(f"DESCRIBE `{t}`")
        for r in cur.fetchall():
            print(f"  {r['Field']:30} {r['Type']}")
        cur.execute(f"SELECT * FROM `{t}` LIMIT 1")
        sample = cur.fetchone()
        if sample:
            print(f"  sample row: {dict(list(sample.items())[:8])}")
        break

# naics_master
cur.execute("SHOW TABLES LIKE 'naics_master'")
if cur.fetchone():
    cur.execute("SELECT COUNT(*) AS n FROM naics_master")
    print(f"\nnaics_master rows: {cur.fetchone()['n']}")
    cur.execute("DESCRIBE naics_master")
    for r in cur.fetchall():
        print(f"  {r['Field']:30} {r['Type']}")

# Check if baseline lookup already exists
cur.execute("SHOW TABLES LIKE 'post_intake_industry_baseline_lookup'")
print(f"\npost_intake_industry_baseline_lookup exists: {bool(cur.fetchone())}")

conn.close()
