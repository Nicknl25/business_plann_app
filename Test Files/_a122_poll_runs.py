"""A-122: block until the named drafts' planning runs reach a terminal state
(or the deadline). Prints a status line every ~60s and a final table."""
import os, sys, time
from dotenv import load_dotenv; load_dotenv()
import mysql.connector
ids = sys.argv[1].split(","); deadline = time.time() + int(sys.argv[2]) * 60
conn = mysql.connector.connect(host=os.getenv("MYSQL_HOST"), user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"), database=os.getenv("MYSQL_DB"), port=int(os.getenv("MYSQL_PORT") or 3306), autocommit=True)
TERMINAL = {"completed", "failed", "dead_letter", "error", "cancelled"}
def snap():
  cur = conn.cursor(dictionary=True)
  cur.execute("SELECT draft_id, planning_run_id, planning_run_status, planning_stage, planning_status FROM intake_consult_drafts WHERE draft_id IN (%s)" % ",".join(["%s"]*len(ids)), tuple(ids))
  rows = cur.fetchall(); cur.close(); return rows
while True:
  rows = snap()
  print(time.strftime("%H:%M:%S"), " | ".join(f"{r['draft_id'][:8]} {r['planning_run_status']} @{r['planning_stage']}" for r in rows), flush=True)
  if all((r["planning_run_status"] or "") in TERMINAL for r in rows): break
  if time.time() > deadline: print("DEADLINE"); break
  time.sleep(60)
for r in rows: print(r)
