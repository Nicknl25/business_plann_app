"""List every table in the DB with row counts so I know what raw data is already loaded."""
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
cur = conn.cursor()
cur.execute("SHOW TABLES")
tables = sorted([r[0] for r in cur.fetchall()])
print(f"Total tables: {len(tables)}\n")
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM `{t}`")
    n = cur.fetchone()[0]
    print(f"  {n:>10}  {t}")
conn.close()
