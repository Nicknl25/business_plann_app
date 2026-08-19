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
    "SELECT draft_id, business_name, active_focus, status, updated_at "
    "FROM intake_consult_drafts WHERE business_name LIKE %s "
    "ORDER BY updated_at DESC LIMIT 30",
    ("%NexGen%",),
)
for r in cur.fetchall():
    print(f"{r['draft_id']} | af={r['active_focus']} | st={r['status']} | {r['updated_at']}")
conn.close()
