import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import mysql.connector
conn = mysql.connector.connect(host='localhost', user='root', password='Lovers251979!', database='biz_plan_revert')
cur = conn.cursor()
cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s", ('50658fff105e480c896f714fa519f22e',))
msgs = json.loads(cur.fetchone()[0])
for i in (96, 98, 100, 102, 104, 106, 108, 110, 118, 120):
    m = msgs[i]
    print('='*90)
    print(i, m.get('role'))
    print(str(m.get('content') or m.get('text') or '')[:2600])
