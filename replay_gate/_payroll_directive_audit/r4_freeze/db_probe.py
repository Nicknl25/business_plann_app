import sys; sys.path[:0] = ["python", "python/client_intake_and_finmo"]
from dotenv import load_dotenv; load_dotenv()
from intake_submission import get_mysql_connection
c = get_mysql_connection(autocommit=True) if "autocommit" in get_mysql_connection.__code__.co_varnames else get_mysql_connection()
cur = c.cursor()
cur.execute("SELECT COUNT(*) FROM intake_consult_drafts"); print("drafts_total", cur.fetchone()[0])
cur.execute("SELECT draft_id, client_id, business_name, created_at FROM intake_consult_drafts ORDER BY created_at DESC LIMIT 4")
for r in cur.fetchall(): print("latest_draft", *r)
cur.execute("SELECT planning_run_id, draft_id, run_status, created_at FROM planning_runs ORDER BY created_at DESC LIMIT 2")
for r in cur.fetchall(): print("latest_run", *r)
