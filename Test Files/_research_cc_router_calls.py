import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import mysql.connector
conn = mysql.connector.connect(host='localhost', user='root', password='Lovers251979!', database='biz_plan_revert')
cur = conn.cursor()
cur.execute("DESCRIBE post_intake_gpt_response_store")
print([r[0] for r in cur.fetchall()])
cur.execute("SELECT COUNT(*) FROM post_intake_gpt_response_store WHERE draft_id=%s", ('50658fff105e480c896f714fa519f22e',))
print('rows for draft:', cur.fetchone())
