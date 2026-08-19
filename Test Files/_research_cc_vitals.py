import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import mysql.connector
conn = mysql.connector.connect(host='localhost', user='root', password='Lovers251979!', database='biz_plan_revert')
cur = conn.cursor()
cur.execute("DESCRIBE run_vitals_turns")
cols = [r[0] for r in cur.fetchall()]
print(cols)
cur.execute("SELECT run_id FROM run_vitals_runs WHERE draft_id=%s", ('50658fff105e480c896f714fa519f22e',))
rows = cur.fetchall()
print('runs:', rows)
