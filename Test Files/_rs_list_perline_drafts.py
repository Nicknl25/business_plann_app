import os
from dotenv import load_dotenv; import mysql.connector; load_dotenv()
c=mysql.connector.connect(host=os.getenv("MYSQL_HOST"),user=os.getenv("MYSQL_USER"),password=os.getenv("MYSQL_PASSWORD"),database=os.getenv("MYSQL_DB"),port=int(os.getenv("MYSQL_PORT") or 3306))
cur=c.cursor(dictionary=True)
cur.execute("SELECT draft_id,business_name,updated_at, planning_run_status FROM intake_consult_drafts WHERE model_input_json LIKE '%per_line_cogs_source%' ORDER BY updated_at DESC")
for r in cur.fetchall(): print(r["draft_id"][:8], r["planning_run_status"], r["updated_at"], r["business_name"])
