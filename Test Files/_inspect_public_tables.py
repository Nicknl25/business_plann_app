"""Inspect schemas of public-data tables to plan the metric derivation."""
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
for t in ("cbp_2022_raw", "bds_firm_age", "bds_firm_size", "sba_loan_7a_raw", "industry_growth_index"):
    print(f"\n=== {t} ===")
    cur.execute(f"DESCRIBE `{t}`")
    for r in cur.fetchall():
        print(f"  {r['Field']:32} {r['Type']}")
    cur.execute(f"SELECT * FROM `{t}` LIMIT 1")
    s = cur.fetchone()
    if s:
        print("  --- sample ---")
        for k, v in s.items():
            sval = str(v)[:80]
            print(f"    {k}: {sval}")
conn.close()
