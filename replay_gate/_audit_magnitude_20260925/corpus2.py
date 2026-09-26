import sys, json, os
sys.path.insert(0, os.path.join(sys.argv[1], "python"))
sys.path.append(os.path.join(sys.argv[1], "python", "client_intake_and_finmo"))
from dotenv import load_dotenv; load_dotenv(os.path.join(sys.argv[1], ".env"), override=True)
from intake_submission import get_mysql_connection
c = get_mysql_connection(); cur = c.cursor()
cur.execute("SELECT messages_json FROM intake_consult_drafts WHERE updated_at >= '2026-08-01'")
seen = set(); out = []
for (m,) in cur.fetchall():
    try: msgs = json.loads(m or "[]")
    except Exception: continue
    for x in msgs:
        if isinstance(x, dict) and x.get("role") == "user":
            t = str(x.get("content") or "")
            if t and t not in seen:
                seen.add(t); out.append(t)
c.close()
old = json.load(open(os.path.join(os.path.dirname(__file__), "corpus.py"), encoding="utf-8")) if False else None
adv = json.loads(open(sys.argv[3], encoding="utf-8").read()) if len(sys.argv) > 3 else []
json.dump(out + adv, open(sys.argv[2], "w"))
print("corpus messages:", len(out), "+ adversarial", len(adv))
