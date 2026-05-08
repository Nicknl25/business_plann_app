"""List intake_consult_drafts rows by business_name + active_focus."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = ROOT / "python"
for p in (str(PYTHON_DIR), str(PYTHON_DIR / "client_intake_and_finmo")):
  if p not in sys.path:
    sys.path.insert(0, p)
try:
  from dotenv import load_dotenv
  load_dotenv(ROOT / ".env", override=False)
except Exception:
  pass
import mysql.connector

conn = mysql.connector.connect(
  host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"),
  password=os.getenv("MYSQL_PASSWORD") or "", database=os.getenv("MYSQL_DB"),
  port=int(os.getenv("MYSQL_PORT") or "3306"),
)
cur = conn.cursor(dictionary=True)
cur.execute(
  "SELECT draft_id, client_id, business_name, active_focus, status, completed_at "
  "FROM intake_consult_drafts "
  "WHERE business_name IS NOT NULL AND TRIM(business_name) != '' "
  "ORDER BY completed_at DESC LIMIT 30"
)
for row in cur.fetchall():
  print(f"  {row['draft_id']} | {row.get('client_id') or '?':<25} | "
        f"{(row.get('business_name') or '')[:30]:<30} | "
        f"focus={row.get('active_focus')} | status={row.get('status')}")
cur.close()
conn.close()
