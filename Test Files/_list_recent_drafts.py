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
    "SELECT draft_id, business_name, updated_at FROM intake_consult_drafts "
    "WHERE finmo_json IS NOT NULL ORDER BY updated_at DESC LIMIT 30"
)
for r in cur.fetchall():
    print(r["updated_at"], r["draft_id"][:12], r["business_name"])
cur.close()
conn.close()
