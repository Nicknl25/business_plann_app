"""Check actual firm_age_bucket labels in bds_firm_age."""
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
cur.execute(
    "SELECT firm_age_bucket, COUNT(*) AS n, MAX(year) AS last_y "
    "FROM bds_firm_age GROUP BY firm_age_bucket ORDER BY firm_age_bucket"
)
for r in cur.fetchall():
    print(f"  {r['firm_age_bucket']:30} n={r['n']} last_y={r['last_y']}")
conn.close()
