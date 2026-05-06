"""Probe industry_metrics_raw and industry_growth_index to understand their content."""
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

for t in ("industry_metrics_raw", "industry_growth_index", "industry_growth_table", "industry_mapping_lookup", "industry_types"):
    print(f"\n=== {t} ===")
    cur.execute(f"DESCRIBE `{t}`")
    cols = cur.fetchall()
    for c in cols:
        print(f"  {c['Field']:30} {c['Type']}")
    cur.execute(f"SELECT * FROM `{t}` LIMIT 2")
    samples = cur.fetchall()
    for i, s in enumerate(samples):
        print(f"  --- sample {i+1} ---")
        for k, v in s.items():
            sval = str(v)
            if len(sval) > 80:
                sval = sval[:77] + "..."
            print(f"    {k}: {sval}")

cur.execute("SELECT DISTINCT metric FROM industry_metrics_raw LIMIT 50")
metrics = cur.fetchall()
if metrics:
    print(f"\nindustry_metrics_raw: distinct 'metric' values (first 50):")
    for m in metrics:
        print(f"  {m}")
else:
    cur.execute("DESCRIBE industry_metrics_raw")
    cols = [c["Field"] for c in cur.fetchall()]
    print(f"\nindustry_metrics_raw columns: {cols}")

conn.close()
