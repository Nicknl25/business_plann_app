"""VS re-derivation: for the 8 class drafts, which quarters does the bare SUM
overstate MIN(closing, SUM(window))? Is Q1 among them (so the Q1 tie-out catches it)?"""
import os, sys, json, mysql.connector
from dotenv import load_dotenv
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(r"C:\dev\business_plann_app\.env")
IDS = ["e606a5ee","d7b337ca","8f1c539a","acbecef5","1b9b4e45","366f5f4d","ee72251f","df00b8e6"]
c = mysql.connector.connect(host=os.getenv('MYSQL_HOST'), user=os.getenv('MYSQL_USER'), password=os.getenv('MYSQL_PASSWORD'), database=os.getenv('MYSQL_DB'), autocommit=True)
cur = c.cursor(dictionary=True)
q1_caught = 0
for d in IDS:
    cur.execute("SELECT draft_id,business_name,finmo_json FROM intake_consult_drafts WHERE draft_id LIKE %s", (d+"%",))
    rows = cur.fetchall()
    if not rows: print(d, "NOT FOUND"); continue
    r = rows[0]
    qr = {int(x['quarter_index']): x for x in json.loads(r['finmo_json'])['quarter_rows'] if isinstance(x, dict)}
    bad = []
    for q in sorted(qr):
        window = [float(qr[w].get('debt_repayment') or 0.0) for w in range(q+1, q+5) if w in qr]
        closing = float(qr[q].get('debt_closing_balance') or 0.0)
        bare, clipped = sum(window), min(closing, sum(window))
        if bare - clipped > 1.0: bad.append((q, round(bare - clipped)))
    has_q1 = any(q == 1 for q, _ in bad)
    q1_caught += 1 if has_q1 else 0
    print(f"{d} {r['business_name'][:32]:34s} overstated quarters={[q for q,_ in bad]}  Q1_in_set={has_q1}  worst=${max([e for _,e in bad] or [0]):,}")
cur.close(); c.close()
print(f"\n{q1_caught} of {len(IDS)} carry a Q1 error the Q1 tie-out catches; {len(IDS)-q1_caught} silent.")
