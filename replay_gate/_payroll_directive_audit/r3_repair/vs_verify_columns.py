import json, sys, datetime
sys.path.insert(0, r"C:/Users/IGNATI~1/AppData/Local/Temp/claude/C--dev-business-plann-app/e7c6ea70-948d-44f2-b6f4-4c8aaaadb609/scratchpad")
from pd_db import q
for tag, d in (("marchetti_3201a64c", "3201a64c%"), ("northwind_3c2224e1", "3c2224e1%")):
    before = json.load(open(r"C:\dev\business_plann_app\_r3_repair_snapshots\%s_BEFORE_full_row.json" % tag, encoding="utf-8"))
    r = q("SELECT * FROM intake_consult_drafts WHERE draft_id LIKE %s", (d,))[0]
    now = {k: (v.isoformat() if isinstance(v, (datetime.datetime, datetime.date)) else (v.decode() if isinstance(v, bytes) else v)) for k, v in r.items()}
    moved = [k for k in now if json.dumps(now[k], default=str) != json.dumps(before.get(k), default=str)]
    print(tag, "columns compared:", len(now), "moved:", moved)
