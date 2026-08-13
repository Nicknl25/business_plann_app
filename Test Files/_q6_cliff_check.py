import json
import os
import sys

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
DRAFTS = [
    ("Sunny W2", "ee7cd6b20cc142429e576214b5cf199c"),
    ("Understory W2", "ea30f6dc23784a35a73ac7f4352c2721"),
    ("Blueprint W2", "49181987acf24de4adf0f5e8b79e5bff"),
    ("Glaze W2", "195d85e4345f4d9ab3e466d75bd58404"),
    ("Meridian clean", "0f8e1e1c5d8d414cb17e2c51f5860382"),
]
for label, d in DRAFTS:
    cur.execute("SELECT finmo_json FROM intake_consult_drafts WHERE draft_id=%s", (d,))
    fm = json.loads(cur.fetchone()["finmo_json"])
    rows = {int(float(r.get("quarter_index"))): r for r in fm.get("quarter_rows") or [] if isinstance(r, dict)}
    qoq = []
    for q in range(2, 13):
        prev = float((rows.get(q - 1) or {}).get("revenue") or 0)
        curr = float((rows.get(q) or {}).get("revenue") or 0)
        qoq.append(round((curr / prev - 1) * 100, 1) if prev > 0 else None)
    mx = max((v for v in qoq if v is not None), default=None)
    print(f"{label}: QoQ% Q2..Q12 = {qoq}  max={mx}")
cur.close()
conn.close()
