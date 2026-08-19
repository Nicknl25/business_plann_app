import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import mysql.connector
conn = mysql.connector.connect(host='localhost', user='root', password='Lovers251979!', database='biz_plan_revert')
cur = conn.cursor()
cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE draft_id=%s", ('50658fff105e480c896f714fa519f22e',))
msgs = json.loads(cur.fetchone()[0])
print('n messages:', len(msgs))
for i, m in enumerate(msgs):
    role = m.get('role')
    txt = str(m.get('content') or m.get('text') or '')
    if any(s in txt for s in ('work on paper', 'closes about', 'believable range', 'closes')) or (role=='user' and i>90):
        print('='*90)
        print(i, role)
        print(txt[:3000])
